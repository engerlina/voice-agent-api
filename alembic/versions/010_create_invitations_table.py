"""Create invitations table

Revision ID: 010
Revises: 009
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if table exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not table_exists('invitations'):
        # Create invitation_status enum (ignore if exists)
        op.execute("""
            DO $$ BEGIN
                CREATE TYPE invitation_status_enum AS ENUM ('pending', 'accepted', 'expired', 'revoked');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$
        """)

        # Create invitations table
        op.execute("""
            CREATE TABLE invitations (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                email VARCHAR(255) NOT NULL,
                role user_role_enum NOT NULL DEFAULT 'user',
                token VARCHAR(64) UNIQUE NOT NULL,
                invited_by_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                status invitation_status_enum NOT NULL DEFAULT 'pending',
                accepted_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
        """)

        # Create indexes
        op.execute("CREATE INDEX ix_invitations_tenant_id ON invitations(tenant_id)")
        op.execute("CREATE INDEX ix_invitations_email ON invitations(email)")
        op.execute("CREATE INDEX ix_invitations_token ON invitations(token)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invitations")
    op.execute("DROP TYPE IF EXISTS invitation_status_enum")
