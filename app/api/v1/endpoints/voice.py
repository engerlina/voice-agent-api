"""Voice Agent API endpoints."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import logger

router = APIRouter()


# ============== Schemas ==============

class CallCreate(BaseModel):
    """Create call schema."""
    to_number: str
    from_number: str | None = None
    metadata: dict[str, Any] | None = None


class CallResponse(BaseModel):
    """Call response schema."""
    id: str
    direction: str
    status: str
    caller_number: str | None
    callee_number: str | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    created_at: datetime


class DocumentCreate(BaseModel):
    """Create document for RAG."""
    name: str
    description: str | None = None
    content: str
    metadata: dict[str, Any] | None = None


class DocumentResponse(BaseModel):
    """Document response schema."""
    id: str
    name: str
    description: str | None
    status: str
    chunk_count: int
    created_at: datetime


class SearchRequest(BaseModel):
    """RAG search request."""
    query: str
    top_k: int = 5


class SearchResult(BaseModel):
    """Search result."""
    document_name: str
    content: str
    similarity: float


class SearchResponse(BaseModel):
    """Search response."""
    query: str
    results: list[SearchResult]


class LiveKitTokenRequest(BaseModel):
    """Request for LiveKit room token."""
    room_name: str
    participant_name: str


class LiveKitTokenResponse(BaseModel):
    """LiveKit token response."""
    token: str
    room_name: str
    url: str


# ============== Endpoints ==============

@router.get("/status")
async def voice_agent_status():
    """Check if voice agent is configured and ready."""
    return {
        "enabled": settings.voice_agent_enabled,
        "livekit_configured": bool(settings.livekit_url),
        "stt_configured": bool(settings.deepgram_api_key),
        "tts_configured": bool(settings.elevenlabs_api_key),
        "llm_configured": bool(settings.openai_api_key or settings.anthropic_api_key),
    }


@router.post("/livekit/token", response_model=LiveKitTokenResponse)
async def get_livekit_token(request: LiveKitTokenRequest):
    """Get a LiveKit room token for joining a call."""
    if not settings.voice_agent_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice agent not configured",
        )

    from app.services.livekit_service import LiveKitService

    livekit = LiveKitService()
    token = livekit.create_room_token(
        room_name=request.room_name,
        participant_identity=request.participant_name,
    )

    return LiveKitTokenResponse(
        token=token,
        room_name=request.room_name,
        url=settings.livekit_url,
    )


@router.post("/calls", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
async def initiate_call(
    request: CallCreate,
    db: AsyncSession = Depends(get_db),
):
    """Initiate an outbound voice call."""
    if not settings.voice_agent_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice agent not configured",
        )

    call_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # TODO: Create call record in database
    # TODO: Trigger actual call via Twilio/LiveKit

    logger.info(
        "call_initiated",
        call_id=call_id,
        to_number=request.to_number,
    )

    return CallResponse(
        id=call_id,
        direction="outbound",
        status="initiated",
        caller_number=request.from_number or settings.twilio_phone_number,
        callee_number=request.to_number,
        started_at=now,
        ended_at=None,
        duration_seconds=None,
        created_at=now,
    )


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    request: DocumentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a document for RAG knowledge base."""
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # TODO: Store document and queue for processing
    logger.info(
        "document_created",
        document_id=doc_id,
        name=request.name,
    )

    return DocumentResponse(
        id=doc_id,
        name=request.name,
        description=request.description,
        status="pending",
        chunk_count=0,
        created_at=now,
    )


@router.post("/documents/search", response_model=SearchResponse)
async def search_documents(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Search documents using RAG vector similarity."""
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG not configured - OpenAI API key required",
        )

    # TODO: Implement actual vector search with RAG service
    logger.info("rag_search", query=request.query, top_k=request.top_k)

    return SearchResponse(
        query=request.query,
        results=[],
    )


@router.post("/webhooks/twilio/voice")
async def twilio_voice_webhook(
    request: dict[str, Any],
):
    """Handle incoming Twilio voice webhooks."""
    call_sid = request.get("CallSid")
    call_status = request.get("CallStatus")

    logger.info(
        "twilio_webhook",
        call_sid=call_sid,
        status=call_status,
    )

    # Return TwiML response
    return {
        "response": """<?xml version='1.0' encoding='UTF-8'?>
<Response>
    <Say>Hello! Thank you for calling Trvel support. How can I help you today?</Say>
    <Pause length='1'/>
</Response>"""
    }


@router.post("/webhooks/livekit")
async def livekit_webhook(
    request: dict[str, Any],
):
    """Handle LiveKit room webhooks."""
    event_type = request.get("event")

    logger.info("livekit_webhook", event_type=event_type)

    return {"status": "ok"}
