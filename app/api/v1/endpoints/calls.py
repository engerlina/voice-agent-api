"""Call management endpoints for voice agent integration."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import logger
from app.models.call_log import CallLog, CallTranscriptLog

router = APIRouter()


# ============== Schemas ==============

class CallCreateRequest(BaseModel):
    """Create a new call record."""
    room_name: str
    call_sid: Optional[str] = None
    caller_number: Optional[str] = None
    callee_number: Optional[str] = None
    user_id: Optional[str] = None
    direction: str = "inbound"


class CallUpdateRequest(BaseModel):
    """Update call status."""
    status: Optional[str] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    ended_by: Optional[str] = None
    agent_response_count: Optional[int] = None


class TranscriptEntry(BaseModel):
    """A single transcript entry."""
    speaker: str  # "caller" or "agent"
    text: str
    confidence: Optional[float] = None
    start_time_ms: int
    end_time_ms: int


class TranscriptBatchRequest(BaseModel):
    """Batch of transcripts to save."""
    call_id: str
    entries: list[TranscriptEntry]


class CallResponse(BaseModel):
    """Call response."""
    id: str
    room_name: str
    status: str
    caller_number: Optional[str]
    callee_number: Optional[str]
    started_at: Optional[datetime]


# ============== Internal Endpoints ==============
# These are called by the voice agent, not authenticated users

@router.post("/internal/create", response_model=CallResponse)
async def create_call(
    request: CallCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a call record. Called by voice agent when call starts."""
    now = datetime.now(timezone.utc)

    # Create call record using simple CallLog model
    call = CallLog(
        room_name=request.room_name,
        call_sid=request.call_sid,
        direction=request.direction,
        status="in_progress",
        caller_number=request.caller_number,
        callee_number=request.callee_number,
        started_at=now,
        user_id=request.user_id,
    )

    db.add(call)
    await db.commit()
    await db.refresh(call)

    logger.info(
        "call_created",
        call_id=call.id,
        room_name=request.room_name,
        caller=request.caller_number,
    )

    return CallResponse(
        id=call.id,
        room_name=request.room_name,
        status="in_progress",
        caller_number=request.caller_number,
        callee_number=request.callee_number,
        started_at=now,
    )


@router.post("/internal/{call_id}/update")
async def update_call(
    call_id: str,
    request: CallUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update call status. Called by voice agent when call ends."""
    result = await db.execute(
        select(CallLog).where(CallLog.id == call_id)
    )
    call = result.scalar_one_or_none()

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    if request.status:
        call.status = request.status
    if request.ended_at:
        call.ended_at = request.ended_at
    if request.duration_seconds is not None:
        call.duration_seconds = request.duration_seconds
    if request.ended_by:
        call.ended_by = request.ended_by
    if request.agent_response_count is not None:
        call.agent_response_count = request.agent_response_count

    await db.commit()

    logger.info(
        "call_updated",
        call_id=call_id,
        status=request.status,
    )

    return {"status": "updated"}


@router.post("/internal/transcripts")
async def save_transcripts(
    request: TranscriptBatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Save transcript entries. Called by voice agent during/after call."""
    for entry in request.entries:
        transcript = CallTranscriptLog(
            call_id=request.call_id,
            speaker=entry.speaker,
            text=entry.text,
            confidence=entry.confidence,
            start_time_ms=entry.start_time_ms,
            end_time_ms=entry.end_time_ms,
        )
        db.add(transcript)

    await db.commit()

    logger.info(
        "transcripts_saved",
        call_id=request.call_id,
        count=len(request.entries),
    )

    return {"status": "saved", "count": len(request.entries)}


@router.get("/internal/{call_id}/transcripts")
async def get_call_transcripts(
    call_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all transcripts for a call."""
    result = await db.execute(
        select(CallTranscriptLog)
        .where(CallTranscriptLog.call_id == call_id)
        .order_by(CallTranscriptLog.start_time_ms)
    )
    transcripts = result.scalars().all()

    return {
        "call_id": call_id,
        "transcripts": [
            {
                "speaker": t.speaker,
                "text": t.text,
                "confidence": t.confidence,
                "start_time_ms": t.start_time_ms,
                "end_time_ms": t.end_time_ms,
            }
            for t in transcripts
        ],
    }
