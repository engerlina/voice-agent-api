"""Phone number model for multi-tenant telephony."""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PhoneNumber(Base):
    """Phone numbers available for tenants to claim.

    Admin pre-provisions numbers from Twilio, tenants claim them.
    """

    __tablename__ = "phone_numbers"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # The actual phone number (E.164 format)
    number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)

    # Twilio SID for this number
    twilio_sid: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Display name / friendly name
    friendly_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Country code
    country: Mapped[str] = mapped_column(String(2), default="US", nullable=False)

    # Capabilities
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Assignment
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    webhook_configured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    @property
    def is_available(self) -> bool:
        """Check if number is available for assignment."""
        return self.is_active and self.user_id is None

    def __repr__(self) -> str:
        return f"<PhoneNumber {self.number}>"
