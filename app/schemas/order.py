"""Order schemas - matches Prisma schema."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OrderBase(BaseModel):
    """Base order schema."""

    destination_slug: str
    bundle_name: Optional[str] = None  # eSIM-Go bundle identifier
    customer_email: str


class OrderCreate(OrderBase):
    """Schema for creating an order."""

    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None


class ESimInfo(BaseModel):
    """eSIM information within an order (inline fields)."""

    status: str
    iccid: Optional[str] = None
    smdp_address: Optional[str] = None
    matching_id: Optional[str] = None
    qr_code: Optional[str] = None
    order_ref: Optional[str] = None
    provisioned_at: Optional[datetime] = None


class OrderResponse(BaseModel):
    """Order response schema - matches Prisma Order model."""

    id: int
    order_number: str
    customer_id: int
    status: str
    destination_slug: str
    destination_name: str
    plan_name: str
    bundle_name: Optional[str] = None
    duration: int  # Days
    amount_cents: int
    currency: str
    stripe_session_id: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None
    esim: ESimInfo
    locale: str
    createdAt: datetime
    updatedAt: datetime
    paidAt: Optional[datetime] = None

    class Config:
        from_attributes = True


class OrderSummary(BaseModel):
    """Abbreviated order summary."""

    id: int
    order_number: str
    status: str
    destination_name: str
    amount_cents: int
    currency: str
    createdAt: datetime

    class Config:
        from_attributes = True


class OrderProcessingResult(BaseModel):
    """Result of order processing pipeline."""

    order_id: int
    order_number: str
    status: str
    esim_provisioned: bool = False
    qr_delivered: bool = False
    delivery_channel: Optional[str] = None
    processing_time_ms: int = 0
    errors: list[str] = []


class RefundRequest(BaseModel):
    """Refund request schema."""

    order_id: int = Field(..., description="Order ID to refund")
    reason: Optional[str] = Field(None, description="Reason for refund")


class RefundResponse(BaseModel):
    """Refund response schema."""

    order_id: int
    order_number: str
    refund_id: str
    amount_cents: int
    currency: str
    status: str
    reason: Optional[str] = None


class ResendQRRequest(BaseModel):
    """Request to resend QR code.

    Used by Aria (chat) and phone support to resend QR codes
    through specific channels.
    """

    order_id: Optional[int] = Field(None, description="Order ID (if known)")
    order_number: Optional[str] = Field(None, description="Order number (e.g., TRV-20240115-001)")
    customer_email: Optional[str] = Field(None, description="Customer email for verification")
    channel: str = Field(
        "email",
        description="Delivery channel: 'email', 'sms', or 'auto' (email first, then SMS fallback)"
    )
    phone_override: Optional[str] = Field(
        None,
        description="Override phone number for SMS delivery (use for voice calls)"
    )


class ResendQRResponse(BaseModel):
    """Response after QR code resend attempt."""

    success: bool
    order_id: int
    order_number: str
    customer_email: str
    destination_name: str
    plan_name: str
    channel_used: Optional[str] = Field(None, description="Channel that succeeded: email, sms")
    message_id: Optional[str] = Field(None, description="Delivery provider message ID")
    message: str = Field(..., description="Human-friendly status message")
    timestamp: datetime


class ResendQRErrorResponse(BaseModel):
    """Error response when resend fails."""

    success: bool = False
    error: str
    order_id: Optional[int] = None
    order_number: Optional[str] = None
    timestamp: datetime


# =============================================================================
# Full Refund Processing (with eSIM Go bundle recovery)
# =============================================================================


class ProcessRefundRequest(BaseModel):
    """Request to process a full refund with eSIM bundle recovery.

    Used by Aria (AI support) and phone support to process refunds.
    Includes eSIM Go bundle revocation and inventory refund.

    Refund is only allowed if:
    - eSIM has NOT been activated (no data used)
    - Order status is 'paid' (not already refunded)
    """

    order_id: Optional[int] = Field(None, description="Order ID (if known)")
    order_number: Optional[str] = Field(
        None, description="Order number (e.g., TRV-20240115-001)"
    )
    customer_email: Optional[str] = Field(
        None, description="Customer email to find their most recent order"
    )
    reason: Optional[str] = Field(
        "customer_request",
        description="Reason for refund: customer_request, guarantee_not_met, technical_issue",
    )
    force: bool = Field(
        False,
        description="Force refund even if eSIM was activated (use with caution, for guarantee cases)",
    )


class RefundStepResult(BaseModel):
    """Result of a single refund step."""

    step: str = Field(..., description="Step name: eligibility_check, bundle_revoke, bundle_refund, stripe_refund, email_notification")
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    details: Optional[dict] = None


class ProcessRefundResponse(BaseModel):
    """Response after full refund processing."""

    success: bool
    order_id: int
    order_number: str
    customer_email: str
    destination_name: str
    plan_name: str
    amount_refunded: float = Field(..., description="Amount refunded in dollars")
    currency: str
    stripe_refund_id: Optional[str] = None
    esim_bundle_revoked: bool = False
    esim_bundle_refunded: bool = False
    steps: list[RefundStepResult] = Field(
        default_factory=list, description="Details of each refund step"
    )
    message: str = Field(..., description="Human-friendly summary")
    timestamp: datetime


class ProcessRefundErrorResponse(BaseModel):
    """Error response when refund cannot be processed."""

    success: bool = False
    error: str = Field(..., description="Error message explaining why refund failed")
    error_code: str = Field(
        ...,
        description="Error code: order_not_found, already_refunded, esim_activated, no_payment_intent, refund_failed",
    )
    order_id: Optional[int] = None
    order_number: Optional[str] = None
    customer_email: Optional[str] = None
    destination_name: Optional[str] = None
    data_used_mb: Optional[float] = Field(
        None, description="Data used if eSIM was activated (reason for denial)"
    )
    timestamp: datetime
