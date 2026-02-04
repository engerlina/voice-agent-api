"""Settings endpoints for Voice Agent Dashboard."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user
from app.core.database import get_db
from app.models.global_settings import GlobalSettings, SETTING_ENABLED_MODELS
from app.models.settings import TenantSettings
from app.models.user import User
from app.services.models_service import get_all_available_models, merge_with_settings

router = APIRouter()


# Pydantic models
class SettingsResponse(BaseModel):
    """Settings response - what the frontend sees."""
    # LLM
    llm_provider: str
    llm_model: str

    # Voice
    elevenlabs_voice_id: str

    # Agent Behavior
    system_prompt: Optional[str]
    welcome_message: str
    max_conversation_turns: int

    # Language settings
    language: str
    auto_detect_language: bool

    # Response speed
    min_silence_duration: float

    # Features
    rag_enabled: bool
    call_recording_enabled: bool

    class Config:
        from_attributes = True


class SettingsUpdate(BaseModel):
    """Settings that can be updated by the user."""
    # LLM
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None

    # Voice
    elevenlabs_voice_id: Optional[str] = None

    # Agent Behavior
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    max_conversation_turns: Optional[int] = None

    # Language settings
    language: Optional[str] = None
    auto_detect_language: Optional[bool] = None

    # Response speed
    min_silence_duration: Optional[float] = None

    # Features
    rag_enabled: Optional[bool] = None
    call_recording_enabled: Optional[bool] = None


class AvailableModelsResponse(BaseModel):
    openai: list[str]
    anthropic: list[str]


def settings_to_response(settings: TenantSettings) -> SettingsResponse:
    """Convert TenantSettings model to response."""
    return SettingsResponse(
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        elevenlabs_voice_id=settings.elevenlabs_voice_id,
        system_prompt=settings.system_prompt,
        welcome_message=settings.welcome_message,
        max_conversation_turns=settings.max_conversation_turns,
        language=settings.language,
        auto_detect_language=settings.auto_detect_language,
        min_silence_duration=settings.min_silence_duration,
        rag_enabled=settings.rag_enabled,
        call_recording_enabled=settings.call_recording_enabled,
    )


@router.get("", response_model=SettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's settings."""
    result = await db.execute(
        select(TenantSettings).where(TenantSettings.user_id == current_user.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Create default settings for this user
        settings = TenantSettings(user_id=current_user.id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return settings_to_response(settings)


@router.put("", response_model=SettingsResponse)
async def update_settings(
    updates: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user's settings."""
    result = await db.execute(
        select(TenantSettings).where(TenantSettings.user_id == current_user.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = TenantSettings(user_id=current_user.id)
        db.add(settings)

    # Update only provided fields
    update_data = updates.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)

    return settings_to_response(settings)


@router.get("/models", response_model=AvailableModelsResponse)
async def get_available_models(
    db: AsyncSession = Depends(get_db),
):
    """Get list of available AI models (only enabled models).

    Fetches models dynamically and filters to only those enabled by admin.
    """
    # Fetch available models from providers
    available_models = await get_all_available_models()

    # Get stored settings (enabled/disabled state)
    result = await db.execute(
        select(GlobalSettings).where(GlobalSettings.key == SETTING_ENABLED_MODELS)
    )
    setting = result.scalar_one_or_none()
    stored_settings = setting.value if setting else None

    # Merge: available models + stored enabled/disabled state
    models_config = merge_with_settings(available_models, stored_settings)

    # Filter to only enabled models (return just the IDs for the user)
    openai_models = [
        m["id"] for m in models_config.get("openai", []) if m.get("enabled", True)
    ]
    anthropic_models = [
        m["id"] for m in models_config.get("anthropic", []) if m.get("enabled", True)
    ]

    return AvailableModelsResponse(
        openai=openai_models,
        anthropic=anthropic_models,
    )


# Internal endpoint for voice agent to fetch settings by user_id
class AgentSettingsResponse(BaseModel):
    """Settings response for voice agent - includes all config needed."""
    user_id: str
    llm_provider: str
    llm_model: str
    stt_provider: str
    tts_provider: str
    elevenlabs_voice_id: str
    system_prompt: Optional[str]
    welcome_message: str
    max_conversation_turns: int
    rag_enabled: bool
    call_recording_enabled: bool
    # Language settings
    language: str
    auto_detect_language: bool
    # Response speed
    min_silence_duration: float

    class Config:
        from_attributes = True


@router.get("/agent/by-phone/{phone_number:path}", response_model=AgentSettingsResponse)
async def get_agent_settings_by_phone(
    phone_number: str,
    db: AsyncSession = Depends(get_db),
):
    """Get settings by phone number - for voice agent when user_id is not available.

    The phone number should be in E.164 format (e.g., +61340525699).
    """
    from app.models.phone_number import PhoneNumber

    # Find user by phone number
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.number == phone_number)
    )
    phone = result.scalar_one_or_none()

    if not phone or not phone.user_id:
        # Return defaults if phone not found or not assigned
        return AgentSettingsResponse(
            user_id="unknown",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            stt_provider="deepgram",
            tts_provider="elevenlabs",
            elevenlabs_voice_id="21m00Tcm4TlvDq8ikWAM",
            system_prompt=None,
            welcome_message="Hello! How can I help you today?",
            max_conversation_turns=50,
            rag_enabled=True,
            call_recording_enabled=False,
            language="en",
            auto_detect_language=False,
            min_silence_duration=0.4,
        )

    # Get user's settings
    result = await db.execute(
        select(TenantSettings).where(TenantSettings.user_id == phone.user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Return defaults for this user
        return AgentSettingsResponse(
            user_id=phone.user_id,
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            stt_provider="deepgram",
            tts_provider="elevenlabs",
            elevenlabs_voice_id="21m00Tcm4TlvDq8ikWAM",
            system_prompt=None,
            welcome_message="Hello! How can I help you today?",
            max_conversation_turns=50,
            rag_enabled=True,
            call_recording_enabled=False,
            language="en",
            auto_detect_language=False,
            min_silence_duration=0.4,
        )

    return AgentSettingsResponse(
        user_id=phone.user_id,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        stt_provider=settings.stt_provider,
        tts_provider=settings.tts_provider,
        elevenlabs_voice_id=settings.elevenlabs_voice_id,
        system_prompt=settings.system_prompt,
        welcome_message=settings.welcome_message,
        max_conversation_turns=settings.max_conversation_turns,
        rag_enabled=settings.rag_enabled,
        call_recording_enabled=settings.call_recording_enabled,
        language=settings.language,
        auto_detect_language=settings.auto_detect_language,
        min_silence_duration=settings.min_silence_duration,
    )


# Keep the original user_id endpoint working
@router.get("/agent/user/{user_id}", response_model=AgentSettingsResponse)
async def get_agent_settings_by_user_id(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Alias for get_agent_settings."""
    result = await db.execute(
        select(TenantSettings).where(TenantSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Return defaults if no settings exist
        return AgentSettingsResponse(
            user_id=user_id,
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            stt_provider="deepgram",
            tts_provider="elevenlabs",
            elevenlabs_voice_id="21m00Tcm4TlvDq8ikWAM",
            system_prompt=None,
            welcome_message="Hello! How can I help you today?",
            max_conversation_turns=50,
            rag_enabled=True,
            call_recording_enabled=False,
            language="en",
            auto_detect_language=False,
            min_silence_duration=0.4,
        )

    return AgentSettingsResponse(
        user_id=user_id,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        stt_provider=settings.stt_provider,
        tts_provider=settings.tts_provider,
        elevenlabs_voice_id=settings.elevenlabs_voice_id,
        system_prompt=settings.system_prompt,
        welcome_message=settings.welcome_message,
        max_conversation_turns=settings.max_conversation_turns,
        rag_enabled=settings.rag_enabled,
        call_recording_enabled=settings.call_recording_enabled,
        language=settings.language,
        auto_detect_language=settings.auto_detect_language,
        min_silence_duration=settings.min_silence_duration,
    )
