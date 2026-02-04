"""Create user_tenants junction table for roles

Revision ID: 009
Revises: 008
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

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
    # Create user_tenants table using raw SQL to avoid SQLAlchemy enum issues
    if not table_exists('user_tenants'):
        # Create enum type (ignore if exists)
        op.execute("""
            DO $$ BEGIN
                CREATE TYPE user_role_enum AS ENUM ('super_admin', 'admin', 'user');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$
        """)

        # Create user_tenants table
        op.execute("""
            CREATE TABLE user_tenants (
                id UUID PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                role user_role_enum NOT NULL DEFAULT 'user',
                is_primary BOOLEAN NOT NULL DEFAULT FALSE,
                invited_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, tenant_id)
            )
        """)

        # Create indexes separately
        op.execute("CREATE INDEX ix_user_tenants_user_id ON user_tenants(user_id)")
        op.execute("CREATE INDEX ix_user_tenants_tenant_id ON user_tenants(tenant_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_tenants")
    op.execute("DROP TYPE IF EXISTS user_role_enum")
