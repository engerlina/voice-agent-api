"""Tenant settings model for storing user configuration."""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TenantSettings(Base):
    """Settings model for voice agent configuration per user."""

    __tablename__ = "tenant_settings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), unique=True, nullable=False
    )

    # LLM Configuration
    llm_provider: Mapped[str] = mapped_column(String(50), default="openai", nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), default="gpt-4-turbo-preview", nullable=False)
    openai_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    anthropic_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Voice Configuration (STT)
    stt_provider: Mapped[str] = mapped_column(String(50), default="deepgram", nullable=False)
    deepgram_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Voice Configuration (TTS)
    tts_provider: Mapped[str] = mapped_column(String(50), default="elevenlabs", nullable=False)
    elevenlabs_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    elevenlabs_voice_id: Mapped[str] = mapped_column(String(100), default="21m00Tcm4TlvDq8ikWAM", nullable=False)

    # LiveKit Configuration
    livekit_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    livekit_api_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    livekit_api_secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Agent Behavior
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    welcome_message: Mapped[str] = mapped_column(
        Text, default="Hello! How can I help you today?", nullable=False
    )
    max_conversation_turns: Mapped[int] = mapped_column(default=50, nullable=False)

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
