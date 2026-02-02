"""Simple call log model for storing call records and transcripts."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Float
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CallLog(Base):
    """Simple call log for recording calls and transcripts."""

    __tablename__ = "call_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Call identification
    room_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    call_sid: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )

    # Call details
    direction: Mapped[str] = mapped_column(String(20), default="inbound")
    status: Mapped[str] = mapped_column(String(50), default="in_progress")
    caller_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    callee_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Disposition
    ended_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    agent_response_count: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationship to transcripts
    transcripts: Mapped[list["CallTranscriptLog"]] = relationship(
        "CallTranscriptLog",
        back_populates="call",
        cascade="all, delete-orphan",
    )


class CallTranscriptLog(Base):
    """Call transcript entries."""

    __tablename__ = "call_transcript_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    call_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("call_logs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Speaker
    speaker: Mapped[str] = mapped_column(String(50), nullable=False)  # "caller", "agent"

    # Content
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Timing
    start_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationship
    call: Mapped["CallLog"] = relationship("CallLog", back_populates="transcripts")
