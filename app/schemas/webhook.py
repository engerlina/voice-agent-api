"""Webhook schemas."""

from typing import Any, Optional

from pydantic import BaseModel


class StripeWebhookEvent(BaseModel):
    """Stripe webhook event schema."""

    id: str
    type: str
    data: dict[str, Any]
    created: int
    livemode: bool


class StripePaymentIntent(BaseModel):
    """Stripe PaymentIntent from webhook."""

    id: str
    amount: int
    currency: str
    status: str
    customer: Optional[str] = None
    metadata: dict[str, str] = {}


class StripeCharge(BaseModel):
    """Stripe Charge from webhook."""

    id: str
    amount: int
    currency: str
    status: str
    payment_intent: Optional[str] = None
    receipt_email: Optional[str] = None


class WebhookResponse(BaseModel):
    """Standard webhook response."""

    received: bool = True
    message: str = "Webhook processed"
    order_id: Optional[str] = None


class ESIMProviderWebhook(BaseModel):
    """Generic eSIM provider webhook."""

    event_type: str
    esim_id: Optional[str] = None
    iccid: Optional[str] = None
    status: Optional[str] = None
    data: dict[str, Any] = {}


class DeliveryStatusWebhook(BaseModel):
    """Email/SMS delivery status webhook."""

    provider: str  # resend, twilio
    message_id: str
    status: str  # delivered, bounced, failed
    recipient: str
    timestamp: int
    error: Optional[str] = None
