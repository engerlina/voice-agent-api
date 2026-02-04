"""Create user_tenants junction table for roles

Revision ID: 009
Revises: 008
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if table exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # Create user_role enum
    user_role_enum = sa.Enum(
        'super_admin', 'admin', 'user',
        name='user_role_enum'
    )

    if not table_exists('user_tenants'):
        user_role_enum.create(op.get_bind(), checkfirst=True)

        op.create_table(
            'user_tenants',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            # User FK - String(36) to match users.id
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
            # Tenant FK - UUID to match tenants.id
            sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
            # Role within this tenant
            sa.Column('role', user_role_enum, nullable=False, server_default='user'),
            # Is this the user's primary/default tenant?
            sa.Column('is_primary', sa.Boolean, nullable=False, server_default='false'),
            # Who invited this user (nullable for self-created tenants)
            sa.Column('invited_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            # Timestamps
            sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            # Unique constraint: one membership per user per tenant
            sa.UniqueConstraint('user_id', 'tenant_id', name='uq_user_tenant'),
        )


def downgrade() -> None:
    if table_exists('user_tenants'):
        op.drop_table('user_tenants')
    # Drop enum type
    op.execute("DROP TYPE IF EXISTS user_role_enum")
