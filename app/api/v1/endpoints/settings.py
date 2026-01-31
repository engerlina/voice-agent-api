"""Settings endpoints for Voice Agent Dashboard."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user
from app.core.database import get_db
from app.models.settings import TenantSettings
from app.models.user import User

router = APIRouter()


# Pydantic models
class SettingsResponse(BaseModel):
    # LLM
    llm_provider: str
    llm_model: str
    openai_api_key_set: bool
    anthropic_api_key_set: bool

    # STT
    stt_provider: str
    deepgram_api_key_set: bool

    # TTS
    tts_provider: str
    elevenlabs_api_key_set: bool
    elevenlabs_voice_id: str

    # LiveKit
    livekit_url: Optional[str]
    livekit_configured: bool

    # Agent Behavior
    system_prompt: Optional[str]
    welcome_message: str
    max_conversation_turns: int

    # Features
    rag_enabled: bool
    call_recording_enabled: bool

    class Config:
        from_attributes = True


class SettingsUpdate(BaseModel):
    # LLM
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # STT
    stt_provider: Optional[str] = None
    deepgram_api_key: Optional[str] = None

    # TTS
    tts_provider: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None

    # LiveKit
    livekit_url: Optional[str] = None
    livekit_api_key: Optional[str] = None
    livekit_api_secret: Optional[str] = None

    # Agent Behavior
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    max_conversation_turns: Optional[int] = None

    # Features
    rag_enabled: Optional[bool] = None
    call_recording_enabled: Optional[bool] = None


class AvailableModelsResponse(BaseModel):
    openai: list[str]
    anthropic: list[str]


def mask_api_key(key: Optional[str]) -> bool:
    """Return True if API key is set, False otherwise."""
    return bool(key and len(key) > 0)


def settings_to_response(settings: TenantSettings) -> SettingsResponse:
    """Convert TenantSettings model to response."""
    return SettingsResponse(
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        openai_api_key_set=mask_api_key(settings.openai_api_key),
        anthropic_api_key_set=mask_api_key(settings.anthropic_api_key),
        stt_provider=settings.stt_provider,
        deepgram_api_key_set=mask_api_key(settings.deepgram_api_key),
        tts_provider=settings.tts_provider,
        elevenlabs_api_key_set=mask_api_key(settings.elevenlabs_api_key),
        elevenlabs_voice_id=settings.elevenlabs_voice_id,
        livekit_url=settings.livekit_url,
        livekit_configured=bool(settings.livekit_url and settings.livekit_api_key),
        system_prompt=settings.system_prompt,
        welcome_message=settings.welcome_message,
        max_conversation_turns=settings.max_conversation_turns,
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
async def get_available_models():
    """Get list of available AI models."""
    return AvailableModelsResponse(
        openai=[
            "gpt-4-turbo-preview",
            "gpt-4",
            "gpt-4-32k",
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-16k",
        ],
        anthropic=[
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
            "claude-2.1",
            "claude-2.0",
        ],
    )
