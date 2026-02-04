"""Create tenants and tenant_configs tables

Revision ID: 008
Revises: 007
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID

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
    # Create tenant_status enum
    tenant_status_enum = sa.Enum(
        'active', 'suspended', 'trial', 'cancelled',
        name='tenant_status_enum'
    )

    if not table_exists('tenants'):
        tenant_status_enum.create(op.get_bind(), checkfirst=True)

        op.create_table(
            'tenants',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('slug', sa.String(100), unique=True, nullable=False, index=True),
            sa.Column('status', tenant_status_enum, nullable=False, server_default='trial'),
            sa.Column('email', sa.String(255), nullable=False),
            sa.Column('phone', sa.String(50), nullable=True),
            sa.Column('website', sa.String(255), nullable=True),
            sa.Column('twilio_phone_number', sa.String(50), nullable=True),
            sa.Column('sip_trunk_uri', sa.String(255), nullable=True),
            sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if not table_exists('tenant_configs'):
        op.create_table(
            'tenant_configs',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), unique=True, nullable=False),
            sa.Column('business_hours', sa.JSON, nullable=True),
            sa.Column('timezone', sa.String(50), server_default='America/New_York', nullable=False),
            sa.Column('system_prompt', sa.Text, nullable=True),
            sa.Column('greeting_message', sa.Text, server_default="Hello! Thank you for calling. How can I help you today?", nullable=False),
            sa.Column('voice_id', sa.String(100), nullable=True),
            sa.Column('llm_model', sa.String(100), server_default='gpt-4o-mini', nullable=False),
            sa.Column('temperature', sa.Float, server_default='0.7', nullable=False),
            sa.Column('language', sa.String(10), server_default='en', nullable=False),
            sa.Column('auto_detect_language', sa.Boolean, server_default='false', nullable=False),
            sa.Column('transfer_number', sa.String(50), nullable=True),
            sa.Column('voicemail_enabled', sa.Boolean, server_default='true', nullable=False),
            sa.Column('max_call_duration_seconds', sa.Integer, server_default='1800', nullable=False),
            sa.Column('rag_enabled', sa.Boolean, server_default='true', nullable=False),
            sa.Column('rag_top_k', sa.Integer, server_default='5', nullable=False),
            sa.Column('rag_similarity_threshold', sa.Float, server_default='0.7', nullable=False),
            sa.Column('metadata', sa.JSON, nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    if table_exists('tenant_configs'):
        op.drop_table('tenant_configs')
    if table_exists('tenants'):
        op.drop_table('tenants')
    # Drop enum type
    op.execute("DROP TYPE IF EXISTS tenant_status_enum")
