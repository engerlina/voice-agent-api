"""Checkout endpoint - generates Stripe payment links for chat/SMS."""

from datetime import datetime, timezone
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_api_key
from app.models.plan import Plan
from app.schemas.checkout import (
    CheckoutRequest,
    CheckoutResponse,
    CheckoutErrorResponse,
)
from app.services.stripe_service import StripeService, get_plan_name

router = APIRouter()


# Destination name mapping (for display)
DESTINATION_NAMES = {
    "japan": "Japan",
    "thailand": "Thailand",
    "south-korea": "South Korea",
    "singapore": "Singapore",
    "indonesia": "Indonesia",
    "malaysia": "Malaysia",
    "vietnam": "Vietnam",
    "philippines": "Philippines",
    "taiwan": "Taiwan",
    "hong-kong": "Hong Kong",
    "china": "China",
    "india": "India",
    "australia": "Australia",
    "new-zealand": "New Zealand",
    "usa": "United States",
    "uk": "United Kingdom",
    "france": "France",
    "germany": "Germany",
    "italy": "Italy",
    "spain": "Spain",
    "europe": "Europe (Multi-Country)",
}


def get_destination_name(slug: str) -> str:
    """Get display name for destination slug."""
    return DESTINATION_NAMES.get(slug.lower(), slug.replace("-", " ").title())


def get_stripe_service() -> StripeService:
    """Dependency for Stripe service."""
    return StripeService()


@router.post(
    "/create",
    response_model=Union[CheckoutResponse, CheckoutErrorResponse],
    responses={
        200: {
            "description": "Checkout session created",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "Checkout created",
                            "value": {
                                "success": True,
                                "checkout_url": "https://checkout.stripe.com/c/pay/cs_xxx",
                                "session_id": "cs_xxx",
                                "destination": "japan",
                                "destination_name": "Japan",
                                "duration": 7,
                                "plan_name": "Week Explorer",
                                "price": 34.99,
                                "currency": "AUD",
                                "message": "Here's your payment link for Japan eSIM (7 days) - $34.99 AUD: https://checkout.stripe.com/...",
                                "timestamp": "2024-01-20T15:00:00Z",
                            },
                        },
                        "error": {
                            "summary": "Plan not found",
                            "value": {
                                "success": False,
                                "error": "No plan found for destination: xyz",
                                "destination": "xyz",
                                "timestamp": "2024-01-20T15:00:00Z",
                            },
                        },
                    }
                }
            },
        },
    },
)
async def create_checkout(
    request: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
    stripe_service: StripeService = Depends(get_stripe_service),
) -> Union[CheckoutResponse, CheckoutErrorResponse]:
    """Create a Stripe checkout session and return the payment link.

    This endpoint is used by:
    - Aria (AI chat support) to send payment links in chat
    - Phone support to send payment links via SMS

    The response includes a pre-formatted message that can be sent directly to customers.
    """
    now = datetime.now(timezone.utc)

    # Look up the plan from database
    result = await db.execute(
        select(Plan).where(
            Plan.destination_slug == request.destination.lower(),
            Plan.currency == request.currency.upper(),
        )
    )
    plan = result.scalar_one_or_none()

    if not plan:
        return CheckoutErrorResponse(
            success=False,
            error=f"No plan found for destination: {request.destination} in {request.currency}",
            destination=request.destination,
            timestamp=now,
        )

    # Find the specific duration in the plan
    durations = plan.durations if plan.durations else []
    selected_duration = None
    for d in durations:
        if d.get("duration") == request.duration:
            selected_duration = d
            break

    if not selected_duration:
        available = [d.get("duration") for d in durations]
        return CheckoutErrorResponse(
            success=False,
            error=f"Duration {request.duration} days not available. Available: {available}",
            destination=request.destination,
            timestamp=now,
        )

    # Get pricing and bundle info
    price = selected_duration.get("retail_price")
    bundle_name = selected_duration.get("bundle_name")
    destination_name = get_destination_name(request.destination)
    plan_name = get_plan_name(request.duration)

    # Create Stripe checkout session
    try:
        checkout_result = await stripe_service.create_checkout_session(
            destination_slug=request.destination.lower(),
            destination_name=destination_name,
            duration=request.duration,
            price=price,
            currency=request.currency.upper(),
            bundle_name=bundle_name,
            locale=request.locale,
            promo_code=request.promo_code,
            customer_email=request.customer_email,
            customer_phone=request.customer_phone,
        )
    except Exception as e:
        return CheckoutErrorResponse(
            success=False,
            error=f"Failed to create checkout: {str(e)}",
            destination=request.destination,
            timestamp=now,
        )

    # Build friendly message for chat/SMS
    message = (
        f"Here's your payment link for {destination_name} eSIM "
        f"({request.duration} days) - ${price:.2f} {request.currency}: "
        f"{checkout_result['url']}"
    )

    return CheckoutResponse(
        success=True,
        checkout_url=checkout_result["url"],
        session_id=checkout_result["session_id"],
        destination=request.destination,
        destination_name=destination_name,
        duration=request.duration,
        plan_name=plan_name,
        price=price,
        currency=request.currency.upper(),
        message=message,
        timestamp=now,
    )
