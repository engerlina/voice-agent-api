"""Dependency injection for API endpoints - authentication and permissions."""

from typing import Optional
import uuid

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_tenant import UserTenant, UserRole

security = HTTPBearer()

# Super admin emails - platform owners
SUPER_ADMIN_EMAILS = ["jonochan@gmail.com", "jonathan@aineversleeps.net"]


class CurrentUserContext:
    """Context object containing user and optional tenant context."""

    def __init__(
        self,
        user: User,
        tenant: Optional[Tenant] = None,
        membership: Optional[UserTenant] = None,
    ):
        self.user = user
        self.tenant = tenant
        self.membership = membership

    @property
    def role(self) -> Optional[UserRole]:
        """Get user's role in current tenant."""
        if self.membership:
            return self.membership.role
        return None

    @property
    def is_super_admin(self) -> bool:
        """Check if user is a platform super admin."""
        return self.user.email in SUPER_ADMIN_EMAILS or self.user.is_admin

    @property
    def is_tenant_admin(self) -> bool:
        """Check if user is admin of current tenant."""
        if self.is_super_admin:
            return True
        return self.membership and self.membership.role == UserRole.ADMIN

    @property
    def tenant_id(self) -> Optional[uuid.UUID]:
        """Get current tenant ID."""
        return self.tenant.id if self.tenant else None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the current user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


async def get_current_user_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> CurrentUserContext:
    """Get current user with their tenant context.

    Tenant can be specified via X-Tenant-ID header.
    If not specified, uses user's primary tenant.
    """
    # Load user's tenant memberships
    result = await db.execute(
        select(UserTenant)
        .options(selectinload(UserTenant.tenant))
        .where(UserTenant.user_id == current_user.id)
    )
    memberships = result.scalars().all()

    if not memberships:
        # User has no tenant memberships - return without context
        return CurrentUserContext(user=current_user)

    # Find the target tenant
    target_membership = None

    if x_tenant_id:
        # Use specified tenant if user has access
        try:
            tenant_uuid = uuid.UUID(x_tenant_id)
            for m in memberships:
                if m.tenant_id == tenant_uuid:
                    target_membership = m
                    break
            if not target_membership:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have access to this tenant",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid tenant ID format",
            )
    else:
        # Use primary tenant, or first available
        for m in memberships:
            if m.is_primary:
                target_membership = m
                break
        if not target_membership:
            target_membership = memberships[0]

    return CurrentUserContext(
        user=current_user,
        tenant=target_membership.tenant,
        membership=target_membership,
    )


async def get_super_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require platform super admin access.

    Super admins are determined by:
    - Email in SUPER_ADMIN_EMAILS list
    - is_admin flag on User model
    """
    if current_user.email not in SUPER_ADMIN_EMAILS and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )
    return current_user


async def get_tenant_admin_context(
    context: CurrentUserContext = Depends(get_current_user_context),
) -> CurrentUserContext:
    """Require tenant admin access.

    Tenant admins can:
    - Manage tenant settings
    - Invite/remove users
    - Update user roles within tenant
    """
    if not context.is_tenant_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admin access required",
        )
    return context


async def require_tenant_context(
    context: CurrentUserContext = Depends(get_current_user_context),
) -> CurrentUserContext:
    """Require user to have an active tenant context.

    Use this for endpoints that need tenant scoping.
    """
    if not context.tenant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tenant context. Please join or create an organization.",
        )
    return context
