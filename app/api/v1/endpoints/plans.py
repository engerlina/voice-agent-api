"""Plan lookup endpoints - queries from database."""

from datetime import datetime, timezone
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_api_key
from app.models.plan import Plan
from app.schemas.plan import (
    DurationPlan,
    PlanLookupRequest,
    PlanLookupResponse,
    PlanNotFoundResponse,
    DestinationListResponse,
)

router = APIRouter()


@router.post(
    "/lookup",
    response_model=Union[PlanLookupResponse, PlanNotFoundResponse],
    responses={
        200: {
            "description": "Plan lookup result",
            "content": {
                "application/json": {
                    "examples": {
                        "found": {
                            "summary": "Plans found",
                            "value": {
                                "success": True,
                                "destination_slug": "japan",
                                "currency": "AUD",
                                "locale": "en-au",
                                "best_daily_rate": 4.87,
                                "default_durations": [5, 7, 15],
                                "plans": [
                                    {
                                        "duration": 5,
                                        "daily_rate": 5.10,
                                        "bundle_name": "esim_ULE_5D_JP_V2",
                                        "retail_price": 25.49,
                                        "wholesale_cents": 1038,
                                    },
                                    {
                                        "duration": 7,
                                        "daily_rate": 5.00,
                                        "bundle_name": "esim_ULE_7D_JP_V2",
                                        "retail_price": 34.99,
                                        "wholesale_cents": 1423,
                                    },
                                ],
                                "total_plans": 2,
                                "timestamp": "2024-01-20T15:00:00Z",
                            },
                        },
                        "not_found": {
                            "summary": "No plans found",
                            "value": {
                                "success": False,
                                "error": "Plan not found",
                                "destination_slug": "unknown",
                                "currency": "AUD",
                                "timestamp": "2024-01-20T15:00:00Z",
                            },
                        },
                    }
                }
            },
        },
    },
)
async def lookup_plans(
    request: PlanLookupRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> Union[PlanLookupResponse, PlanNotFoundResponse]:
    """Look up available plans by destination and currency.

    This endpoint is used by Aria (AI support agent) and internal tools.
    Returns matching plans with pricing from the database.

    Can filter by:
    - destination: Destination slug (e.g., 'japan')
    - currency: Currency code (e.g., 'AUD', 'USD')
    - locale: Locale code (e.g., 'en-au', 'en-us')
    - duration: Specific duration in days
    """
    now = datetime.now(timezone.utc)

    if not request.destination:
        return PlanNotFoundResponse(
            success=False,
            error="Destination is required",
            destination_slug=None,
            currency=request.currency,
            timestamp=now,
        )

    # Query for plan by destination, currency, and locale
    result = await db.execute(
        select(Plan).where(
            Plan.destination_slug == request.destination.lower(),
            Plan.currency == request.currency.upper(),
            Plan.locale == request.locale.lower(),
        )
    )
    plan = result.scalar_one_or_none()

    if not plan:
        # Try without locale filter (fallback)
        result = await db.execute(
            select(Plan).where(
                Plan.destination_slug == request.destination.lower(),
                Plan.currency == request.currency.upper(),
            )
        )
        plan = result.scalar_one_or_none()

    if not plan:
        return PlanNotFoundResponse(
            success=False,
            error="Plan not found",
            destination_slug=request.destination,
            currency=request.currency,
            timestamp=now,
        )

    # Parse durations from JSON field
    durations = plan.durations if plan.durations else []

    # Filter by specific duration if requested
    if request.duration:
        durations = [d for d in durations if d.get("duration") == request.duration]

    # Convert to DurationPlan objects
    plan_list = [
        DurationPlan(
            duration=d.get("duration"),
            daily_rate=d.get("daily_rate"),
            bundle_name=d.get("bundle_name"),
            retail_price=d.get("retail_price"),
            wholesale_cents=d.get("wholesale_cents"),
        )
        for d in durations
    ]

    return PlanLookupResponse(
        success=True,
        destination_slug=plan.destination_slug,
        currency=plan.currency,
        locale=plan.locale,
        best_daily_rate=plan.best_daily_rate,
        default_durations=plan.default_durations,
        plans=plan_list,
        total_plans=len(plan_list),
        timestamp=now,
    )


@router.get("/destinations", response_model=DestinationListResponse)
async def list_destinations(
    currency: str = Query("AUD", description="Currency to filter by"),
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> DestinationListResponse:
    """List all available destinations.

    Returns unique destination slugs that have plans in the specified currency.
    """
    result = await db.execute(
        select(Plan.destination_slug)
        .where(Plan.currency == currency.upper())
        .distinct()
        .order_by(Plan.destination_slug)
    )
    destinations = [row[0] for row in result.fetchall()]

    return DestinationListResponse(
        total=len(destinations),
        destinations=destinations,
    )


@router.get("/{destination_slug}")
async def get_destination_plans(
    destination_slug: str,
    currency: str = Query("AUD", description="Currency for pricing"),
    locale: str = Query("en-au", description="Locale"),
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> PlanLookupResponse:
    """Get all plans for a specific destination."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Plan).where(
            Plan.destination_slug == destination_slug.lower(),
            Plan.currency == currency.upper(),
            Plan.locale == locale.lower(),
        )
    )
    plan = result.scalar_one_or_none()

    if not plan:
        # Try without locale filter
        result = await db.execute(
            select(Plan).where(
                Plan.destination_slug == destination_slug.lower(),
                Plan.currency == currency.upper(),
            )
        )
        plan = result.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No plans found for destination: {destination_slug}",
        )

    durations = plan.durations if plan.durations else []
    plan_list = [
        DurationPlan(
            duration=d.get("duration"),
            daily_rate=d.get("daily_rate"),
            bundle_name=d.get("bundle_name"),
            retail_price=d.get("retail_price"),
            wholesale_cents=d.get("wholesale_cents"),
        )
        for d in durations
    ]

    return PlanLookupResponse(
        success=True,
        destination_slug=plan.destination_slug,
        currency=plan.currency,
        locale=plan.locale,
        best_daily_rate=plan.best_daily_rate,
        default_durations=plan.default_durations,
        plans=plan_list,
        total_plans=len(plan_list),
        timestamp=now,
    )
