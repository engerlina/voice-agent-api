"""Global settings model for platform-wide configuration."""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GlobalSettings(Base):
    """Key-value store for global platform settings.

    Used for storing platform-wide configuration like enabled AI models.
    """

    __tablename__ = "global_settings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<GlobalSettings key={self.key}>"


# Constants for global settings keys
SETTING_ENABLED_MODELS = "enabled_models"

# Default model configurations
DEFAULT_MODELS = {
    "openai": [
        {"id": "gpt-4-turbo-preview", "name": "GPT-4 Turbo Preview", "enabled": True},
        {"id": "gpt-4", "name": "GPT-4", "enabled": True},
        {"id": "gpt-4o", "name": "GPT-4o", "enabled": True},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "enabled": True},
        {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "enabled": True},
    ],
    "anthropic": [
        {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus", "enabled": True},
        {"id": "claude-3-sonnet-20240229", "name": "Claude 3 Sonnet", "enabled": True},
        {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "enabled": True},
        {"id": "claude-3-haiku-20240307", "name": "Claude 3 Haiku", "enabled": True},
    ],
}
