"""Invitation model for user invitations to tenants."""

import enum
import secrets
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user_tenant import UserRole

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.user import User


class InvitationStatus(str, enum.Enum):
    """Status of an invitation."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


def generate_invite_token() -> str:
    """Generate a secure random token for invitations."""
    return secrets.token_urlsafe(32)


def default_expiry() -> datetime:
    """Default expiration: 7 days from now."""
    return datetime.utcnow() + timedelta(days=7)


class Invitation(Base):
    """Invitation to join a tenant.

    When a tenant admin invites someone, an invitation is created with a unique token.
    The invitee receives an email with a magic link containing the token.
    When they sign up using that link, they automatically join the tenant.
    """

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Which tenant is the user being invited to
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Email of the person being invited
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    # Role they will have when they join
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum", create_type=False),
        default=UserRole.USER,
        nullable=False,
    )

    # Secure token for the magic link
    token: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        default=generate_invite_token,
    )

    # Who sent the invitation
    invited_by_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # When the invitation expires
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=default_expiry,
    )

    # Status tracking
    status: Mapped[InvitationStatus] = mapped_column(
        Enum(InvitationStatus, name="invitation_status_enum"),
        default=InvitationStatus.PENDING,
        nullable=False,
    )

    # When the invitation was accepted (if accepted)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")
    invited_by: Mapped["User"] = relationship("User")

    @property
    def is_valid(self) -> bool:
        """Check if invitation is still valid (pending and not expired)."""
        if self.status != InvitationStatus.PENDING:
            return False
        return datetime.utcnow() < self.expires_at.replace(tzinfo=None)

    def __repr__(self) -> str:
        return f"<Invitation {self.email} to tenant={self.tenant_id} status={self.status.value}>"
