"""Admin endpoints for managing the voice agent platform."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

from app.api.v1.endpoints.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import logger
from app.models.phone_number import PhoneNumber
from app.models.settings import TenantSettings
from app.models.user import User


def get_twilio_client() -> TwilioClient:
    """Get Twilio client instance."""
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise HTTPException(
            status_code=500,
            detail="Twilio credentials not configured"
        )
    return TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)

router = APIRouter()

# Admin email(s) - could also be stored in env
ADMIN_EMAILS = ["jonochan@gmail.com", "jonathan@aineversleeps.net"]


async def get_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency to ensure current user is an admin."""
    if current_user.email not in ADMIN_EMAILS and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# ============== Schemas ==============

class UserListResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str]
    tenant_name: Optional[str]
    is_active: bool
    is_admin: bool
    created_at: datetime
    phone_number: Optional[str] = None

    class Config:
        from_attributes = True


class PhoneNumberAdmin(BaseModel):
    id: str
    number: str
    twilio_sid: Optional[str]
    friendly_name: Optional[str]
    country: str
    voice_enabled: bool
    sms_enabled: bool
    is_active: bool
    user_id: Optional[str]
    user_email: Optional[str] = None
    assigned_at: Optional[datetime]
    webhook_configured: bool
    created_at: datetime


class AddPhoneNumberRequest(BaseModel):
    number: str
    twilio_sid: Optional[str] = None
    friendly_name: Optional[str] = None
    country: str = "US"
    voice_enabled: bool = True
    sms_enabled: bool = False


class UpdatePhoneNumberRequest(BaseModel):
    friendly_name: Optional[str] = None
    is_active: Optional[bool] = None


class StatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_phone_numbers: int
    assigned_phone_numbers: int
    available_phone_numbers: int


# ============== Endpoints ==============

@router.get("/stats", response_model=StatsResponse)
async def get_admin_stats(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get platform statistics."""
    # Count users
    total_users = await db.scalar(select(func.count(User.id)))
    active_users = await db.scalar(
        select(func.count(User.id)).where(User.is_active == True)
    )

    # Count phone numbers
    total_phones = await db.scalar(select(func.count(PhoneNumber.id)))
    assigned_phones = await db.scalar(
        select(func.count(PhoneNumber.id)).where(PhoneNumber.user_id != None)
    )

    return StatsResponse(
        total_users=total_users or 0,
        active_users=active_users or 0,
        total_phone_numbers=total_phones or 0,
        assigned_phone_numbers=assigned_phones or 0,
        available_phone_numbers=(total_phones or 0) - (assigned_phones or 0),
    )


@router.get("/users", response_model=list[UserListResponse])
async def list_users(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List all users with their assigned phone numbers."""
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    users = result.scalars().all()

    response = []
    for user in users:
        # Get user's phone number if any
        phone_result = await db.execute(
            select(PhoneNumber.number).where(PhoneNumber.user_id == user.id)
        )
        phone = phone_result.scalar_one_or_none()

        response.append(UserListResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            tenant_name=user.tenant_name,
            is_active=user.is_active,
            is_admin=user.is_admin,
            created_at=user.created_at,
            phone_number=phone,
        ))

    return response


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    is_active: Optional[bool] = None,
    is_admin: Optional[bool] = None,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user status."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if is_active is not None:
        user.is_active = is_active
    if is_admin is not None:
        user.is_admin = is_admin

    await db.commit()

    return {"message": "User updated"}


