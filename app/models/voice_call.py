"""Call and session models."""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class CallStatus(str, enum.Enum):
    """Call status states."""

    INITIATED = "initiated"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    TRANSFERRED = "transferred"


class CallDirection(str, enum.Enum):
    """Call direction."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Call(Base, TimestampMixin, TenantMixin):
    """Call/session record."""

    __tablename__ = "calls"

    # Call identification
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    livekit_room_id: Mapped[str | None] = mapped_column(String(255))
    twilio_sid: Mapped[str | None] = mapped_column(String(255))

    # Call details
    direction: Mapped[CallDirection] = mapped_column(Enum(CallDirection), nullable=False)
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus),
        default=CallStatus.INITIATED,
        nullable=False,
    )

    # Parties
    caller_number: Mapped[str | None] = mapped_column(String(50))
    callee_number: Mapped[str | None] = mapped_column(String(50))
    caller_name: Mapped[str | None] = mapped_column(String(255))

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    # Disposition
    ended_by: Mapped[str | None] = mapped_column(String(50))  # "caller", "agent", "system"
    transfer_target: Mapped[str | None] = mapped_column(String(255))

    # AI metrics
    agent_response_count: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="calls")
    events: Mapped[list["CallEvent"]] = relationship(
        "CallEvent",
        back_populates="call",
        cascade="all, delete-orphan",
    )
    transcripts: Mapped[list["CallTranscript"]] = relationship(
        "CallTranscript",
        back_populates="call",
        cascade="all, delete-orphan",
    )


class CallEvent(Base, TimestampMixin):
    """Call event log for audit trail."""

    __tablename__ = "call_events"

    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_data: Mapped[dict | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Relationships
    call: Mapped["Call"] = relationship("Call", back_populates="events")


class CallTranscript(Base, TimestampMixin):
    """Call transcript entries."""

    __tablename__ = "call_transcripts"

    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Speaker
    speaker: Mapped[str] = mapped_column(String(50), nullable=False)  # "caller", "agent"

    # Content
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column()

    # Timing
    start_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    call: Mapped["Call"] = relationship("Call", back_populates="transcripts")
