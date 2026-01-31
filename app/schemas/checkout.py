"""Checkout schemas for Stripe payment links."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class CheckoutRequest(BaseModel):
    """Request to create a Stripe checkout session.

    Used by Aria (chat) and phone support to generate payment links.
    """

    destination: str = Field(..., description="Destination slug (e.g., 'japan')")
    duration: int = Field(..., description="Duration in days (e.g., 7)")
    currency: str = Field("AUD", description="Currency code (AUD, USD, SGD, etc.)")
    locale: str = Field("en-au", description="Locale for checkout page")
    promo_code: Optional[str] = Field(None, description="Promo code to apply")
    customer_email: Optional[EmailStr] = Field(None, description="Customer email to prefill")
    customer_phone: Optional[str] = Field(None, description="Customer phone for SMS delivery")


class CheckoutResponse(BaseModel):
    """Response with Stripe checkout URL.

    The URL can be sent to customers via chat or SMS.
    """

    success: bool
    checkout_url: str = Field(..., description="Stripe checkout page URL")
    session_id: str = Field(..., description="Stripe session ID for tracking")
    destination: str
    destination_name: str
    duration: int
    plan_name: str
    price: float
    currency: str
    message: str = Field(..., description="Friendly message to send to customer")
    timestamp: datetime


class CheckoutErrorResponse(BaseModel):
    """Response when checkout creation fails."""

    success: bool = False
    error: str
    destination: Optional[str] = None
    timestamp: datetime