@router.get("/phone-numbers", response_model=list[PhoneNumberAdmin])
async def list_all_phone_numbers(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List all phone numbers with assignment info."""
    result = await db.execute(
        select(PhoneNumber).order_by(PhoneNumber.created_at.desc())
    )
    numbers = result.scalars().all()

    response = []
    for number in numbers:
        # Get assigned user's email if any
        user_email = None
        if number.user_id:
            user_result = await db.execute(
                select(User.email).where(User.id == number.user_id)
            )
            user_email = user_result.scalar_one_or_none()

        response.append(PhoneNumberAdmin(
            id=number.id,
            number=number.number,
            twilio_sid=number.twilio_sid,
            friendly_name=number.friendly_name,
            country=number.country,
            voice_enabled=number.voice_enabled,
            sms_enabled=number.sms_enabled,
            is_active=number.is_active,
            user_id=number.user_id,
            user_email=user_email,
            assigned_at=number.assigned_at,
            webhook_configured=number.webhook_configured,
            created_at=number.created_at,
        ))

    return response


@router.post("/phone-numbers", response_model=PhoneNumberAdmin)
async def add_phone_number(
    request: AddPhoneNumberRequest,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a new phone number to the pool."""
    # Check if number already exists
    existing = await db.execute(
        select(PhoneNumber).where(PhoneNumber.number == request.number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Phone number already exists",
        )

    number = PhoneNumber(
        number=request.number,
        twilio_sid=request.twilio_sid,
        friendly_name=request.friendly_name,
        country=request.country,
        voice_enabled=request.voice_enabled,
        sms_enabled=request.sms_enabled,
    )
    db.add(number)
    await db.commit()
    await db.refresh(number)

    logger.info("phone_number_added", number=request.number, admin=admin.email)

    return PhoneNumberAdmin(
        id=number.id,
        number=number.number,
        twilio_sid=number.twilio_sid,
        friendly_name=number.friendly_name,
        country=number.country,
        voice_enabled=number.voice_enabled,
        sms_enabled=number.sms_enabled,
        is_active=number.is_active,
        user_id=number.user_id,
        user_email=None,
        assigned_at=number.assigned_at,
        webhook_configured=number.webhook_configured,
        created_at=number.created_at,
    )


@router.patch("/phone-numbers/{number_id}")
async def update_phone_number(
    number_id: str,
    request: UpdatePhoneNumberRequest,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a phone number."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    number = result.scalar_one_or_none()

    if not number:
        raise HTTPException(status_code=404, detail="Phone number not found")

    if request.friendly_name is not None:
        number.friendly_name = request.friendly_name
    if request.is_active is not None:
        number.is_active = request.is_active

    await db.commit()

    return {"message": "Phone number updated"}


@router.delete("/phone-numbers/{number_id}")
async def delete_phone_number(
    number_id: str,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a phone number from the pool."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    number = result.scalar_one_or_none()

    if not number:
        raise HTTPException(status_code=404, detail="Phone number not found")

    if number.user_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete assigned phone number. Unassign it first.",
        )

    await db.delete(number)
    await db.commit()

    logger.info("phone_number_deleted", number=number.number, admin=admin.email)

    return {"message": "Phone number deleted"}


@router.post("/phone-numbers/{number_id}/unassign")
async def unassign_phone_number(
    number_id: str,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Forcefully unassign a phone number from a user."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    number = result.scalar_one_or_none()

    if not number:
        raise HTTPException(status_code=404, detail="Phone number not found")

    old_user_id = number.user_id
    number.user_id = None
    number.assigned_at = None
    number.webhook_configured = False

    await db.commit()

    logger.info(
        "phone_number_unassigned_by_admin",
        number=number.number,
        old_user_id=old_user_id,
        admin=admin.email,
    )

    return {"message": "Phone number unassigned"}


@router.get("/check")
async def check_admin(
    current_user: User = Depends(get_current_user),
):
    """Check if current user is an admin."""
    is_admin = current_user.email in ADMIN_EMAILS or current_user.is_admin
    return {"is_admin": is_admin, "email": current_user.email}


# ============== Twilio Number Search & Purchase ==============

class TwilioAvailableNumber(BaseModel):
    phone_number: str
    friendly_name: str
    locality: Optional[str]
    region: Optional[str]
    country: str
    capabilities: dict


class BuyNumberRequest(BaseModel):
    phone_number: str


@router.get("/twilio/available", response_model=list[TwilioAvailableNumber])
async def search_available_numbers(
    country: str = Query(default="US", description="Country code (US, CA, GB, AU, etc.)"),
    area_code: Optional[str] = Query(default=None, description="Area code to search"),
    contains: Optional[str] = Query(default=None, description="Pattern the number should contain"),
    admin: User = Depends(get_admin_user),
):
    """Search for available phone numbers to purchase from Twilio."""
    try:
        client = get_twilio_client()

        # Build search parameters
        search_params = {"voice_enabled": True, "limit": 20}
        if area_code:
            search_params["area_code"] = area_code
        if contains:
            search_params["contains"] = contains

        # Search for available numbers
        available = client.available_phone_numbers(country).local.list(**search_params)

        return [
            TwilioAvailableNumber(
                phone_number=num.phone_number,
                friendly_name=num.friendly_name,
                locality=num.locality,
                region=num.region,
                country=country,
                capabilities={
                    "voice": num.capabilities.get("voice", False),
                    "sms": num.capabilities.get("sms", False),
                    "mms": num.capabilities.get("mms", False),
                }
            )
            for num in available
        ]
    except TwilioRestException as e:
        logger.error("twilio_search_error", error=str(e))
        raise HTTPException(status_code=400, detail=f"Twilio error: {e.msg}")


@router.post("/twilio/buy")
async def buy_phone_number(
    request: BuyNumberRequest,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Purchase a phone number from Twilio and add it to the pool."""
    try:
        client = get_twilio_client()

        # Check if number already exists in our pool
        existing = await db.execute(
            select(PhoneNumber).where(PhoneNumber.number == request.phone_number)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Number already in pool")

        # Purchase the number from Twilio
        purchased = client.incoming_phone_numbers.create(
            phone_number=request.phone_number,
            voice_url=f"{settings.api_base_url}/api/v1/voice/twilio/incoming",
            voice_method="POST",
        )

        # Add to our phone number pool
        phone_number = PhoneNumber(
            number=purchased.phone_number,
            twilio_sid=purchased.sid,
            friendly_name=purchased.friendly_name,
            country=purchased.phone_number[:2] if purchased.phone_number.startswith("+1") else "US",
            voice_enabled=True,
            sms_enabled=purchased.capabilities.get("sms", False),
        )
        db.add(phone_number)
        await db.commit()
        await db.refresh(phone_number)

        logger.info(
            "phone_number_purchased",
            number=purchased.phone_number,
            sid=purchased.sid,
            admin=admin.email,
        )

        return {
            "message": "Number purchased successfully",
            "number": purchased.phone_number,
            "sid": purchased.sid,
        }

    except TwilioRestException as e:
        logger.error("twilio_purchase_error", error=str(e))
        raise HTTPException(status_code=400, detail=f"Twilio error: {e.msg}")
