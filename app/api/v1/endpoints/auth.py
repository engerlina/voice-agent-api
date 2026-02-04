"""Authentication endpoints for Voice Agent Dashboard."""

import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.invitation import Invitation, InvitationStatus
from app.models.tenant import Tenant, TenantConfig, TenantStatus
from app.models.user import User
from app.models.user_tenant import UserTenant, UserRole

router = APIRouter()
security = HTTPBearer()


def generate_slug(name: str) -> str:
    """Generate a URL-safe slug from organization name."""
    # Convert to lowercase, replace spaces with hyphens
    slug = name.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)  # Remove special chars
    slug = re.sub(r'[\s_]+', '-', slug)  # Replace spaces/underscores with hyphens
    slug = re.sub(r'-+', '-', slug)  # Remove multiple hyphens
    slug = slug.strip('-')
    # Add random suffix for uniqueness
    suffix = secrets.token_hex(4)
    return f"{slug}-{suffix}" if slug else suffix


# Pydantic models
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    organization_name: Optional[str] = None  # Required unless invite_token provided
    invite_token: Optional[str] = None  # Token from invitation link

    @field_validator('organization_name')
    @classmethod
    def validate_organization_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if len(v) < 2:
            raise ValueError('Organization name must be at least 2 characters')
        if len(v) > 200:
            raise ValueError('Organization name must be less than 200 characters')
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TenantInfo(BaseModel):
    """Tenant information for user context."""
    id: str
    name: str
    slug: str
    role: str

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str]
    is_active: bool
    is_admin: bool = False
    current_tenant: Optional[TenantInfo] = None
    tenants: list[TenantInfo] = []

    class Config:
        from_attributes = True


# Helper functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against stored hash."""
    # Hash format: salt$hash
    if "$" not in hashed_password:
        return False
    salt, stored_hash = hashed_password.split("$", 1)
    computed_hash = hashlib.pbkdf2_hmac(
        "sha256", plain_password.encode(), salt.encode(), 100000
    ).hex()
    return secrets.compare_digest(computed_hash, stored_hash)


def get_password_hash(password: str) -> str:
    """Hash password with random salt."""
    salt = secrets.token_hex(16)
    hash_value = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 100000
    ).hex()
    return f"{salt}${hash_value}"


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
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


# Endpoints
@router.post("/signup", response_model=Token)
async def signup(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user.

    If invite_token is provided, user joins an existing organization.
    Otherwise, a new organization is created.
    """
    # Check if user exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    invitation = None

    # Handle invited signup
    if user_data.invite_token:
        # Validate invitation
        result = await db.execute(
            select(Invitation)
            .where(Invitation.token == user_data.invite_token)
        )
        invitation = result.scalar_one_or_none()

        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitation token",
            )

        if invitation.status != InvitationStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation has already been used or revoked",
            )

        if not invitation.is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation has expired",
            )

        # Email must match invitation
        if user_data.email.lower() != invitation.email.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match invitation",
            )
    else:
        # Normal signup requires organization_name
        if not user_data.organization_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization name is required",
            )

    # Create user
    user = User(
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=get_password_hash(user_data.password),
        tenant_name=user_data.organization_name or "",  # Keep for backwards compat
    )
    db.add(user)
    await db.flush()  # Get user.id without committing

    if invitation:
        # Invited signup: join existing tenant with invitation's role
        user_tenant = UserTenant(
            user_id=user.id,
            tenant_id=invitation.tenant_id,
            role=invitation.role,
            is_primary=True,
            invited_by_id=invitation.invited_by_id,
        )
        db.add(user_tenant)

        # Mark invitation as accepted
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.utcnow()
    else:
        # Normal signup: create new tenant
        tenant = Tenant(
            id=uuid.uuid4(),
            name=user_data.organization_name,
            slug=generate_slug(user_data.organization_name),
            email=user_data.email,
            status=TenantStatus.TRIAL,
            is_active=True,
        )
        db.add(tenant)
        await db.flush()  # Get tenant.id

        # Create default tenant config
        tenant_config = TenantConfig(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
        )
        db.add(tenant_config)

        # Link user to tenant as admin
        user_tenant = UserTenant(
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserRole.ADMIN,
            is_primary=True,
        )
        db.add(user_tenant)

    await db.commit()
    await db.refresh(user)

    # Generate tokens
    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(data={"sub": user.email})

    return Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=Token)
async def login(user_data: UserLogin, db: AsyncSession = Depends(get_db)):
    """Login and get access token."""
    result = await db.execute(select(User).where(User.email == user_data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )

    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(data={"sub": user.email})

    return Token(access_token=access_token, refresh_token=refresh_token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user info with tenant context."""
    # Load user's tenant memberships
    result = await db.execute(
        select(UserTenant)
        .options(selectinload(UserTenant.tenant))
        .where(UserTenant.user_id == current_user.id)
    )
    memberships = result.scalars().all()

    # Build tenant info list
    tenants = []
    current_tenant = None
    for membership in memberships:
        tenant_info = TenantInfo(
            id=str(membership.tenant.id),
            name=membership.tenant.name,
            slug=membership.tenant.slug,
            role=membership.role.value,
        )
        tenants.append(tenant_info)
        # Primary tenant is the current context
        if membership.is_primary:
            current_tenant = tenant_info

    # If no primary set, use first tenant
    if not current_tenant and tenants:
        current_tenant = tenants[0]

    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        is_admin=current_user.is_admin,
        current_tenant=current_tenant,
        tenants=tenants,
    )
