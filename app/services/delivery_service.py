"""Multi-channel delivery service for QR codes (email, SMS)."""

import base64
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from twilio.rest import Client as TwilioClient

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class DeliveryService:
    """Service for multi-channel QR code delivery.

    Implements redundant delivery: Email → SMS
    Critical for SLA: QR code must reach customer within 30 seconds.
    """

    def __init__(self):
        self.resend_api_key = settings.resend_api_key
        self.from_email = settings.resend_from_email
        self.from_name = settings.resend_from_name

        # Only initialize Twilio if credentials are provided
        if settings.twilio_account_sid and settings.twilio_auth_token:
            self.twilio = TwilioClient(
                settings.twilio_account_sid,
                settings.twilio_auth_token,
            )
        else:
            self.twilio = None

    async def deliver_qr_code(
        self,
        customer_email: str,
        customer_phone: Optional[str],
        customer_name: str,
        order_number: str,
        destination: str,
        plan_name: str,
        duration_days: int,
        qr_code_image: bytes,
        qr_code_data: str,
        activation_code: Optional[str] = None,
        sm_dp_address: Optional[str] = None,
    ) -> dict:
        """Deliver QR code with automatic fallback.

        Priority: Email → SMS
        Returns: {"channel": "email|sms", "success": bool, "message_id": str}
        """
        result = {
            "channel": None,
            "success": False,
            "message_id": None,
            "attempts": [],
        }

        # Attempt 1: Email (primary)
        try:
            email_result = await self.send_qr_email(
                email=customer_email,
                name=customer_name,
                order_number=order_number,
                destination=destination,
                plan_name=plan_name,
                duration_days=duration_days,
                qr_code_image=qr_code_image,
                activation_code=activation_code,
                sm_dp_address=sm_dp_address,
            )
            result["attempts"].append({"channel": "email", "success": True})
            result["channel"] = "email"
            result["success"] = True
            result["message_id"] = email_result.get("message_id")
            return result
        except Exception as e:
            logger.warning("email_delivery_failed", email=customer_email, error=str(e))
            result["attempts"].append({"channel": "email", "success": False, "error": str(e)})

        # Attempt 2: SMS (if phone available and Twilio configured)
        if customer_phone and self.twilio:
            try:
                sms_result = await self.send_qr_sms(
                    phone=customer_phone,
                    order_number=order_number,
                    destination=destination,
                    qr_code_data=qr_code_data,
                )
                result["attempts"].append({"channel": "sms", "success": True})
                result["channel"] = "sms"
                result["success"] = True
                result["message_id"] = sms_result.get("message_id")
                return result
            except Exception as e:
                logger.warning("sms_delivery_failed", phone=customer_phone, error=str(e))
                result["attempts"].append({"channel": "sms", "success": False, "error": str(e)})

        logger.error(
            "all_delivery_channels_failed",
            order_number=order_number,
            attempts=result["attempts"],
        )
        return result

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def send_qr_email(
        self,
        email: str,
        name: str,
        order_number: str,
        destination: str,
        plan_name: str,
        duration_days: int,
        qr_code_image: bytes,
        activation_code: Optional[str] = None,
        sm_dp_address: Optional[str] = None,
    ) -> dict:
        """Send QR code via email using Resend."""
        first_name = name.split()[0] if name else "there"
        logo_url = "https://www.trvel.co/android-chrome-192x192.png"

        # HTML email template - matches trvel-website styling
        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
