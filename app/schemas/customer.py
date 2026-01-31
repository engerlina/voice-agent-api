"""Customer schemas - matches Prisma schema."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class CustomerBase(BaseModel):
    """Base customer schema - matches Prisma Customer model."""

    email: EmailStr
    name: Optional[str] = None
    phone: Optional[str] = None


class CustomerCreate(CustomerBase):
    """Schema for creating a customer."""

    pass


class CustomerResponse(CustomerBase):
    """Customer response schema - matches Prisma Customer model."""

    id: int  # Prisma uses Int for id
    stripe_customer_id: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Customer Lookup Schemas (for Aria/ElevenLabs integration)
# ============================================================================


class CustomerLookupRequest(BaseModel):
    """Request schema for customer lookup."""

    email: EmailStr = Field(..., description="Customer email address")


class CustomerInLookup(BaseModel):
    """Customer info in lookup response."""

    id: int  # Prisma uses Int for id
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    created_at: datetime


class DestinationInOrder(BaseModel):
    """Destination details in order."""

    slug: str
    name: str


class PlanInOrder(BaseModel):
    """Plan details in order."""

    name: str
    duration_days: int


class PaymentInOrder(BaseModel):
    """Payment details in order."""

    cents: int
    amount: float
    formatted: str


class ESimInOrder(BaseModel):
    """eSIM details in order."""

    status: Optional[str] = None
    iccid: Optional[str] = None
    email_sent: bool = False


class OrderInLookup(BaseModel):
    """Order details in lookup response."""

    id: int  # Prisma uses Int for id
    order_number: str
    destination: DestinationInOrder
    plan: PlanInOrder
    payment: PaymentInOrder
    status: str
    esim: ESimInOrder
    created_at: datetime
    paid_at: Optional[datetime] = None


class LookupSummary(BaseModel):
    """Summary stats in lookup response."""

    total_orders: int
    completed_orders: int
    total_spent: str


class CustomerLookupResponse(BaseModel):
    """Response schema for customer lookup - matches n8n workflow format."""

    success: bool
    customer: Optional[CustomerInLookup] = None
    orders: List[OrderInLookup] = []
    summary: LookupSummary
    timestamp: datetime


class CustomerNotFoundResponse(BaseModel):
    """Response when customer is not found."""

    success: bool = False
    error: str = "Customer not found"
    email: str
    timestamp: datetime


# ============================================================================
# Legacy schemas (for backwards compatibility)
# ============================================================================


class OrderSummaryInLookup(BaseModel):
    """Abbreviated order info for customer lookup."""

    id: int  # Prisma uses Int for id
    order_number: str
    status: str
    destination_name: str
    plan_name: str
    duration_days: int
    amount: float
    currency: str
    created_at: datetime

    class Config:
        from_attributes = True
