"""Support endpoints - AI triage only, no ticket persistence."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_api_key
from app.schemas.support import SupportTriageRequest, SupportTriageResponse
from app.services.support_service import SupportService

router = APIRouter()


def get_support_service() -> SupportService:
    """Dependency for support service."""
    return SupportService()


@router.post("/triage", response_model=SupportTriageResponse)
async def triage_support_request(
    request: SupportTriageRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
    support_service: SupportService = Depends(get_support_service),
) -> SupportTriageResponse:
    """AI-powered support request triage.

    This endpoint:
    1. Classifies the issue category and priority
    2. Looks up related customer/order data for context
    3. Generates a suggested response
    4. Returns classification and response (no persistence)

    The result can be forwarded to an external ticketing system if needed.
    """
    return await support_service.triage_support_request(db, request)
