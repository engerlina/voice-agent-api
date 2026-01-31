"""eSIM provisioning service for eSIM Go."""

import io
from typing import Optional

import httpx
import qrcode
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ESimService:
    """eSIM provisioning service using eSIM Go.

    Critical path operation - must complete within seconds.
    """

    API_BASE_URL = "https://api.esim-go.com/v2.5"

    def __init__(self):
        self.api_key = settings.esimgo_api_key

    def _get_headers(self) -> dict:
        """Get API request headers."""
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def provision_esim(
        self,
        bundle_name: str,
        order_reference: Optional[str] = None,
    ) -> dict:
        """Provision an eSIM from eSIM Go.

        Args:
            bundle_name: The eSIM Go bundle/plan name (e.g., "esim_1GB_7D_JP_V2")
            order_reference: Optional order reference for tracking

        Returns:
            dict with iccid, qr_code_data, activation_code, etc.
        """
        logger.info(
            "esim_provisioning_attempt",
            bundle=bundle_name,
            order_reference=order_reference,
        )

        async with httpx.AsyncClient() as client:
            # Apply bundle to get eSIM
            response = await client.post(
                f"{self.API_BASE_URL}/esims/apply",
                headers=self._get_headers(),
                json={
                    "type": "bundle",
                    "bundle": bundle_name,
                    "startTime": "now",
                    "Order": order_reference or "",
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            esim = data.get("esim", {})
            iccid = esim.get("iccid")

            # Get QR code data
            qr_data = await self._get_qr_code_data(iccid)

            result = {
                "provider": "esim_go",
                "provider_order_id": data.get("orderReference"),
                "provider_esim_id": esim.get("reference"),
                "iccid": iccid,
                "qr_code_data": qr_data.get("qrCodeData"),
                "qr_code_url": qr_data.get("qrCodeUrl"),
                "activation_code": qr_data.get("activationCode"),
                "sm_dp_address": qr_data.get("smdpAddress"),
                "raw_response": data,
            }

            # Generate QR code image
            if result.get("qr_code_data"):
                result["qr_code_image"] = self._generate_qr_image(result["qr_code_data"])

            logger.info(
                "esim_provisioned",
                iccid=iccid,
                order_reference=order_reference,
            )

            return result

    async def _get_qr_code_data(self, iccid: str) -> dict:
        """Get QR code data for an eSIM."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.API_BASE_URL}/esims/{iccid}",
                headers=self._get_headers(),
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            return {
                "qrCodeData": data.get("qrCodeData") or data.get("lpaString"),
                "qrCodeUrl": data.get("qrCodeUrl"),
                "activationCode": data.get("activationCode") or data.get("matchingId"),
                "smdpAddress": data.get("smdpAddress") or data.get("smdp"),
            }

    async def get_esim_status(self, iccid: str) -> dict:
        """Get eSIM activation and usage status.

        Used for 10-minute connection guarantee monitoring.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.API_BASE_URL}/esims/{iccid}",
                headers=self._get_headers(),
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            status = data.get("status", "").lower()
            return {
                "status": status,
                "activated": status in ["active", "installed", "in_use"],
                "data_used_mb": data.get("dataUsed", 0) / (1024 * 1024) if data.get("dataUsed") else 0,
                "data_limit_mb": data.get("dataLimit", 0) / (1024 * 1024) if data.get("dataLimit") else None,
                "expiry_date": data.get("expiryDate"),
                "raw_response": data,
            }

    async def check_activation_status(self, iccid: str) -> dict:
        """Check if an eSIM has been activated.

        Alias for get_esim_status for backward compatibility.
        """
        return await self.get_esim_status(iccid)

    async def get_bundles(self, country_code: Optional[str] = None) -> list:
        """Get available eSIM bundles/plans.

        Args:
            country_code: Optional ISO country code to filter (e.g., "JP", "TH")
        """
        async with httpx.AsyncClient() as client:
            params = {}
            if country_code:
                params["country"] = country_code.upper()

            response = await client.get(
                f"{self.API_BASE_URL}/bundles",
                headers=self._get_headers(),
                params=params,
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json().get("bundles", [])

    async def cancel_esim(self, iccid: str) -> bool:
        """Cancel/deactivate an eSIM (for refunds).

        Note: Not all eSIMs can be cancelled depending on their state.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.API_BASE_URL}/esims/{iccid}",
                    headers=self._get_headers(),
                    timeout=10.0,
                )
                if response.status_code == 200:
                    logger.info("esim_cancelled", iccid=iccid)
                    return True
                else:
                    logger.warning(
                        "esim_cancellation_failed",
                        iccid=iccid,
                        status=response.status_code,
                    )
                    return False
        except Exception as e:
            logger.error("esim_cancellation_error", iccid=iccid, error=str(e))
            return False

    # =========================================================================
    # Refund-related methods (eSIM Go bundle management)
    # =========================================================================

    async def get_esim_bundles_applied(self, iccid: str) -> dict:
        """Get list of bundles applied to an eSIM.

        Endpoint: GET /esims/{iccid}/bundles
        Used to find the bundle name and assignment ID for revocation.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.API_BASE_URL}/esims/{iccid}/bundles",
                headers=self._get_headers(),
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            bundles = data.get("bundles", [])
            return {
                "bundles": bundles,
                "count": len(bundles),
                "raw_response": data,
            }

    async def check_esim_data_usage(self, iccid: str) -> dict:
        """Check if eSIM has consumed any data.

        Returns eligibility for refund based on data usage.
        If any data has been used, eSIM is NOT eligible for refund.
        """
        status = await self.get_esim_status(iccid)

        data_used_bytes = status.get("raw_response", {}).get("dataUsed", 0)
        data_used_mb = data_used_bytes / (1024 * 1024) if data_used_bytes else 0

        # Get bundle info for more details
        bundles_info = await self.get_esim_bundles_applied(iccid)
        bundles = bundles_info.get("bundles", [])

        # Check if any bundle has started (has data usage)
        any_bundle_started = False
        for bundle in bundles:
            if bundle.get("dataUsed", 0) > 0:
                any_bundle_started = True
                break

        eligible_for_refund = data_used_bytes == 0 and not any_bundle_started

        return {
            "iccid": iccid,
            "data_used_bytes": data_used_bytes,
            "data_used_mb": round(data_used_mb, 2),
            "any_bundle_started": any_bundle_started,
            "eligible_for_refund": eligible_for_refund,
            "status": status.get("status"),
            "bundles": bundles,
        }

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def revoke_bundle(self, iccid: str, bundle_name: str) -> dict:
        """Revoke a bundle from an eSIM.

        Endpoint: DELETE /esims/{iccid}/bundles/{name}
        This removes the bundle from the eSIM and returns it to inventory.

        Args:
            iccid: The ICCID of the eSIM
            bundle_name: The bundle name (case-sensitive, e.g., "esim_1GB_7D_JP_V2")

        Returns:
            dict with success status and details
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.API_BASE_URL}/esims/{iccid}/bundles/{bundle_name}",
                    headers=self._get_headers(),
                    timeout=15.0,
                )

                if response.status_code in [200, 204]:
                    logger.info(
                        "bundle_revoked",
                        iccid=iccid,
                        bundle_name=bundle_name,
                    )
                    return {
                        "success": True,
                        "iccid": iccid,
                        "bundle_name": bundle_name,
                        "message": "Bundle revoked and returned to inventory",
                    }
                else:
                    error_data = response.json() if response.content else {}
                    logger.warning(
                        "bundle_revocation_failed",
                        iccid=iccid,
                        bundle_name=bundle_name,
                        status=response.status_code,
                        error=error_data,
                    )
                    return {
                        "success": False,
                        "iccid": iccid,
                        "bundle_name": bundle_name,
                        "error": error_data.get("message", f"HTTP {response.status_code}"),
                    }
        except Exception as e:
            logger.error(
                "bundle_revocation_error",
                iccid=iccid,
                bundle_name=bundle_name,
                error=str(e),
            )
            return {
                "success": False,
                "iccid": iccid,
                "bundle_name": bundle_name,
                "error": str(e),
            }

    async def get_inventory(self, bundle_name: Optional[str] = None) -> dict:
        """Get organization inventory to find usageId for refund.

        Endpoint: GET /inventory
        Used to find the usageId of a returned bundle for refund processing.

        Args:
            bundle_name: Optional filter by bundle name
        """
        async with httpx.AsyncClient() as client:
            params = {}
            if bundle_name:
                params["bundle"] = bundle_name

            response = await client.get(
                f"{self.API_BASE_URL}/inventory",
                headers=self._get_headers(),
                params=params,
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            inventory = data.get("inventory", [])
            return {
                "inventory": inventory,
                "count": len(inventory),
                "raw_response": data,
            }

    async def find_inventory_usage_id(self, bundle_name: str) -> Optional[str]:
        """Find the usageId for a specific bundle in inventory.

        Used after revoking a bundle to get the usageId needed for refund.
        """
        inventory = await self.get_inventory(bundle_name=bundle_name)

        for item in inventory.get("inventory", []):
            if item.get("bundle") == bundle_name and item.get("quantity", 0) > 0:
                return item.get("usageId")

        return None

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def refund_bundle_to_balance(self, usage_id: str, quantity: int = 1) -> dict:
        """Refund a bundle from inventory back to organization balance.

        Endpoint: POST /inventory/refund
        This refunds the bundle credit to the organization's eSIM Go balance.

        Args:
            usage_id: The usageId from inventory (found via get_inventory)
            quantity: Number of bundles to refund (default 1)

        Important restrictions:
        - Bundle must not have started (no data consumed)
        - Must be within permitted refund period (typically 60 days)
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.API_BASE_URL}/inventory/refund",
                    headers=self._get_headers(),
                    json={
                        "usageId": usage_id,
                        "quantity": quantity,
                    },
                    timeout=15.0,
                )

                if response.status_code in [200, 201]:
                    data = response.json() if response.content else {}
                    logger.info(
                        "bundle_refunded_to_balance",
                        usage_id=usage_id,
                        quantity=quantity,
                    )
                    return {
                        "success": True,
                        "usage_id": usage_id,
                        "quantity": quantity,
                        "message": "Bundle refunded to organization balance",
                        "raw_response": data,
                    }
                else:
                    error_data = response.json() if response.content else {}
                    logger.warning(
                        "bundle_refund_failed",
                        usage_id=usage_id,
                        status=response.status_code,
                        error=error_data,
                    )
                    return {
                        "success": False,
                        "usage_id": usage_id,
                        "error": error_data.get("message", f"HTTP {response.status_code}"),
                    }
        except Exception as e:
            logger.error(
                "bundle_refund_error",
                usage_id=usage_id,
                error=str(e),
            )
            return {
                "success": False,
                "usage_id": usage_id,
                "error": str(e),
            }

    async def process_full_bundle_refund(self, iccid: str, bundle_name: str) -> dict:
        """Process complete bundle refund: revoke from eSIM and refund to balance.

        This is a convenience method that handles the full refund workflow:
        1. Revoke the bundle from the eSIM
        2. Find the usageId in inventory
        3. Refund the bundle to organization balance

        Args:
            iccid: The ICCID of the eSIM
            bundle_name: The bundle name to revoke and refund

        Returns:
            dict with success status and details of each step
        """
        result = {
            "success": False,
            "iccid": iccid,
            "bundle_name": bundle_name,
            "steps": {
                "revoke": None,
                "find_usage_id": None,
                "refund": None,
            },
            "error": None,
        }

        # Step 1: Revoke the bundle from the eSIM
        revoke_result = await self.revoke_bundle(iccid, bundle_name)
        result["steps"]["revoke"] = revoke_result

        if not revoke_result.get("success"):
            result["error"] = f"Failed to revoke bundle: {revoke_result.get('error')}"
            return result

        # Step 2: Find the usageId in inventory
        usage_id = await self.find_inventory_usage_id(bundle_name)
        result["steps"]["find_usage_id"] = {"usage_id": usage_id}

        if not usage_id:
            # Bundle was revoked but we couldn't find it in inventory
            # This might be okay - log a warning but don't fail
            logger.warning(
                "usage_id_not_found_after_revoke",
                iccid=iccid,
                bundle_name=bundle_name,
            )
            result["steps"]["refund"] = {
                "skipped": True,
                "reason": "usageId not found in inventory",
            }
            result["success"] = True  # Revoke succeeded, that's the main thing
            result["error"] = "Bundle revoked but inventory refund skipped (usageId not found)"
            return result

        # Step 3: Refund the bundle to organization balance
        refund_result = await self.refund_bundle_to_balance(usage_id)
        result["steps"]["refund"] = refund_result

        if refund_result.get("success"):
            result["success"] = True
        else:
            result["error"] = f"Revoke succeeded but balance refund failed: {refund_result.get('error')}"

        return result

    def _generate_qr_image(self, qr_data: str) -> bytes:
        """Generate QR code image from data string."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
