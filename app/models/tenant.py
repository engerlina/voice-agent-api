"""Tenant models for multi-tenancy."""

import enum
import uuid
from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, String, Text, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.call import Call
    from app.models.document import Document
    from app.models.user import UserTenant


class TenantStatus(str, enum.Enum):
    """Tenant account status."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"
    CANCELLED = "cancelled"


class Tenant(Base, TimestampMixin):
    """Tenant (organization/clinic) model."""

    __tablename__ = "tenants"

    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus),
        default=TenantStatus.TRIAL,
        nullable=False,
    )

    # Contact
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(255))

    # Telephony
    twilio_phone_number: Mapped[str | None] = mapped_column(String(50))
    sip_trunk_uri: Mapped[str | None] = mapped_column(String(255))

    # Feature flags
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    users: Mapped[list["UserTenant"]] = relationship(
        "UserTenant",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    config: Mapped["TenantConfig | None"] = relationship(
        "TenantConfig",
        back_populates="tenant",
        uselist=False,
        cascade="all, delete-orphan",
    )
    calls: Mapped[list["Call"]] = relationship(
        "Call",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )


class TenantConfig(Base, TimestampMixin):
    """Tenant-specific configuration."""

    __tablename__ = "tenant_configs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # Business hours (stored as JSON for flexibility)
    business_hours: Mapped[dict | None] = mapped_column(
        JSON,
        default=lambda: {
            "monday": {"open": "09:00", "close": "17:00"},
            "tuesday": {"open": "09:00", "close": "17:00"},
            "wednesday": {"open": "09:00", "close": "17:00"},
            "thursday": {"open": "09:00", "close": "17:00"},
            "friday": {"open": "09:00", "close": "17:00"},
            "saturday": None,
            "sunday": None,
        },
    )
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York")

    # AI Agent configuration
    system_prompt: Mapped[str | None] = mapped_column(Text)
    greeting_message: Mapped[str] = mapped_column(
        Text,
        default="Hello! Thank you for calling. How can I help you today?",
    )
    voice_id: Mapped[str | None] = mapped_column(String(100))
    llm_model: Mapped[str] = mapped_column(String(100), default="gpt-4-turbo-preview")
    temperature: Mapped[float] = mapped_column(default=0.7)

    # Call routing
    transfer_number: Mapped[str | None] = mapped_column(String(50))
    voicemail_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_call_duration_seconds: Mapped[int] = mapped_column(default=1800)  # 30 min

    # RAG settings
    rag_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rag_top_k: Mapped[int] = mapped_column(default=5)
    rag_similarity_threshold: Mapped[float] = mapped_column(default=0.7)

    # Custom metadata
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="config")
