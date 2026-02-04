"""Create global_settings table for platform-wide configuration

Revision ID: 007
Revises: 006
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if table exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not table_exists('global_settings'):
        op.create_table(
            'global_settings',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('key', sa.String(100), unique=True, nullable=False, index=True),
            sa.Column('value', sa.JSON, nullable=True),
            sa.Column('description', sa.Text, nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    if table_exists('global_settings'):
        op.drop_table('global_settings')
