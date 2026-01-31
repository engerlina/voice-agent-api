"""Webhook endpoints for external service integrations."""

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.webhook import DeliveryStatusWebhook, WebhookResponse
from app.services.background_tasks import schedule_connection_guarantee_check
from app.services.order_service import OrderService
from app.services.stripe_service import StripeService

logger = get_logger(__name__)

router = APIRouter()


def get_order_service() -> OrderService:
    """Dependency for order service."""
    return OrderService()


def get_stripe_service() -> StripeService:
    """Dependency for Stripe service."""
    return StripeService()


@router.post("/stripe", response_model=WebhookResponse)
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    order_service: OrderService = Depends(get_order_service),
    stripe_service: StripeService = Depends(get_stripe_service),
    stripe_signature: str = Header(None, alias="stripe-signature"),
) -> WebhookResponse:
    """Handle Stripe webhooks.

    Critical path for order processing:
    - payment_intent.succeeded: Triggers eSIM provisioning and QR delivery
    - charge.refunded: Updates order status

    IMPORTANT: Must acknowledge within 200ms, then process async.
    """
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header",
        )

    # Get raw body for signature verification
    body = await request.body()

    try:
        event = stripe_service.verify_webhook_signature(body, stripe_signature)
    except ValueError as e:
        logger.error("stripe_webhook_invalid_signature", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )

    event_type = event.get("type")
    event_data = event.get("data", {})

    logger.info("stripe_webhook_received", event_type=event_type, event_id=event.get("id"))

    # Handle different event types
    if event_type == "payment_intent.succeeded":
        # Critical path - process order
        result = await order_service.process_payment_webhook(db, event_data)

        # Schedule 10-minute guarantee check
        if result.qr_delivered:
            background_tasks.add_task(
                schedule_connection_guarantee_check,
                order_id=result.order_id,
                delay_minutes=settings.sla_connection_guarantee_minutes,
            )

        return WebhookResponse(
            received=True,
            message=f"Order processed: {result.status}",
            order_id=result.order_id,
        )

    elif event_type == "charge.refunded":
        # Refund processed externally (e.g., via Stripe dashboard)
        logger.info("stripe_refund_webhook", event_data=event_data)
        return WebhookResponse(received=True, message="Refund acknowledged")

    elif event_type == "payment_intent.payment_failed":
        logger.warning("stripe_payment_failed", event_data=event_data)
        return WebhookResponse(received=True, message="Payment failure acknowledged")

    else:
        # Acknowledge unknown events
        logger.debug("stripe_webhook_unhandled", event_type=event_type)
        return WebhookResponse(received=True, message=f"Event {event_type} acknowledged")


@router.post("/resend", response_model=WebhookResponse)
async def resend_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    """Handle Resend email delivery status webhooks.

    Tracks email delivery for QR codes.
    See: https://resend.com/docs/dashboard/webhooks/introduction
    """
    body = await request.json()

    event_type = body.get("type")
    data = body.get("data", {})

    logger.info(
        "resend_event",
        event_type=event_type,
        email_id=data.get("email_id"),
        to=data.get("to"),
    )

    # Handle delivery events
    if event_type == "email.delivered":
        # Email successfully delivered
        pass
    elif event_type == "email.bounced":
        # Email bounced - may need to alert or retry via SMS
        logger.warning("email_bounced", data=data)
    elif event_type == "email.complained":
        # Spam complaint
        logger.warning("email_spam_complaint", data=data)

    return WebhookResponse(received=True, message=f"Resend event {event_type} processed")


@router.post("/twilio", response_model=WebhookResponse)
async def twilio_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    """Handle Twilio SMS/WhatsApp delivery status webhooks."""
    form_data = await request.form()

    message_sid = form_data.get("MessageSid")
    message_status = form_data.get("MessageStatus")
    to = form_data.get("To")

    logger.info(
        "twilio_event",
        message_sid=message_sid,
        status=message_status,
        to=to,
    )

    return WebhookResponse(received=True, message="Twilio event processed")


@router.post("/esim-provider", response_model=WebhookResponse)
async def esim_provider_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    """Handle eSIM provider webhooks (activation status, etc.)."""
    body = await request.json()

    event_type = body.get("event_type")
    esim_id = body.get("esim_id") or body.get("iccid")

    logger.info(
        "esim_provider_event",
        event_type=event_type,
        esim_id=esim_id,
    )

    # Handle activation notifications
    if event_type in ["activated", "first_use", "connected"]:
        # Update order/eSIM status
        # This could trigger clearing of guarantee check
        pass

    return WebhookResponse(received=True, message=f"eSIM event {event_type} processed")