</head>
<body style="font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #010326; margin: 0; padding: 0; background-color: #fdfbf8;">
  <div style="max-width: 600px; margin: 0 auto; padding: 24px 20px;">

    <!-- Header with Logo -->
    <div style="text-align: center; margin-bottom: 20px;">
      <img src="{logo_url}" alt="Trvel" width="48" height="48" style="border-radius: 12px; margin-bottom: 8px;">
      <h1 style="color: #63BFBF; font-size: 28px; margin: 0; font-weight: 700;">trvel</h1>
    </div>

    <!-- Main Card -->
    <div style="background: white; border-radius: 24px; padding: 40px 32px; box-shadow: 0 4px 24px rgba(99, 191, 191, 0.15);">

      <!-- Greeting -->
      <p style="font-size: 18px; color: #010326; margin: 0 0 24px;">Hey {first_name}! 👋</p>

      <!-- Success Message -->
      <div style="background: linear-gradient(135deg, #63BFBF 0%, #75cfcf 100%); border-radius: 16px; padding: 24px; margin-bottom: 32px; text-align: center;">
        <p style="color: white; font-size: 20px; font-weight: 600; margin: 0 0 8px;">Your eSIM is ready!</p>
        <p style="color: rgba(255,255,255,0.9); margin: 0; font-size: 15px;">Scan the QR code below to install</p>
      </div>

      <!-- Order Number Badge -->
      <div style="text-align: center; margin-bottom: 32px;">
        <span style="display: inline-block; background: #e8f7f7; border: 2px solid #63BFBF; color: #4fa9a9; padding: 8px 20px; border-radius: 100px; font-weight: 600; font-size: 14px; letter-spacing: 0.5px;">
          Order {order_number}
        </span>
      </div>

      <!-- QR Code Section -->
      <div style="background: #fdfbf8; border-radius: 16px; padding: 24px; margin-bottom: 32px; text-align: center;">
        <h3 style="font-size: 16px; color: #010326; margin: 0 0 16px; font-weight: 600;">📱 Your eSIM QR Code</h3>
        <div style="background: white; border-radius: 12px; padding: 16px; display: inline-block; border: 2px solid #F2E2CE;">
          <img src="cid:qrcode" alt="eSIM QR Code" width="200" height="200" style="display: block;">
        </div>
        <p style="margin: 16px 0 8px; color: #585b76; font-size: 13px;">Scan this code from another device (laptop/tablet)</p>
      </div>

      <!-- Detailed Installation Instructions -->
      <div style="background: white; border: 2px solid #63BFBF; border-radius: 16px; padding: 24px; margin-bottom: 32px;">
        <h3 style="font-size: 16px; color: #010326; margin: 0 0 20px; font-weight: 600;">📲 Step-by-step Installation</h3>

        <!-- iPhone Instructions -->
        <div style="margin-bottom: 20px;">
          <p style="margin: 0 0 12px; color: #010326; font-weight: 600; font-size: 14px;"> iPhone (iOS 17.4+)</p>
          <ol style="margin: 0; padding-left: 20px; color: #585b76; font-size: 14px; line-height: 1.8;">
            <li>Open <strong>Settings</strong> → <strong>Mobile Data</strong> → <strong>Add eSIM</strong></li>
            <li>Tap <strong>"Use QR Code"</strong></li>
            <li>Point camera at the QR code above</li>
            <li>Tap <strong>"Add eSIM"</strong> when prompted</li>
            <li>Label it as "Travel" or "{destination}"</li>
          </ol>
        </div>

        <!-- Android Instructions -->
        <div style="margin-bottom: 20px;">
          <p style="margin: 0 0 12px; color: #010326; font-weight: 600; font-size: 14px;">🤖 Android</p>
          <ol style="margin: 0; padding-left: 20px; color: #585b76; font-size: 14px; line-height: 1.8;">
            <li>Open <strong>Settings</strong> → <strong>Network & Internet</strong> → <strong>SIMs</strong></li>
            <li>Tap <strong>"Add eSIM"</strong> or <strong>"+"</strong></li>
            <li>Select <strong>"Scan QR code"</strong></li>
            <li>Point camera at the QR code above</li>
            <li>Follow prompts to complete setup</li>
          </ol>
        </div>

        <!-- Pro Tips -->
        <div style="background: #e8f7f7; border-radius: 12px; padding: 16px;">
          <p style="margin: 0 0 8px; color: #4fa9a9; font-weight: 600; font-size: 14px;">💡 Pro Tips</p>
          <ul style="margin: 0; padding-left: 18px; color: #585b76; font-size: 13px; line-height: 1.7;">
            <li><strong>Install before you travel</strong> - Set it up on WiFi at home</li>
            <li><strong>Don't delete it!</strong> - The QR code can only be used once</li>
            <li><strong>When you land:</strong> Turn on <strong>Data Roaming</strong> for the eSIM</li>
            <li>Your data plan starts when you first connect to a network in {destination}</li>
          </ul>
        </div>
      </div>

      <!-- Order Details -->
      <div style="background: #fdfbf8; border-radius: 16px; padding: 24px; margin-bottom: 32px;">
        <table style="width: 100%; border-collapse: collapse;">
          <tr>
            <td style="color: #585b76; padding: 12px 0; border-bottom: 1px solid #F2E2CE; font-size: 15px;">Destination</td>
            <td style="font-weight: 600; color: #010326; text-align: right; padding: 12px 0; border-bottom: 1px solid #F2E2CE; font-size: 15px;">🌏 {destination}</td>
          </tr>
          <tr>
            <td style="color: #585b76; padding: 12px 0; border-bottom: 1px solid #F2E2CE; font-size: 15px;">Plan</td>
            <td style="font-weight: 600; color: #010326; text-align: right; padding: 12px 0; border-bottom: 1px solid #F2E2CE; font-size: 15px;">{plan_name} ({duration_days} days)</td>
          </tr>
          <tr>
            <td style="color: #585b76; padding: 12px 0; font-size: 15px;">Data</td>
            <td style="font-weight: 600; color: #63BFBF; text-align: right; padding: 12px 0; font-size: 15px;">Unlimited</td>
          </tr>
        </table>
      </div>

      <!-- Support Card -->
      <div style="background: linear-gradient(135deg, #F2E2CE 0%, #f7efe4 100%); border-radius: 16px; padding: 20px; text-align: center;">
        <p style="margin: 0 0 4px; color: #010326; font-weight: 600;">Questions? I'm here to help!</p>
        <p style="margin: 0; color: #585b76; font-size: 14px;">
          Reply to this email or call us on +61 3 4052 7555
        </p>
      </div>
    </div>

    <!-- Personal Sign-off -->
    <div style="margin-top: 32px; padding: 0 8px;">
      <p style="color: #585b76; margin: 0 0 16px; font-size: 15px;">
        Thanks for choosing Trvel for your {destination} trip! If you have any questions at all, just reply to this email - I personally read and respond to every message.
      </p>
      <p style="color: #010326; margin: 0; font-weight: 500;">
        Safe travels! ✈️<br>
        <span style="color: #63BFBF; font-weight: 600;">Jonathan</span><br>
        <span style="color: #585b76; font-size: 14px; font-weight: 400;">Founder of Trvel</span>
      </p>
    </div>

    <!-- Footer -->
    <div style="text-align: center; margin-top: 40px; padding-top: 24px; border-top: 1px solid #F2E2CE;">
      <p style="color: #888a9d; font-size: 12px; margin: 0;">
        Trvel • Travel eSIMs made simple<br>
        <a href="https://www.trvel.co" style="color: #63BFBF; text-decoration: none;">trvel.co</a>
      </p>
    </div>
  </div>
