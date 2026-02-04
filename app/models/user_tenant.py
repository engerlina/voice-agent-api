"""UserTenant junction model for multi-tenant user roles."""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.user import User


class UserRole(str, enum.Enum):
    """User role within a tenant."""

    SUPER_ADMIN = "super_admin"  # Platform owner - managed via ADMIN_EMAILS, not DB
    ADMIN = "admin"  # Tenant administrator
    USER = "user"  # Regular tenant member


class UserTenant(Base):
    """Junction table linking users to tenants with roles.

    A user can belong to multiple tenants with different roles in each.
    Each tenant must have at least one admin.
    """

    __tablename__ = "user_tenants"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # FK to users table (String(36) UUID format)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # FK to tenants table (UUID)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Role within this tenant
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum"),
        default=UserRole.USER,
        nullable=False,
    )

    # Is this the user's primary/default tenant?
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Invitation tracking
    invited_by_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Timestamps
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
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
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="tenant_memberships",
    )
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="users",
    )
    invited_by: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[invited_by_id],
    )

    def __repr__(self) -> str:
        return f"<UserTenant user={self.user_id} tenant={self.tenant_id} role={self.role.value}>"
