"""Tenant settings model for storing user configuration."""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TenantSettings(Base):
    """Settings model for voice agent configuration per user.

    Note: API keys (OpenAI, Anthropic, Deepgram, ElevenLabs, LiveKit)
    are stored globally in environment variables, not per-tenant.
    LiveKit is multi-tenant - each call gets its own room.
    """

    __tablename__ = "tenant_settings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), unique=True, nullable=False
    )

    # LLM Configuration (provider choice only - keys are global)
    llm_provider: Mapped[str] = mapped_column(String(50), default="openai", nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), default="gpt-4-turbo-preview", nullable=False)

    # STT Configuration (Speech-to-Text) - required by database
    stt_provider: Mapped[str] = mapped_column(String(50), default="deepgram", nullable=False)

    # TTS Configuration (Text-to-Speech) - required by database
    tts_provider: Mapped[str] = mapped_column(String(50), default="elevenlabs", nullable=False)

    # Voice Configuration (voice selection only - keys are global)
    elevenlabs_voice_id: Mapped[str] = mapped_column(String(100), default="21m00Tcm4TlvDq8ikWAM", nullable=False)

    # Agent Behavior
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    welcome_message: Mapped[str] = mapped_column(
        Text, default="Hello! How can I help you today?", nullable=False
    )
    max_conversation_turns: Mapped[int] = mapped_column(Integer, default=50, nullable=False)

    # Language Configuration
    # Supported: en, zh (Mandarin), yue (Cantonese), vi, ar, el, it, hi, tl, es, ko, ja, fr, de, pt
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    auto_detect_language: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Response Speed Configuration
    # min_silence_duration: How long to wait after user stops speaking before responding (seconds)
    # Lower = faster response but may cut off user mid-sentence
    # Default: 0.55, Fast: 0.3, Very Fast: 0.2
    min_silence_duration: Mapped[float] = mapped_column(Float, default=0.4, nullable=False)

    # Feature Flags
    rag_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    call_recording_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<TenantSettings user_id={self.user_id}>"
