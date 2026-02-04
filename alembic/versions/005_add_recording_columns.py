"""Add egress_id and recording_url columns to call_logs

Revision ID: 005
Revises: 004
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists in table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # Add egress_id column if it doesn't exist
    if not column_exists('call_logs', 'egress_id'):
        op.add_column('call_logs',
            sa.Column('egress_id', sa.String(255), nullable=True)
        )

    # Add recording_url column if it doesn't exist
    if not column_exists('call_logs', 'recording_url'):
        op.add_column('call_logs',
            sa.Column('recording_url', sa.Text, nullable=True)
        )


def downgrade() -> None:
    if column_exists('call_logs', 'egress_id'):
        op.drop_column('call_logs', 'egress_id')
    if column_exists('call_logs', 'recording_url'):
        op.drop_column('call_logs', 'recording_url')
