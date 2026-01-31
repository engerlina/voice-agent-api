"""Internal notification service (Telegram alerts)."""

from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class NotificationService:
    """Service for internal team notifications (Telegram)."""

    def __init__(self):
        self.bot_token = settings.telegram_bot_token
        self.alerts_chat_id = settings.telegram_alerts_chat_id
        self.support_chat_id = settings.telegram_support_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    async def _send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
    ) -> bool:
        """Send a message to a Telegram chat."""
        if not self.bot_token or not chat_id:
            logger.warning("telegram_not_configured")
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                    },
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error("telegram_send_failed", error=str(e))
            return False

    async def alert_critical(
        self,
        title: str,
        message: str,
        order_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Send critical alert to ops team.

        Used for: QR delivery failures, provisioning failures, SLA breaches.
        """
        text = f"<b>🚨 {title}</b>\n\n{message}"

        if order_id:
            text += f"\n\n<b>Order ID:</b> <code>{order_id}</code>"

        if error:
            text += f"\n\n<b>Error:</b>\n<pre>{error[:500]}</pre>"

        success = await self._send_message(self.alerts_chat_id, text)
        if success:
            logger.info("critical_alert_sent", title=title)
        return success

    async def alert_sla_breach(
        self,
        sla_type: str,
        order_id: Optional[str] = None,
        ticket_id: Optional[str] = None,
        elapsed_seconds: float = 0,
        threshold_seconds: float = 0,
    ) -> bool:
        """Alert when an SLA is breached.

        SLA types:
        - qr_delivery: QR code not delivered within 30 seconds
        - support_response: First response not sent within 3 minutes
        - connection_guarantee: Customer not connected within 10 minutes
        """
        sla_names = {
            "qr_delivery": "QR Code Delivery",
            "support_response": "Support First Response",
            "connection_guarantee": "10-Minute Connection Guarantee",
        }

        title = f"SLA Breach: {sla_names.get(sla_type, sla_type)}"
        message = (
            f"<b>Threshold:</b> {threshold_seconds}s\n"
            f"<b>Elapsed:</b> {elapsed_seconds:.1f}s\n"
            f"<b>Overage:</b> {elapsed_seconds - threshold_seconds:.1f}s"
        )

        if order_id:
            message += f"\n<b>Order:</b> <code>{order_id}</code>"
        if ticket_id:
            message += f"\n<b>Ticket:</b> <code>{ticket_id}</code>"

        return await self.alert_critical(title, message)

    async def alert_delivery_failure(
        self,
        order_id: str,
        order_number: str,
        customer_email: str,
        attempts: list,
    ) -> bool:
        """Alert when all QR delivery channels fail."""
        channels_tried = ", ".join([a["channel"] for a in attempts])
        errors = "\n".join([f"• {a['channel']}: {a.get('error', 'Unknown')}" for a in attempts])

        message = (
            f"<b>Order:</b> <code>{order_number}</code>\n"
            f"<b>Customer:</b> {customer_email}\n"
            f"<b>Channels Tried:</b> {channels_tried}\n\n"
            f"<b>Errors:</b>\n{errors}\n\n"
            f"⚠️ <b>Manual intervention required</b>"
        )

        return await self.alert_critical(
            title="QR Delivery Failed - All Channels",
            message=message,
            order_id=order_id,
        )

    async def alert_provisioning_failure(
        self,
        order_id: str,
        order_number: str,
        destination: str,
        provider: str,
        error: str,
    ) -> bool:
        """Alert when eSIM provisioning fails."""
        message = (
            f"<b>Order:</b> <code>{order_number}</code>\n"
            f"<b>Destination:</b> {destination}\n"
            f"<b>Provider:</b> {provider}"
        )

        return await self.alert_critical(
            title="eSIM Provisioning Failed",
            message=message,
            order_id=order_id,
            error=error,
        )

    async def notify_support_escalation(
        self,
        ticket_number: str,
        category: str,
        subject: str,
        customer_email: str,
        ai_summary: Optional[str] = None,
    ) -> bool:
        """Notify support channel of escalated ticket."""
        text = (
            f"<b>📬 New Escalation: {ticket_number}</b>\n\n"
            f"<b>Category:</b> {category}\n"
            f"<b>Customer:</b> {customer_email}\n"
            f"<b>Subject:</b> {subject}"
        )

        if ai_summary:
            text += f"\n\n<b>AI Summary:</b>\n{ai_summary}"

        success = await self._send_message(self.support_chat_id, text)
        if not success:
            logger.error("telegram_support_notification_failed")
        return success

    async def notify_guarantee_refund(
        self,
        order_number: str,
        customer_email: str,
        destination: str,
        amount: float,
        currency: str,
    ) -> bool:
        """Notify when a 10-minute guarantee refund is issued."""
        text = (
            f"<b>🔄 10-Minute Guarantee Refund</b>\n\n"
            f"<b>Order:</b> <code>{order_number}</code>\n"
            f"<b>Customer:</b> {customer_email}\n"
            f"<b>Destination:</b> {destination}\n"
            f"<b>Amount:</b> {currency} ${amount:.2f}\n\n"
            f"<i>Customer did not activate within 10 minutes. Auto-refund issued.</i>"
        )

        return await self._send_message(self.alerts_chat_id, text)
