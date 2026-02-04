"""Admin endpoints for managing the voice agent platform."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

from app.api.deps import get_super_admin_user, get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import logger
from app.models.global_settings import GlobalSettings, SETTING_ENABLED_MODELS, DEFAULT_MODELS
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

# Use the centralized dependency for admin access
get_admin_user = get_super_admin_user


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


@router.post("/phone-numbers/{number_id}/fix-webhook")
async def fix_phone_number_webhook(
    number_id: str,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Fix the Twilio webhook URL for a phone number."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    number = result.scalar_one_or_none()

    if not number:
        raise HTTPException(status_code=404, detail="Phone number not found")

    if not number.twilio_sid:
        raise HTTPException(status_code=400, detail="Phone number has no Twilio SID")

    try:
        client = get_twilio_client()

        # Use correct production URL
        base_url = "https://api-production-66de.up.railway.app"
        user_param = f"?user_id={number.user_id}" if number.user_id else ""
        webhook_url = f"{base_url}/api/v1/voice/twilio/incoming{user_param}"

        client.incoming_phone_numbers(number.twilio_sid).update(
            voice_url=webhook_url,
            voice_method="POST",
        )

        number.webhook_configured = True
        await db.commit()

        logger.info(
            "phone_webhook_fixed",
            number=number.number,
            webhook_url=webhook_url,
            admin=admin.email,
        )

        return {"message": "Webhook fixed", "webhook_url": webhook_url}

    except TwilioRestException as e:
        logger.error("twilio_webhook_fix_error", error=str(e))
        raise HTTPException(status_code=400, detail=f"Twilio error: {e.msg}")


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
    address_sid: Optional[str] = None


class TwilioAddress(BaseModel):
    sid: str
    friendly_name: str
    customer_name: str
    street: str
    city: str
    region: str
    postal_code: str
    country: str


@router.get("/twilio/addresses", response_model=list[TwilioAddress])
async def list_twilio_addresses(
    admin: User = Depends(get_admin_user),
):
    """List all addresses in the Twilio account."""
    try:
        client = get_twilio_client()
        addresses = client.addresses.list(limit=50)

        return [
            TwilioAddress(
                sid=addr.sid,
                friendly_name=addr.friendly_name or "",
                customer_name=addr.customer_name or "",
                street=addr.street or "",
                city=addr.city or "",
                region=addr.region or "",
                postal_code=addr.postal_code or "",
                country=addr.iso_country or "",
            )
            for addr in addresses
        ]
    except TwilioRestException as e:
        logger.error("twilio_address_list_error", error=str(e))
        raise HTTPException(status_code=400, detail=f"Twilio error: {e.msg}")


@router.get("/twilio/available", response_model=list[TwilioAvailableNumber])
async def search_available_numbers(
    country: str = Query(default="US", description="Country code (US, CA, GB, AU, etc.)"),
    area_code: Optional[str] = Query(default=None, description="Area code to search"),
    contains: Optional[str] = Query(default=None, description="Pattern the number should contain"),
    number_type: str = Query(default="local", description="Number type: local, mobile, toll_free"),
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

        # Get the right number type endpoint
        country_numbers = client.available_phone_numbers(country)
        if number_type == "mobile":
            available = country_numbers.mobile.list(**search_params)
        elif number_type == "toll_free":
            available = country_numbers.toll_free.list(**search_params)
        else:
            available = country_numbers.local.list(**search_params)

        return [
            TwilioAvailableNumber(
                phone_number=num.phone_number,
                friendly_name=num.friendly_name,
                locality=getattr(num, 'locality', None),
                region=getattr(num, 'region', None),
                country=country,
                capabilities={
                    "voice": num.capabilities.get("voice", False) if num.capabilities else False,
                    "sms": num.capabilities.get("sms", False) if num.capabilities else False,
                    "mms": num.capabilities.get("mms", False) if num.capabilities else False,
                }
            )
            for num in available
        ]
    except TwilioRestException as e:
        logger.error("twilio_search_error", error=str(e), country=country, number_type=number_type)
        raise HTTPException(status_code=400, detail=f"Twilio error: {e.msg}")
    except Exception as e:
        logger.error("twilio_search_error", error=str(e), country=country, number_type=number_type)
        raise HTTPException(status_code=500, detail=f"Error searching numbers: {str(e)}")


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

        # Build purchase params - use correct production URL
        base_url = settings.api_base_url
        if "trvel-fastapi-production" in base_url:
            base_url = "https://api-production-66de.up.railway.app"

        purchase_params = {
            "phone_number": request.phone_number,
            "voice_url": f"{base_url}/api/v1/voice/twilio/incoming",
            "voice_method": "POST",
        }

        # Add address SID if provided (required for AU, GB, and some other countries)
        if request.address_sid:
            purchase_params["address_sid"] = request.address_sid
        else:
            # Try to get the first available address as fallback
            try:
                addresses = client.addresses.list(limit=1)
                if addresses:
                    purchase_params["address_sid"] = addresses[0].sid
                    logger.info("using_default_address", address_sid=addresses[0].sid)
            except Exception:
                pass  # No address available, proceed without

        # Purchase the number from Twilio
        purchased = client.incoming_phone_numbers.create(**purchase_params)

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


# ============== Model Management ==============

class ModelInfo(BaseModel):
    id: str
    name: str
    enabled: bool


class ProviderModels(BaseModel):
    provider: str
    models: list[ModelInfo]


class ModelsResponse(BaseModel):
    providers: list[ProviderModels]


class ToggleModelRequest(BaseModel):
    enabled: bool


async def get_enabled_models_setting(db: AsyncSession) -> dict:
    """Get the enabled models setting from the database, or create default."""
    result = await db.execute(
        select(GlobalSettings).where(GlobalSettings.key == SETTING_ENABLED_MODELS)
    )
    setting = result.scalar_one_or_none()

    if not setting:
        # Create default setting with all models enabled
        setting = GlobalSettings(
            key=SETTING_ENABLED_MODELS,
            value=DEFAULT_MODELS,
            description="Controls which AI models are available to users",
        )
        db.add(setting)
        await db.commit()
        await db.refresh(setting)

    return setting.value


@router.get("/models", response_model=ModelsResponse)
async def list_all_models(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List all AI models with their enabled status (admin only)."""
    models_config = await get_enabled_models_setting(db)

    providers = []
    for provider, models in models_config.items():
        providers.append(ProviderModels(
            provider=provider,
            models=[ModelInfo(id=m["id"], name=m["name"], enabled=m["enabled"]) for m in models]
        ))

    return ModelsResponse(providers=providers)


@router.put("/models/{provider}/{model_id}/toggle")
async def toggle_model(
    provider: str,
    model_id: str,
    request: ToggleModelRequest,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle a model's enabled status (admin only)."""
    result = await db.execute(
        select(GlobalSettings).where(GlobalSettings.key == SETTING_ENABLED_MODELS)
    )
    setting = result.scalar_one_or_none()

    if not setting:
        # Create with defaults first
        await get_enabled_models_setting(db)
        result = await db.execute(
            select(GlobalSettings).where(GlobalSettings.key == SETTING_ENABLED_MODELS)
        )
        setting = result.scalar_one_or_none()

    models_config = setting.value

    # Validate provider exists
    if provider not in models_config:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")

    # Find and update the model
    model_found = False
    for model in models_config[provider]:
        if model["id"] == model_id:
            model["enabled"] = request.enabled
            model_found = True
            break

    if not model_found:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found in provider '{provider}'")

    # Update the setting
    setting.value = models_config
    await db.commit()

    logger.info(
        "model_toggled",
        provider=provider,
        model_id=model_id,
        enabled=request.enabled,
        admin=admin.email,
    )

    return {"message": f"Model '{model_id}' {'enabled' if request.enabled else 'disabled'}"}
