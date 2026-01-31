"""Support triage schemas - AI-powered support without database persistence."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class SupportTriageRequest(BaseModel):
    """Request for AI support triage."""

    subject: str
    message: str
    customer_email: Optional[EmailStr] = None
    order_id: Optional[int] = None  # Prisma uses Int for order id
    channel: str = "email"


class SupportTriageResponse(BaseModel):
    """Response from AI support triage.

    This is a stateless response - no ticket is persisted to database.
    The triage result should be forwarded to external ticketing system if needed.
    """

    category: str
    priority: str
    confidence: float
    suggested_response: str
    requires_human: bool
    related_order: Optional[dict] = None
    customer_found: bool = False
    processing_time_ms: int
    timestamp: datetime
