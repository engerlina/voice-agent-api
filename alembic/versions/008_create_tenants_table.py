"""Create tenants and tenant_configs tables

Revision ID: 008
Revises: 007
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID, ENUM

# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if table exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # Create tenants table using raw SQL to avoid SQLAlchemy enum issues
    if not table_exists('tenants'):
        # Create enum type (ignore if exists)
        op.execute("""
            DO $$ BEGIN
                CREATE TYPE tenant_status_enum AS ENUM ('active', 'suspended', 'trial', 'cancelled');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$
        """)

        # Create tenants table
        op.execute("""
            CREATE TABLE tenants (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(100) UNIQUE NOT NULL,
                status tenant_status_enum NOT NULL DEFAULT 'trial',
                email VARCHAR(255) NOT NULL,
                phone VARCHAR(50),
                website VARCHAR(255),
                twilio_phone_number VARCHAR(50),
                sip_trunk_uri VARCHAR(255),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
        """)

        # Create index separately
        op.execute("CREATE INDEX ix_tenants_slug ON tenants(slug)")

    if not table_exists('tenant_configs'):
        op.execute("""
            CREATE TABLE tenant_configs (
                id UUID PRIMARY KEY,
                tenant_id UUID UNIQUE NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                business_hours JSONB,
                timezone VARCHAR(50) NOT NULL DEFAULT 'America/New_York',
                system_prompt TEXT,
                greeting_message TEXT NOT NULL DEFAULT 'Hello! Thank you for calling. How can I help you today?',
                voice_id VARCHAR(100),
                llm_model VARCHAR(100) NOT NULL DEFAULT 'gpt-4o-mini',
                temperature FLOAT NOT NULL DEFAULT 0.7,
                language VARCHAR(10) NOT NULL DEFAULT 'en',
                auto_detect_language BOOLEAN NOT NULL DEFAULT FALSE,
                transfer_number VARCHAR(50),
                voicemail_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                max_call_duration_seconds INTEGER NOT NULL DEFAULT 1800,
                rag_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                rag_top_k INTEGER NOT NULL DEFAULT 5,
                rag_similarity_threshold FLOAT NOT NULL DEFAULT 0.7,
                metadata JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_configs")
    op.execute("DROP TABLE IF EXISTS tenants")
    op.execute("DROP TYPE IF EXISTS tenant_status_enum")
