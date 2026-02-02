"""Create call_logs and call_transcript_logs tables.

Revision ID: 003
Revises: 002
Create Date: 2026-02-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if call_logs table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "call_logs" not in existing_tables:
        op.create_table(
            "call_logs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("room_name", sa.String(255), nullable=False, index=True),
            sa.Column("call_sid", sa.String(255), nullable=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True, index=True),
            sa.Column("direction", sa.String(20), default="inbound"),
            sa.Column("status", sa.String(50), default="in_progress"),
            sa.Column("caller_number", sa.String(50), nullable=True),
            sa.Column("callee_number", sa.String(50), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_seconds", sa.Integer, nullable=True),
            sa.Column("ended_by", sa.String(50), nullable=True),
            sa.Column("agent_response_count", sa.Integer, default=0),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "call_transcript_logs" not in existing_tables:
        op.create_table(
            "call_transcript_logs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("call_id", sa.String(36), sa.ForeignKey("call_logs.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("speaker", sa.String(50), nullable=False),
            sa.Column("text", sa.Text, nullable=False),
            sa.Column("confidence", sa.Float, nullable=True),
            sa.Column("start_time_ms", sa.Integer, nullable=False),
            sa.Column("end_time_ms", sa.Integer, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("call_transcript_logs")
    op.drop_table("call_logs")
