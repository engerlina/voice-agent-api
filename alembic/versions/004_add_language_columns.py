"""Add language and auto_detect_language columns to tenant_settings

Revision ID: 004
Revises: 003
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists in table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # Add language column if it doesn't exist
    if not column_exists('tenant_settings', 'language'):
        op.add_column('tenant_settings',
            sa.Column('language', sa.String(10), nullable=False, server_default='en')
        )

    # Add auto_detect_language column if it doesn't exist
    if not column_exists('tenant_settings', 'auto_detect_language'):
        op.add_column('tenant_settings',
            sa.Column('auto_detect_language', sa.Boolean, nullable=False, server_default='false')
        )


def downgrade() -> None:
    if column_exists('tenant_settings', 'language'):
        op.drop_column('tenant_settings', 'language')
    if column_exists('tenant_settings', 'auto_detect_language'):
        op.drop_column('tenant_settings', 'auto_detect_language')
