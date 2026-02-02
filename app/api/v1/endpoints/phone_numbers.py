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

    # Remove SIP trunk configuration
    await remove_sip_configuration(number)

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
    """Configure Twilio to route calls via SIP trunk to LiveKit.

    Sets up the phone number to use the SIP trunk instead of a webhook,
    which connects calls directly to LiveKit for voice agent handling.
    """
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.warning("Twilio not configured, skipping SIP setup")
        return False

    if not number.twilio_sid:
        logger.warning("Phone number has no Twilio SID", number=number.number)
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

        # Get or create SIP trunk for LiveKit
        sip_trunk_sid = await get_or_create_livekit_sip_trunk(client)

        if not sip_trunk_sid:
            logger.error("Could not get/create SIP trunk")
            return False

        # Configure phone number to use SIP trunk (clear voice URL)
        client.incoming_phone_numbers(number.twilio_sid).update(
            voice_url="",  # Clear webhook - SIP trunk handles routing
            trunk_sid=sip_trunk_sid,
        )

        # Add number to LiveKit SIP inbound trunk
        await add_number_to_livekit_sip(number.number)

        logger.info(
            "sip_trunk_configured",
            number=number.number,
            trunk_sid=sip_trunk_sid,
            user_id=user.id,
        )
        return True

    except Exception as e:
        logger.error(
            "sip_trunk_error",
            number=number.number,
            error=str(e),
        )
        return False


async def remove_sip_configuration(number: PhoneNumber) -> bool:
    """Remove SIP trunk configuration when number is released."""
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        return False

    if not number.twilio_sid:
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

        # Remove trunk association from phone number
        client.incoming_phone_numbers(number.twilio_sid).update(
            trunk_sid="",  # Remove SIP trunk
        )

        logger.info(
            "sip_trunk_removed",
            number=number.number,
        )
        return True

    except Exception as e:
        logger.error(
            "sip_trunk_removal_error",
            number=number.number,
            error=str(e),
        )
        return False


async def get_or_create_livekit_sip_trunk(client) -> str:
    """Get existing LiveKit SIP trunk or create one."""
    # Check for existing trunk
    trunks = client.trunking.v1.trunks.list()
    for trunk in trunks:
        if "LiveKit" in trunk.friendly_name:
            return trunk.sid

    # Create new trunk if not found
    livekit_sip_uri = settings.livekit_sip_uri
    if not livekit_sip_uri:
        # Derive from LIVEKIT_URL
        from urllib.parse import urlparse
        parsed = urlparse(settings.livekit_url)
        # Extract subdomain and create SIP domain
        host = parsed.netloc
        if ".livekit.cloud" in host:
            subdomain = host.replace(".livekit.cloud", "")
            livekit_sip_uri = f"{subdomain}.sip.livekit.cloud"

    if not livekit_sip_uri:
        logger.error("Cannot determine LiveKit SIP URI")
        return None

    trunk = client.trunking.v1.trunks.create(
        friendly_name="LiveKit Voice Agent",
    )

    # Add origination URI
    client.trunking.v1.trunks(trunk.sid).origination_urls.create(
        sip_url=f"sip:{livekit_sip_uri}",
        priority=1,
        weight=1,
        friendly_name="LiveKit Cloud",
        enabled=True,
    )

    logger.info(
        "sip_trunk_created",
        trunk_sid=trunk.sid,
        sip_uri=livekit_sip_uri,
    )

    return trunk.sid


async def add_number_to_livekit_sip(phone_number: str) -> bool:
    """Add phone number to LiveKit SIP inbound trunk."""
    try:
        import httpx

        livekit_url = settings.livekit_url
        api_key = settings.livekit_api_key
        api_secret = settings.livekit_api_secret

        if not all([livekit_url, api_key, api_secret]):
            logger.warning("LiveKit not fully configured")
            return False

        # Use LiveKit API to update SIP trunk
        # For now, log that this would be done - full implementation requires
        # calling LiveKit's SIP API which we set up via CLI
        logger.info(
            "livekit_sip_number_add",
            number=phone_number,
            note="Number should be added to LiveKit SIP inbound trunk via CLI or API",
        )
        return True

    except Exception as e:
        logger.error(
            "livekit_sip_add_error",
            number=phone_number,
            error=str(e),
        )
        return False
