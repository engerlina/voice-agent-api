"""Create tenant_settings table and ensure stt_provider column exists

Revision ID: 002
Revises: 001
Create Date: 2026-02-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if table exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists in table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # Create tenant_settings table if it doesn't exist
    if not table_exists('tenant_settings'):
        op.create_table(
            'tenant_settings',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), unique=True, nullable=False),
            sa.Column('llm_provider', sa.String(50), nullable=False, server_default='openai'),
            sa.Column('llm_model', sa.String(100), nullable=False, server_default='gpt-4-turbo-preview'),
            sa.Column('stt_provider', sa.String(50), nullable=False, server_default='deepgram'),
            sa.Column('elevenlabs_voice_id', sa.String(100), nullable=False, server_default='21m00Tcm4TlvDq8ikWAM'),
            sa.Column('system_prompt', sa.Text, nullable=True),
            sa.Column('welcome_message', sa.Text, nullable=False, server_default='Hello! How can I help you today?'),
            sa.Column('max_conversation_turns', sa.Integer, nullable=False, server_default='50'),
            sa.Column('rag_enabled', sa.Boolean, nullable=False, server_default='true'),
            sa.Column('call_recording_enabled', sa.Boolean, nullable=False, server_default='false'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    else:
        # Table exists - ensure stt_provider column exists
        if not column_exists('tenant_settings', 'stt_provider'):
            op.add_column('tenant_settings',
                sa.Column('stt_provider', sa.String(50), nullable=False, server_default='deepgram')
            )


def downgrade() -> None:
    if table_exists('tenant_settings'):
        op.drop_table('tenant_settings')
