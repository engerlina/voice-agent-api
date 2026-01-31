"""Phone number management endpoints."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import logger
from app.models.phone_number import PhoneNumber
from app.models.user import User

router = APIRouter()


class PhoneNumberResponse(BaseModel):
    """Phone number response."""
    id: str
    number: str
    friendly_name: Optional[str]
    country: str
    voice_enabled: bool
    sms_enabled: bool
    is_available: bool
    is_mine: bool

    class Config:
        from_attributes = True


class MyPhoneNumberResponse(BaseModel):
    """Current user's phone number."""
    id: str
    number: str
    friendly_name: Optional[str]
    country: str
    assigned_at: datetime
    webhook_configured: bool


class ClaimNumberRequest(BaseModel):
    """Request to claim a phone number."""
    phone_number_id: str


@router.get("/available", response_model=list[PhoneNumberResponse])
async def list_available_numbers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all available phone numbers that can be claimed."""
    result = await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.is_active == True,
            PhoneNumber.user_id == None,
        ).order_by(PhoneNumber.number)
    )
    numbers = result.scalars().all()

    return [
        PhoneNumberResponse(
            id=n.id,
            number=n.number,
            friendly_name=n.friendly_name,
            country=n.country,
            voice_enabled=n.voice_enabled,
            sms_enabled=n.sms_enabled,
            is_available=True,
            is_mine=False,
        )
        for n in numbers
    ]


@router.get("/mine", response_model=Optional[MyPhoneNumberResponse])
async def get_my_number(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's assigned phone number."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.user_id == current_user.id)
    )
    number = result.scalar_one_or_none()

    if not number:
        return None

    return MyPhoneNumberResponse(
        id=number.id,
        number=number.number,
        friendly_name=number.friendly_name,
        country=number.country,
        assigned_at=number.assigned_at,
        webhook_configured=number.webhook_configured,
    )


@router.post("/claim", response_model=MyPhoneNumberResponse)
async def claim_number(
    request: ClaimNumberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Claim an available phone number for your account."""
    # Check if user already has a number
    existing = await db.execute(
        select(PhoneNumber).where(PhoneNumber.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have a phone number assigned. Release it first to claim a new one.",
        )

    # Get the requested number
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == request.phone_number_id)
    )
    number = result.scalar_one_or_none()

    if not number:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phone number not found",
        )

    if not number.is_available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This phone number is not available",
        )

    # Assign the number
    number.user_id = current_user.id
    number.assigned_at = datetime.now(timezone.utc)

    # Configure Twilio webhook for this number
    webhook_success = await configure_twilio_webhook(number, current_user)
    number.webhook_configured = webhook_success

    await db.commit()
    await db.refresh(number)

    logger.info(
        "phone_number_claimed",
        user_id=current_user.id,
        phone_number=number.number,
        webhook_configured=webhook_success,
    )

    return MyPhoneNumberResponse(
        id=number.id,
        number=number.number,
        friendly_name=number.friendly_name,
        country=number.country,
        assigned_at=number.assigned_at,
        webhook_configured=number.webhook_configured,
    )


@router.post("/release")
async def release_number(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Release your current phone number back to the pool."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.user_id == current_user.id)
    )
    number = result.scalar_one_or_none()

    if not number:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You don't have a phone number assigned",
        )

    # Release the number
    number.user_id = None
    number.assigned_at = None
    number.webhook_configured = False

    await db.commit()

    logger.info(
        "phone_number_released",
        user_id=current_user.id,
        phone_number=number.number,
    )

    return {"message": "Phone number released successfully"}


async def configure_twilio_webhook(number: PhoneNumber, user: User) -> bool:
    """Configure Twilio webhook for the phone number.

    Sets up the voice URL to route calls to our API with the user's ID.
    """
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.warning("Twilio not configured, skipping webhook setup")
        return False

    if not number.twilio_sid:
        logger.warning("Phone number has no Twilio SID", number=number.number)
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

        # Build webhook URL with user ID for routing
        webhook_url = f"{settings.api_base_url}/api/v1/voice/webhooks/twilio/voice?user_id={user.id}"

        # Update the phone number's voice webhook
        client.incoming_phone_numbers(number.twilio_sid).update(
            voice_url=webhook_url,
            voice_method="POST",
        )

        logger.info(
            "twilio_webhook_configured",
            number=number.number,
            webhook_url=webhook_url,
        )
        return True

    except Exception as e:
        logger.error(
            "twilio_webhook_error",
            number=number.number,
            error=str(e),
        )
        return False