</body>
</html>"""

        # Encode QR code image as base64
        encoded_qr = base64.b64encode(qr_code_image).decode()

        # Send via Resend API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"{self.from_name} <{self.from_email}>",
                    "to": [email],
                    "subject": f"Your {destination} eSIM is ready! ✈️",
                    "html": html_content,
                    "attachments": [
                        {
                            "filename": "esim-qr-code.png",
                            "content": encoded_qr,
                            "content_id": "qrcode",
                        }
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()

        logger.info(
            "email_sent",
            email=email,
            order_number=order_number,
            message_id=data.get("id"),
        )

        return {
            "success": True,
            "message_id": data.get("id"),
        }

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def send_qr_sms(
        self,
        phone: str,
        order_number: str,
        destination: str,
        qr_code_data: str,
    ) -> dict:
        """Send QR code link via SMS."""
        # Build the QR viewer URL
        qr_viewer_url = f"{settings.api_base_url}/api/v1/esim/{order_number}"

        # SMS has character limits, so send a link
        message_body = (
            f"Trvel: Your {destination} eSIM is ready!\n\n"
            f"View & scan your QR code:\n"
            f"{qr_viewer_url}\n\n"
            f"10-min connection guarantee."
        )

        message = self.twilio.messages.create(
            body=message_body,
            from_=settings.twilio_phone_number,
            to=phone,
        )

        logger.info(
            "sms_sent",
            phone=phone[-4:],  # Log only last 4 digits
            order_number=order_number,
            sid=message.sid,
        )

        return {
            "success": message.status in ["queued", "sent"],
            "message_id": message.sid,
        }

    async def resend_qr_code(
        self,
        channel: str,
        customer_email: str,
        customer_phone: Optional[str],
        customer_name: str,
        order_number: str,
        destination: str,
        plan_name: str,
        duration_days: int,
        qr_code_image: bytes,
        qr_code_data: str,
        activation_code: Optional[str] = None,
        sm_dp_address: Optional[str] = None,
    ) -> dict:
        """Resend QR code through specified channel.

        Args:
            channel: 'email', 'sms', or 'auto' (email first, SMS fallback)

        Returns:
            {"channel": "email|sms", "success": bool, "message_id": str, "message": str}
        """
        result = {
            "channel": None,
            "success": False,
            "message_id": None,
            "message": "",
        }

        if channel == "email":
            try:
                email_result = await self.send_qr_email(
                    email=customer_email,
                    name=customer_name,
                    order_number=order_number,
                    destination=destination,
                    plan_name=plan_name,
                    duration_days=duration_days,
                    qr_code_image=qr_code_image,
                    activation_code=activation_code,
                    sm_dp_address=sm_dp_address,
                )
                result["channel"] = "email"
                result["success"] = True
                result["message_id"] = email_result.get("message_id")
                result["message"] = f"QR code sent to {customer_email}"
                logger.info(
                    "qr_resend_email_success",
                    order_number=order_number,
                    email=customer_email,
                )
                return result
            except Exception as e:
                logger.error("qr_resend_email_failed", order_number=order_number, error=str(e))
                result["message"] = f"Failed to send email: {str(e)}"
                return result

        elif channel == "sms":
            if not customer_phone:
                result["message"] = "No phone number available for SMS delivery"
                return result
            if not self.twilio:
                result["message"] = "SMS service not configured"
                return result

            try:
                sms_result = await self.send_qr_sms(
                    phone=customer_phone,
                    order_number=order_number,
                    destination=destination,
                    qr_code_data=qr_code_data,
                )
                result["channel"] = "sms"
                result["success"] = True
                result["message_id"] = sms_result.get("message_id")
                result["message"] = f"QR code link sent to {customer_phone[-4:].rjust(len(customer_phone), '*')}"
                logger.info(
                    "qr_resend_sms_success",
                    order_number=order_number,
                    phone_last4=customer_phone[-4:],
                )
                return result
            except Exception as e:
                logger.error("qr_resend_sms_failed", order_number=order_number, error=str(e))
                result["message"] = f"Failed to send SMS: {str(e)}"
                return result

        elif channel == "auto":
            # Try email first, then SMS as fallback
            full_result = await self.deliver_qr_code(
                customer_email=customer_email,
                customer_phone=customer_phone,
                customer_name=customer_name,
                order_number=order_number,
                destination=destination,
                plan_name=plan_name,
                duration_days=duration_days,
                qr_code_image=qr_code_image,
                qr_code_data=qr_code_data,
                activation_code=activation_code,
                sm_dp_address=sm_dp_address,
            )
            result["channel"] = full_result.get("channel")
            result["success"] = full_result.get("success", False)
            result["message_id"] = full_result.get("message_id")
            if result["success"]:
                result["message"] = f"QR code sent via {result['channel']}"
            else:
                result["message"] = "Failed to deliver QR code through any channel"
            return result

        else:
            result["message"] = f"Invalid channel: {channel}. Use 'email', 'sms', or 'auto'"
            return result

    async def send_refund_notification(
        self,
        email: str,
        name: str,
        order_number: str,
        destination: str,
        amount: float,
        currency: str,
        reason: str,
    ) -> dict:
        """Send refund confirmation email - styled to match Trvel branding."""
        first_name = name.split()[0] if name else "there"
        logo_url = "https://www.trvel.co/android-chrome-192x192.png"

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
</head>
<body style="font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #010326; margin: 0; padding: 0; background-color: #fdfbf8;">
  <div style="max-width: 600px; margin: 0 auto; padding: 24px 20px;">

    <!-- Header with Logo -->
    <div style="text-align: center; margin-bottom: 20px;">
      <img src="{logo_url}" alt="Trvel" width="48" height="48" style="border-radius: 12px; margin-bottom: 8px;">
      <h1 style="color: #63BFBF; font-size: 28px; margin: 0; font-weight: 700;">trvel</h1>
    </div>

    <!-- Main Card -->
    <div style="background: white; border-radius: 24px; padding: 40px 32px; box-shadow: 0 4px 24px rgba(99, 191, 191, 0.15);">

      <!-- Greeting -->
      <p style="font-size: 18px; color: #010326; margin: 0 0 24px;">Hey {first_name},</p>

      <!-- Refund Confirmation Banner -->
      <div style="background: linear-gradient(135deg, #63BFBF 0%, #75cfcf 100%); border-radius: 16px; padding: 24px; margin-bottom: 32px; text-align: center;">
        <p style="color: white; font-size: 20px; font-weight: 600; margin: 0 0 8px;">Refund Processed ✓</p>
        <p style="color: rgba(255,255,255,0.9); margin: 0; font-size: 15px;">Your money is on its way back</p>
      </div>

      <!-- Refund Details -->
      <div style="background: #fdfbf8; border-radius: 16px; padding: 24px; margin-bottom: 32px;">
        <table style="width: 100%; border-collapse: collapse;">
          <tr>
            <td style="color: #585b76; padding: 12px 0; border-bottom: 1px solid #F2E2CE; font-size: 15px;">Order Number</td>
            <td style="font-weight: 600; color: #010326; text-align: right; padding: 12px 0; border-bottom: 1px solid #F2E2CE; font-size: 15px;">{order_number}</td>
          </tr>
          <tr>
            <td style="color: #585b76; padding: 12px 0; border-bottom: 1px solid #F2E2CE; font-size: 15px;">Plan</td>
            <td style="font-weight: 600; color: #010326; text-align: right; padding: 12px 0; border-bottom: 1px solid #F2E2CE; font-size: 15px;">🌏 {destination}</td>
          </tr>
          <tr>
            <td style="color: #585b76; padding: 12px 0; font-size: 15px;">Refund Amount</td>
            <td style="font-weight: 600; color: #63BFBF; text-align: right; padding: 12px 0; font-size: 18px;">${amount:.2f} {currency}</td>
          </tr>
        </table>
      </div>

      <!-- Timeline -->
      <div style="background: #e8f7f7; border-radius: 12px; padding: 20px; margin-bottom: 32px;">
        <p style="margin: 0 0 8px; color: #4fa9a9; font-weight: 600; font-size: 14px;">⏱️ What happens next?</p>
        <p style="margin: 0; color: #585b76; font-size: 14px; line-height: 1.7;">
          Your refund has been processed and will appear in your account within <strong>5-10 business days</strong>, depending on your bank or card provider.
        </p>
      </div>

      <!-- Message -->
      <p style="color: #585b76; font-size: 15px; margin: 0 0 24px; line-height: 1.7;">
        We're sorry this plan didn't work out for your trip. If there's anything we could have done better, just reply to this email—we'd love to hear your feedback.
      </p>

      <!-- CTA for future -->
      <div style="background: linear-gradient(135deg, #F2E2CE 0%, #f7efe4 100%); border-radius: 16px; padding: 20px; text-align: center; margin-bottom: 24px;">
        <p style="margin: 0 0 8px; color: #010326; font-weight: 600; font-size: 15px;">Planning another trip?</p>
        <p style="margin: 0; color: #585b76; font-size: 14px;">
          We'd love to help you stay connected. Use code <strong style="color: #63BFBF;">NEXTTRIP</strong> for 10% off your next order.
        </p>
      </div>

      <!-- Support Card -->
      <div style="text-align: center;">
        <p style="margin: 0 0 4px; color: #010326; font-weight: 600;">Questions about your refund?</p>
        <p style="margin: 0; color: #585b76; font-size: 14px;">
          Email <a href="mailto:support@trvel.co" style="color: #63BFBF; text-decoration: none;">support@trvel.co</a> or call <a href="tel:+61340527555" style="color: #63BFBF; text-decoration: none;">+61 3 4052 7555</a>
        </p>
      </div>
    </div>

    <!-- Personal Sign-off -->
    <div style="margin-top: 32px; padding: 0 8px;">
      <p style="color: #585b76; margin: 0 0 16px; font-size: 15px;">
        Thanks for giving Trvel a try. We hope to help you stay connected on a future adventure!
      </p>
      <p style="color: #010326; margin: 0; font-weight: 500;">
        Safe travels! ✈️<br>
        <span style="color: #63BFBF; font-weight: 600;">Jonathan</span><br>
        <span style="color: #585b76; font-size: 14px; font-weight: 400;">Founder of Trvel</span>
      </p>
    </div>

    <!-- Footer -->
    <div style="text-align: center; margin-top: 40px; padding-top: 24px; border-top: 1px solid #F2E2CE;">
      <p style="color: #888a9d; font-size: 12px; margin: 0;">
        Trvel • Travel eSIMs made simple<br>
        <a href="https://www.trvel.co" style="color: #63BFBF; text-decoration: none;">trvel.co</a>
      </p>
    </div>
  </div>
</body>
</html>"""

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"{self.from_name} <{self.from_email}>",
                    "to": [email],
                    "subject": f"Refund Processed - {destination} eSIM",
                    "html": html_content,
                },
            )
            response.raise_for_status()
            data = response.json()

        logger.info(
            "refund_email_sent",
            email=email,
            order_number=order_number,
            amount=amount,
            message_id=data.get("id"),
        )

        return {
            "success": True,
            "message_id": data.get("id"),
        }
