"""Order processing service - simplified for Prisma schema."""

import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Union

from app.core.config import settings
from app.core.logging import get_logger
from app.models.customer import Customer
from app.models.order import Order, OrderStatus, EsimStatus
from app.schemas.order import (
    OrderProcessingResult,
    ProcessRefundRequest,
    ProcessRefundResponse,
    ProcessRefundErrorResponse,
    RefundRequest,
    RefundResponse,
    RefundStepResult,
)
from app.services.delivery_service import DeliveryService
from app.services.esim_service import ESimService
from app.services.notification_service import NotificationService
from app.services.stripe_service import StripeService

logger = get_logger(__name__)


class OrderService:
    """Service for order processing.

    Note: Orders are created by the Next.js frontend via Stripe checkout.
    This service handles webhook processing and order management.
    """

    def __init__(self):
        self.stripe = StripeService()
        self.esim = ESimService()
        self.delivery = DeliveryService()
        self.notifications = NotificationService()

    async def get_order_by_id(
        self,
        db: AsyncSession,
        order_id: int,
    ) -> Optional[Order]:
        """Get order by ID."""
        result = await db.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one_or_none()

    async def get_order_by_number(
        self,
        db: AsyncSession,
        order_number: str,
    ) -> Optional[Order]:
        """Get order by order number."""
        result = await db.execute(
            select(Order).where(Order.order_number == order_number)
        )
        return result.scalar_one_or_none()

    async def process_refund(
        self,
        db: AsyncSession,
        request: RefundRequest,
    ) -> RefundResponse:
        """Process a refund request.

        Trvel policy: No forms, no questions refunds.
        """
        order = await self.get_order_by_id(db, request.order_id)
        if not order:
            raise ValueError(f"Order not found: {request.order_id}")

        if order.status == OrderStatus.refunded:
            raise ValueError("Order already refunded")

        if not order.stripe_payment_intent_id:
            raise ValueError("No payment intent found for order")

        # Process Stripe refund
        refund = await self.stripe.create_refund(
            payment_intent_id=order.stripe_payment_intent_id,
            reason="requested_by_customer",
        )

        # Update order (use .value for PostgreSQL native enum compatibility)
        order.status = OrderStatus.refunded.value
        order.updatedAt = datetime.now(timezone.utc)

        await db.commit()

        # Get customer for notification
        customer = await db.get(Customer, order.customer_id)
        if customer:
            await self.delivery.send_refund_notification(
                email=customer.email,
                name=customer.name or "Customer",
                order_number=order.order_number,
                destination=order.destination_name,
                amount=order.amount_cents / 100,
                currency=order.currency,
                reason=request.reason or "Customer request",
            )

        logger.info(
            "refund_processed",
            order_id=order.id,
            order_number=order.order_number,
            amount_cents=order.amount_cents,
        )

        return RefundResponse(
            order_id=order.id,
            order_number=order.order_number,
            refund_id=refund.id,
            amount_cents=order.amount_cents,
            currency=order.currency,
            status="refunded",
            reason=request.reason,
        )

    async def provision_esim_for_order(
        self,
        db: AsyncSession,
        order_id: int,
    ) -> OrderProcessingResult:
        """Provision eSIM for an existing order.

        Called after payment is confirmed.
        """
        start_time = time.time()
        errors = []

        order = await self.get_order_by_id(db, order_id)
        if not order:
            return OrderProcessingResult(
                order_id=order_id,
                order_number="",
                status="failed",
                errors=["Order not found"],
            )

        result = OrderProcessingResult(
            order_id=order.id,
            order_number=order.order_number,
            status="processing",
        )

        try:
            # Update status to ordering (use .value for PostgreSQL native enum)
            order.esim_status = EsimStatus.ordering.value
            await db.flush()

            # Provision eSIM
            esim_data = await self.esim.provision_esim(
                bundle_name=order.bundle_name or "",
                destination=order.destination_slug,
                duration_days=order.duration,
            )
            result.esim_provisioned = True

            # Update order with eSIM data
            order.esim_status = EsimStatus.ordered.value
            order.esim_iccid = esim_data.get("iccid")
            order.esim_smdp_address = esim_data.get("smdp_address")
            order.esim_matching_id = esim_data.get("matching_id")
            order.esim_qr_code = esim_data.get("qr_code_data")
            order.esim_order_ref = esim_data.get("order_ref")
            order.esim_provisioned_at = datetime.now(timezone.utc)

            await db.flush()

            # Get customer for delivery
            customer = await db.get(Customer, order.customer_id)
            if not customer:
                raise ValueError("Customer not found")

            # Generate QR image
            qr_image = esim_data.get("qr_code_image")
            if not qr_image and esim_data.get("qr_code_data"):
                qr_image = self.esim._generate_qr_image(esim_data["qr_code_data"])

            # Deliver QR code
            delivery_result = await self.delivery.deliver_qr_code(
                customer_email=customer.email,
                customer_phone=customer.phone,
                customer_name=customer.name,
                order_number=order.order_number,
                destination=order.destination_name,
                plan_name=order.plan_name,
                duration_days=order.duration,
                qr_code_image=qr_image,
                qr_code_data=esim_data.get("qr_code_data", ""),
                activation_code=esim_data.get("matching_id"),
                sm_dp_address=esim_data.get("smdp_address"),
            )

            if delivery_result.get("success"):
                order.esim_status = EsimStatus.delivered.value
                order.esim_email_sent = True
                result.qr_delivered = True
                result.delivery_channel = delivery_result.get("channel")
            else:
                errors.append("Delivery failed")
                await self.notifications.alert_delivery_failure(
                    order_id=str(order.id),
                    order_number=order.order_number,
                    customer_email=customer.email,
                    attempts=delivery_result.get("attempts", []),
                )

            await db.commit()

            # Check SLA
            processing_time = time.time() - start_time
            result.processing_time_ms = int(processing_time * 1000)

            if processing_time > settings.sla_qr_delivery_seconds:
                await self.notifications.alert_sla_breach(
                    sla_type="qr_delivery",
                    order_id=str(order.id),
                    elapsed_seconds=processing_time,
                    threshold_seconds=settings.sla_qr_delivery_seconds,
                )

            result.status = "completed" if result.qr_delivered else "partial"
            result.errors = errors

            logger.info(
                "order_provisioned",
                order_id=order.id,
                order_number=order.order_number,
                processing_time_ms=result.processing_time_ms,
            )

            return result

        except Exception as e:
            logger.error(
                "order_provisioning_failed",
                order_id=order.id,
                error=str(e),
            )
            order.esim_status = EsimStatus.failed.value
            await db.commit()

            errors.append(str(e))
            result.status = "failed"
            result.errors = errors
            result.processing_time_ms = int((time.time() - start_time) * 1000)

            await self.notifications.alert_provisioning_failure(
                order_id=str(order.id),
                order_number=order.order_number,
                destination=order.destination_slug,
                provider="esimgo",
                error=str(e),
            )

            return result

    async def process_full_refund(
        self,
        db: AsyncSession,
        request: ProcessRefundRequest,
    ) -> Union[ProcessRefundResponse, ProcessRefundErrorResponse]:
        """Process a full refund with eSIM bundle recovery.

        Workflow:
        1. Find the order
        2. Verify eSIM hasn't been activated (no data used)
        3. Revoke the bundle from eSIM Go
        4. Refund the bundle to organization balance
        5. Process Stripe refund
        6. Send confirmation email

        If eSIM was activated, refund is denied unless force=True.
        """
        now = datetime.now(timezone.utc)
        steps: list[RefundStepResult] = []

        # Step 0: Find the order
        order = None
        customer = None

        if request.order_id:
            order = await self.get_order_by_id(db, request.order_id)
        elif request.order_number:
            order = await self.get_order_by_number(db, request.order_number)
        elif request.customer_email:
            # Find the most recent paid order for this customer
            result = await db.execute(
                select(Order)
                .join(Customer)
                .where(Customer.email == request.customer_email.lower())
                .where(Order.status == OrderStatus.paid)
                .order_by(Order.createdAt.desc())
                .limit(1)
            )
            order = result.scalar_one_or_none()

        if not order:
            return ProcessRefundErrorResponse(
                success=False,
                error="Order not found. Please provide a valid order_id, order_number, or customer_email.",
                error_code="order_not_found",
                order_id=request.order_id,
                order_number=request.order_number,
                customer_email=request.customer_email,
                timestamp=now,
            )

        # Get customer
        customer = await db.get(Customer, order.customer_id)

        # Check if already refunded
        if order.status == OrderStatus.refunded:
            return ProcessRefundErrorResponse(
                success=False,
                error="This order has already been refunded.",
                error_code="already_refunded",
                order_id=order.id,
                order_number=order.order_number,
                customer_email=customer.email if customer else None,
                destination_name=order.destination_name,
                timestamp=now,
            )

        # Check if payment intent exists
        if not order.stripe_payment_intent_id:
            return ProcessRefundErrorResponse(
                success=False,
                error="No payment record found for this order. Cannot process refund.",
                error_code="no_payment_intent",
                order_id=order.id,
                order_number=order.order_number,
                customer_email=customer.email if customer else None,
                destination_name=order.destination_name,
                timestamp=now,
            )

        # Step 1: Check if eSIM has been activated (data usage check)
        esim_bundle_revoked = False
        esim_bundle_refunded = False
        data_used_mb = 0.0

        if order.esim_iccid:
            try:
                usage_info = await self.esim.check_esim_data_usage(order.esim_iccid)
                data_used_mb = usage_info.get("data_used_mb", 0)
                eligible = usage_info.get("eligible_for_refund", False)

                steps.append(RefundStepResult(
                    step="eligibility_check",
                    success=eligible or request.force,
                    message="eSIM not activated" if eligible else f"eSIM used {data_used_mb} MB",
                    details={
                        "data_used_mb": data_used_mb,
                        "eligible": eligible,
                        "force_override": request.force,
                    },
                ))

                # If eSIM was used and not forcing, deny refund
                if not eligible and not request.force:
                    return ProcessRefundErrorResponse(
                        success=False,
                        error=f"eSIM has been activated and used {data_used_mb:.2f} MB of data. Refunds are only available for unused eSIMs.",
                        error_code="esim_activated",
                        order_id=order.id,
                        order_number=order.order_number,
                        customer_email=customer.email if customer else None,
                        destination_name=order.destination_name,
                        data_used_mb=data_used_mb,
                        timestamp=now,
                    )

            except Exception as e:
                logger.warning(
                    "esim_usage_check_failed",
                    order_id=order.id,
                    iccid=order.esim_iccid,
                    error=str(e),
                )
                steps.append(RefundStepResult(
                    step="eligibility_check",
                    success=True,  # Proceed if we can't check
                    message=f"Could not verify eSIM status: {str(e)}. Proceeding with refund.",
                    error=str(e),
                ))

            # Step 2: Revoke the bundle from eSIM
            if order.bundle_name:
                try:
                    revoke_result = await self.esim.revoke_bundle(
                        order.esim_iccid, order.bundle_name
                    )
                    esim_bundle_revoked = revoke_result.get("success", False)
                    steps.append(RefundStepResult(
                        step="bundle_revoke",
                        success=esim_bundle_revoked,
                        message=revoke_result.get("message", "Bundle revoked"),
                        error=revoke_result.get("error"),
                        details={"iccid": order.esim_iccid, "bundle": order.bundle_name},
                    ))

                    # Step 3: Refund the bundle to organization balance
                    if esim_bundle_revoked:
                        try:
                            usage_id = await self.esim.find_inventory_usage_id(order.bundle_name)
                            if usage_id:
                                refund_result = await self.esim.refund_bundle_to_balance(usage_id)
                                esim_bundle_refunded = refund_result.get("success", False)
                                steps.append(RefundStepResult(
                                    step="bundle_refund",
                                    success=esim_bundle_refunded,
                                    message=refund_result.get("message", "Bundle refunded to balance"),
                                    error=refund_result.get("error"),
                                    details={"usage_id": usage_id},
                                ))
                            else:
                                steps.append(RefundStepResult(
                                    step="bundle_refund",
                                    success=False,
                                    message="Could not find bundle in inventory for refund",
                                    error="usageId not found",
                                ))
                        except Exception as e:
                            logger.warning(
                                "bundle_refund_failed",
                                order_id=order.id,
                                error=str(e),
                            )
                            steps.append(RefundStepResult(
                                step="bundle_refund",
                                success=False,
                                message="Bundle refund failed",
                                error=str(e),
                            ))

                except Exception as e:
                    logger.warning(
                        "bundle_revoke_failed",
                        order_id=order.id,
                        iccid=order.esim_iccid,
                        bundle=order.bundle_name,
                        error=str(e),
                    )
                    steps.append(RefundStepResult(
                        step="bundle_revoke",
                        success=False,
                        message="Could not revoke bundle",
                        error=str(e),
                    ))
        else:
            # No eSIM provisioned yet, skip eSIM steps
            steps.append(RefundStepResult(
                step="eligibility_check",
                success=True,
                message="No eSIM provisioned - eligible for refund",
            ))

        # Step 4: Process Stripe refund
        stripe_refund_id = None
        already_refunded_in_stripe = False

        try:
            refund = await self.stripe.create_refund(
                payment_intent_id=order.stripe_payment_intent_id,
                reason="requested_by_customer",
            )
            stripe_refund_id = refund.id

            steps.append(RefundStepResult(
                step="stripe_refund",
                success=True,
                message=f"Payment refunded: {order.currency} ${order.amount_cents / 100:.2f}",
                details={"refund_id": stripe_refund_id, "amount": order.amount_cents / 100},
            ))

        except Exception as e:
            error_str = str(e)

            # Check if the charge was already refunded in Stripe
            if "already been refunded" in error_str or "charge_already_refunded" in error_str:
                logger.info(
                    "stripe_charge_already_refunded",
                    order_id=order.id,
                    payment_intent=order.stripe_payment_intent_id,
                )
                already_refunded_in_stripe = True
                steps.append(RefundStepResult(
                    step="stripe_refund",
                    success=True,
                    message="Payment was already refunded in Stripe",
                    details={"already_refunded": True},
                ))
            else:
                logger.error(
                    "stripe_refund_failed",
                    order_id=order.id,
                    error=error_str,
                )
                return ProcessRefundErrorResponse(
                    success=False,
                    error=f"Failed to process Stripe refund: {error_str}",
                    error_code="refund_failed",
                    order_id=order.id,
                    order_number=order.order_number,
                    customer_email=customer.email if customer else None,
                    destination_name=order.destination_name,
                    timestamp=now,
                )

        # Update order status (use .value for PostgreSQL native enum compatibility)
        order.status = OrderStatus.refunded.value
        order.updatedAt = now
        order.notes = (order.notes or "") + f"\nRefund processed: {request.reason or 'customer_request'}"
        if already_refunded_in_stripe:
            order.notes += " (Stripe: already refunded)"
        await db.commit()

        # Step 5: Send confirmation email
        email_sent = False
        if customer:
            try:
                await self.delivery.send_refund_notification(
                    email=customer.email,
                    name=customer.name or "Traveler",
                    order_number=order.order_number,
                    destination=order.destination_name,
                    amount=order.amount_cents / 100,
                    currency=order.currency,
                    reason=request.reason or "Customer request",
                )
                email_sent = True
                steps.append(RefundStepResult(
                    step="email_notification",
                    success=True,
                    message=f"Confirmation sent to {customer.email}",
                ))
            except Exception as e:
                logger.warning(
                    "refund_email_failed",
                    order_id=order.id,
                    error=str(e),
                )
                steps.append(RefundStepResult(
                    step="email_notification",
                    success=False,
                    message="Could not send confirmation email",
                    error=str(e),
                ))

        logger.info(
            "full_refund_processed",
            order_id=order.id,
            order_number=order.order_number,
            amount_cents=order.amount_cents,
            esim_bundle_revoked=esim_bundle_revoked,
            esim_bundle_refunded=esim_bundle_refunded,
            stripe_refund_id=stripe_refund_id,
            already_refunded_in_stripe=already_refunded_in_stripe,
        )

        amount_refunded = order.amount_cents / 100

        # Build appropriate message
        if already_refunded_in_stripe:
            message = f"Order confirmed refunded: ${amount_refunded:.2f} {order.currency} (payment was already refunded in Stripe)"
        else:
            message = f"Full refund processed: ${amount_refunded:.2f} {order.currency} refunded to customer"

        return ProcessRefundResponse(
            success=True,
            order_id=order.id,
            order_number=order.order_number,
            customer_email=customer.email if customer else "",
            destination_name=order.destination_name,
            plan_name=order.plan_name,
            amount_refunded=amount_refunded,
            currency=order.currency,
            stripe_refund_id=stripe_refund_id,
            esim_bundle_revoked=esim_bundle_revoked,
            esim_bundle_refunded=esim_bundle_refunded,
            steps=steps,
            message=message,
            timestamp=now,
        )
