"""Invitation endpoints for team member invitations."""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_tenant_admin_context, CurrentUserContext
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.invitation import Invitation, InvitationStatus, generate_invite_token, default_expiry
from app.models.user import User
from app.models.user_tenant import UserRole
from app.services.delivery_service import DeliveryService

router = APIRouter()
logger = get_logger(__name__)


# Pydantic schemas
class InvitationCreate(BaseModel):
    email: EmailStr
    role: str = "user"  # "admin" or "user"


class InvitedByInfo(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None


class InvitationResponse(BaseModel):
    id: str
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime
    invited_by: InvitedByInfo

    class Config:
        from_attributes = True


class InvitationValidateResponse(BaseModel):
    valid: bool
    email: Optional[str] = None
    tenant_name: Optional[str] = None
    role: Optional[str] = None
    expires_at: Optional[datetime] = None
    invited_by: Optional[str] = None


class TeamMemberResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str]
    role: str
    joined_at: datetime
    invited_by: Optional[InvitedByInfo] = None

    class Config:
        from_attributes = True


@router.post("", response_model=InvitationResponse)
async def create_invitation(
    data: InvitationCreate,
    context: CurrentUserContext = Depends(get_tenant_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Create an invitation and send email to the invitee.

    Only tenant admins can invite new members.
    """
    # Validate role
    try:
        role = UserRole(data.role)
        # Don't allow inviting super_admins
        if role == UserRole.SUPER_ADMIN:
            role = UserRole.ADMIN
    except ValueError:
        role = UserRole.USER

    # Check if user already exists in this tenant
    existing_user = await db.execute(
        select(User).where(User.email == data.email)
    )
    user = existing_user.scalar_one_or_none()

    if user:
        # Check if already a member of this tenant
        from app.models.user_tenant import UserTenant
        existing_membership = await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == user.id,
                UserTenant.tenant_id == context.tenant_id
            )
        )
        if existing_membership.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is already a member of this organization",
            )

    # Check for existing pending invitation
    existing_invite = await db.execute(
        select(Invitation).where(
            Invitation.email == data.email,
            Invitation.tenant_id == context.tenant_id,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    if existing_invite.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An invitation is already pending for this email",
        )

    # Create invitation
    invitation = Invitation(
        id=uuid.uuid4(),
        tenant_id=context.tenant_id,
        email=data.email,
        role=role,
        token=generate_invite_token(),
        invited_by_id=context.user.id,
        expires_at=default_expiry(),
        status=InvitationStatus.PENDING,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    # Send invitation email
    try:
        delivery = DeliveryService()
        await delivery.send_invitation_email(
            email=data.email,
            organization_name=context.tenant.name,
            inviter_name=context.user.full_name or context.user.email,
            role=role.value,
            invite_token=invitation.token,
        )
    except Exception as e:
        logger.error("invitation_email_failed", error=str(e), email=data.email)
        # Don't fail the invitation creation, just log the error

    logger.info(
        "invitation_created",
        email=data.email,
        tenant_id=str(context.tenant_id),
        invited_by=context.user.email,
    )

    return InvitationResponse(
        id=str(invitation.id),
        email=invitation.email,
        role=invitation.role.value,
        status=invitation.status.value,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        invited_by=InvitedByInfo(
            id=context.user.id,
            email=context.user.email,
            full_name=context.user.full_name,
        ),
    )


@router.get("", response_model=list[InvitationResponse])
async def list_invitations(
    context: CurrentUserContext = Depends(get_tenant_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """List all pending invitations for the current tenant."""
    result = await db.execute(
        select(Invitation)
        .options(selectinload(Invitation.invited_by))
        .where(
            Invitation.tenant_id == context.tenant_id,
            Invitation.status == InvitationStatus.PENDING,
        )
        .order_by(Invitation.created_at.desc())
    )
    invitations = result.scalars().all()

    return [
        InvitationResponse(
            id=str(inv.id),
            email=inv.email,
            role=inv.role.value,
            status=inv.status.value,
            expires_at=inv.expires_at,
            created_at=inv.created_at,
            invited_by=InvitedByInfo(
                id=inv.invited_by.id if inv.invited_by else "",
                email=inv.invited_by.email if inv.invited_by else "",
                full_name=inv.invited_by.full_name if inv.invited_by else None,
            ),
        )
        for inv in invitations
    ]


@router.delete("/{invitation_id}")
async def revoke_invitation(
    invitation_id: str,
    context: CurrentUserContext = Depends(get_tenant_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a pending invitation."""
    try:
        inv_uuid = uuid.UUID(invitation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid invitation ID")

    result = await db.execute(
        select(Invitation).where(
            Invitation.id == inv_uuid,
            Invitation.tenant_id == context.tenant_id,
        )
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot revoke invitation with status: {invitation.status.value}",
        )

    invitation.status = InvitationStatus.REVOKED
    await db.commit()

    logger.info(
        "invitation_revoked",
        invitation_id=invitation_id,
        email=invitation.email,
        revoked_by=context.user.email,
    )

    return {"message": "Invitation revoked"}


@router.post("/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: str,
    context: CurrentUserContext = Depends(get_tenant_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Resend invitation email."""
    try:
        inv_uuid = uuid.UUID(invitation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid invitation ID")

    result = await db.execute(
        select(Invitation).where(
            Invitation.id == inv_uuid,
            Invitation.tenant_id == context.tenant_id,
        )
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail="Can only resend pending invitations",
        )

    # Refresh expiry
    invitation.expires_at = default_expiry()
    await db.commit()

    # Resend email
    try:
        delivery = DeliveryService()
        await delivery.send_invitation_email(
            email=invitation.email,
            organization_name=context.tenant.name,
            inviter_name=context.user.full_name or context.user.email,
            role=invitation.role.value,
            invite_token=invitation.token,
        )
    except Exception as e:
        logger.error("invitation_resend_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to resend invitation email")

    logger.info(
        "invitation_resent",
        invitation_id=invitation_id,
        email=invitation.email,
    )

    return {"message": "Invitation resent"}


@router.get("/validate/{token}", response_model=InvitationValidateResponse)
async def validate_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Validate an invitation token (public endpoint).

    Used by the signup page to pre-fill email and show organization name.
    """
    result = await db.execute(
        select(Invitation)
        .options(selectinload(Invitation.tenant), selectinload(Invitation.invited_by))
        .where(Invitation.token == token)
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        return InvitationValidateResponse(valid=False)

    if invitation.status != InvitationStatus.PENDING:
        return InvitationValidateResponse(valid=False)

    # Check expiry
    if datetime.utcnow() > invitation.expires_at.replace(tzinfo=None):
        # Mark as expired
        invitation.status = InvitationStatus.EXPIRED
        await db.commit()
        return InvitationValidateResponse(valid=False)

    inviter_name = invitation.invited_by.full_name or invitation.invited_by.email if invitation.invited_by else "Someone"

    return InvitationValidateResponse(
        valid=True,
        email=invitation.email,
        tenant_name=invitation.tenant.name,
        role=invitation.role.value,
        expires_at=invitation.expires_at,
        invited_by=inviter_name,
    )


@router.get("/members", response_model=list[TeamMemberResponse])
async def list_team_members(
    context: CurrentUserContext = Depends(get_tenant_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """List all members of the current tenant."""
    from app.models.user_tenant import UserTenant

    result = await db.execute(
        select(UserTenant)
        .options(selectinload(UserTenant.user), selectinload(UserTenant.invited_by))
        .where(UserTenant.tenant_id == context.tenant_id)
        .order_by(UserTenant.joined_at)
    )
    memberships = result.scalars().all()

    return [
        TeamMemberResponse(
            id=str(m.id),
            email=m.user.email,
            full_name=m.user.full_name,
            role=m.role.value,
            joined_at=m.joined_at,
            invited_by=InvitedByInfo(
                id=m.invited_by.id,
                email=m.invited_by.email,
                full_name=m.invited_by.full_name,
            ) if m.invited_by else None,
        )
        for m in memberships
    ]
