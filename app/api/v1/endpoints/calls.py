"""Call management endpoints for voice agent integration."""

import os
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user
from app.core.database import get_db
from app.core.logging import logger
from app.models.call_log import CallLog, CallTranscriptLog
from app.models.user import User

router = APIRouter()


# ============== S3 Presigned URL Helper ==============

def get_presigned_url(recording_url: Optional[str], expiration: int = 3600) -> Optional[str]:
    """
    Generate a presigned URL for S3 recording access.

    Handles URLs in formats:
    - https://bucket.s3.region.amazonaws.com/key
    - https://s3.region.amazonaws.com/bucket/key
    - s3://bucket/key

    Returns the original URL if not an S3 URL or if presigning fails.
    """
    if not recording_url:
        return None

    # Get AWS credentials
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("AWS_REGION", "ap-southeast-2")
    bucket_name = os.getenv("AWS_S3_BUCKET")

    if not all([access_key, secret_key, bucket_name]):
        logger.warning("AWS credentials not configured, returning original URL")
        return recording_url

    try:
        # Parse the URL to extract bucket and key
        key = None

        # Handle s3:// protocol
        if recording_url.startswith("s3://"):
            parts = recording_url[5:].split("/", 1)
            if len(parts) == 2:
                key = parts[1]

        # Handle https:// URLs
        elif recording_url.startswith("https://"):
            parsed = urlparse(recording_url)

            # Format: bucket.s3.region.amazonaws.com/key
            if ".s3." in parsed.netloc and "amazonaws.com" in parsed.netloc:
                key = parsed.path.lstrip("/")

            # Format: s3.region.amazonaws.com/bucket/key
            elif parsed.netloc.startswith("s3.") and "amazonaws.com" in parsed.netloc:
                path_parts = parsed.path.lstrip("/").split("/", 1)
                if len(path_parts) == 2:
                    key = path_parts[1]

        if not key:
            logger.warning(f"Could not parse S3 key from URL: {recording_url}")
            return recording_url

        # Create S3 client
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4"),
        )

        # Generate presigned URL
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": key},
            ExpiresIn=expiration,
        )

        logger.debug(f"Generated presigned URL for key: {key}")
        return presigned_url

    except ClientError as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        return recording_url
    except Exception as e:
        logger.error(f"Unexpected error generating presigned URL: {e}")
        return recording_url


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
    egress_id: Optional[str] = None
    recording_url: Optional[str] = None


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
    if request.egress_id:
        call.egress_id = request.egress_id
    if request.recording_url:
        call.recording_url = request.recording_url

    await db.commit()

    logger.info(
        "call_updated",
        call_id=call_id,
        status=request.status,
        recording_url=request.recording_url,
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


# ============== User-Facing Endpoints ==============
# These require authentication and return calls for the current user

class TranscriptResponse(BaseModel):
    """Transcript entry response."""
    speaker: str
    text: str
    confidence: Optional[float]
    start_time_ms: int
    end_time_ms: int


class CallDetailResponse(BaseModel):
    """Detailed call response with transcripts."""
    id: str
    room_name: str
    call_sid: Optional[str]
    direction: str
    status: str
    caller_number: Optional[str]
    callee_number: Optional[str]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    duration_seconds: Optional[int]
    ended_by: Optional[str]
    agent_response_count: int
    recording_url: Optional[str]
    transcripts: List[TranscriptResponse]

    class Config:
        from_attributes = True


class CallListResponse(BaseModel):
    """Call list item response."""
    id: str
    direction: str
    status: str
    caller_number: Optional[str]
    callee_number: Optional[str]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    duration_seconds: Optional[int]
    agent_response_count: int
    recording_url: Optional[str]

    class Config:
        from_attributes = True


@router.get("", response_model=List[CallListResponse])
async def list_user_calls(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """List all calls for the current user."""
    result = await db.execute(
        select(CallLog)
        .where(CallLog.user_id == current_user.id)
        .order_by(desc(CallLog.started_at))
        .limit(limit)
        .offset(offset)
    )
    calls = result.scalars().all()

    return [
        CallListResponse(
            id=call.id,
            direction=call.direction or "inbound",
            status=call.status or "unknown",
            caller_number=call.caller_number,
            callee_number=call.callee_number,
            started_at=call.started_at,
            ended_at=call.ended_at,
            duration_seconds=call.duration_seconds,
            agent_response_count=call.agent_response_count or 0,
            recording_url=get_presigned_url(call.recording_url),
        )
        for call in calls
    ]


@router.get("/{call_id}", response_model=CallDetailResponse)
async def get_user_call(
    call_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific call with transcripts for the current user."""
    # Get the call
    result = await db.execute(
        select(CallLog)
        .where(CallLog.id == call_id)
        .where(CallLog.user_id == current_user.id)
    )
    call = result.scalar_one_or_none()

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    # Get transcripts
    transcripts_result = await db.execute(
        select(CallTranscriptLog)
        .where(CallTranscriptLog.call_id == call_id)
        .order_by(CallTranscriptLog.start_time_ms)
    )
    transcripts = transcripts_result.scalars().all()

    return CallDetailResponse(
        id=call.id,
        room_name=call.room_name,
        call_sid=call.call_sid,
        direction=call.direction or "inbound",
        status=call.status or "unknown",
        caller_number=call.caller_number,
        callee_number=call.callee_number,
        started_at=call.started_at,
        ended_at=call.ended_at,
        duration_seconds=call.duration_seconds,
        ended_by=call.ended_by,
        agent_response_count=call.agent_response_count or 0,
        recording_url=get_presigned_url(call.recording_url),
        transcripts=[
            TranscriptResponse(
                speaker=t.speaker,
                text=t.text,
                confidence=t.confidence,
                start_time_ms=t.start_time_ms,
                end_time_ms=t.end_time_ms,
            )
            for t in transcripts
        ],
    )
