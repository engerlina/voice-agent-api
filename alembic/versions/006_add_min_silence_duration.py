"""Add min_silence_duration column to tenant_settings

Revision ID: 006
Revises: 005
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists in table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # Add min_silence_duration column if it doesn't exist
    if not column_exists('tenant_settings', 'min_silence_duration'):
        op.add_column('tenant_settings',
            sa.Column('min_silence_duration', sa.Float, nullable=False, server_default='0.4')
        )


def downgrade() -> None:
    if column_exists('tenant_settings', 'min_silence_duration'):
        op.drop_column('tenant_settings', 'min_silence_duration')
