"""Plan schemas - matches Prisma Plan table structure."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DurationPlan(BaseModel):
    """Single duration option within a plan."""

    duration: int = Field(..., description="Duration in days")
    daily_rate: float = Field(..., description="Price per day")
    bundle_name: str = Field(..., description="eSIM Go bundle identifier")
    retail_price: float = Field(..., description="Total retail price")
    wholesale_cents: Optional[int] = Field(None, description="Wholesale cost in cents")


class PlanResponse(BaseModel):
    """Plan response - represents all durations for a destination+currency."""

    id: int
    destination_slug: str
    locale: str
    currency: str
    best_daily_rate: Optional[float] = None
    default_durations: Optional[List[int]] = None
    durations: List[DurationPlan]

    class Config:
        from_attributes = True


class PlanLookupRequest(BaseModel):
    """Request schema for plan lookup."""

    destination: Optional[str] = Field(
        None,
        description="Destination slug (e.g., 'japan')",
    )
    currency: str = Field("AUD", description="Currency for pricing (AUD, USD, SGD, etc.)")
    locale: str = Field("en-au", description="Locale (e.g., 'en-au', 'en-us')")
    duration: Optional[int] = Field(None, description="Filter by specific duration in days")


class PlanLookupResponse(BaseModel):
    """Response schema for plan lookup - matches n8n workflow format."""

    success: bool
    destination_slug: Optional[str] = None
    currency: str
    locale: str
    best_daily_rate: Optional[float] = None
    default_durations: Optional[List[int]] = None
    plans: List[DurationPlan] = []
    total_plans: int
    timestamp: datetime


class PlanNotFoundResponse(BaseModel):
    """Response when plan is not found."""

    success: bool = False
    error: str = "Plan not found"
    destination_slug: Optional[str] = None
    currency: str
    timestamp: datetime


# Legacy schemas for backwards compatibility with destinations.json
class DestinationWithPlans(BaseModel):
    """Destination with its available plans (legacy format)."""

    destination_slug: str
    destination_name: str
    country_code: str
    region: str
    network_partner: Optional[str] = None
    plans: List[DurationPlan]


class DestinationListResponse(BaseModel):
    """Response for listing all destinations."""

    total: int
    destinations: List[str]  # List of destination slugs
