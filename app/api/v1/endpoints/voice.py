"""Voice Agent API endpoints."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import Response
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
    # Mask phone number for display (show last 4 digits)
    phone = settings.twilio_phone_number
    masked_phone = f"***{phone[-4:]}" if phone and len(phone) >= 4 else None

    return {
        "enabled": settings.voice_agent_enabled,
        "livekit_configured": bool(settings.livekit_url),
        "stt_configured": bool(settings.deepgram_api_key),
        "tts_configured": bool(settings.elevenlabs_api_key),
        "llm_configured": bool(settings.openai_api_key or settings.anthropic_api_key),
        "telephony_configured": bool(settings.twilio_account_sid and settings.twilio_phone_number),
        "phone_number": phone if phone else None,
        "phone_number_masked": masked_phone,
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


@router.post("/twilio/incoming")
async def twilio_incoming_call(
    request: Request,
    user_id: str | None = Query(default=None, description="User ID for routing"),
    db: AsyncSession = Depends(get_db),
):
    """Handle incoming Twilio voice calls - main webhook endpoint.

    This connects the caller to a LiveKit room via SIP trunk for AI agent interaction.
    """
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    from_number = form_data.get("From")
    to_number = form_data.get("To")
    call_status = form_data.get("CallStatus")

    logger.info(
        "twilio_incoming_call",
        call_sid=call_sid,
        from_number=from_number,
        to_number=to_number,
        status=call_status,
        user_id=user_id,
    )

    # Check if voice agent is properly configured
    if not settings.voice_agent_enabled:
        logger.warning("voice_agent_not_configured", call_sid=call_sid)
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Amy">I'm sorry, the voice agent is not configured. Please contact support. Goodbye!</Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Check for LiveKit SIP URI (required for SIP trunk connection)
    livekit_sip_uri = getattr(settings, 'livekit_sip_uri', None)

    if not livekit_sip_uri:
        # No SIP trunk configured - use basic TwiML with greeting
        # The voice agent would need a separate process to connect via WebRTC
        logger.warning("livekit_sip_not_configured", call_sid=call_sid)

        # For now, provide a helpful response
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Amy">Hello! Thank you for calling. I'm your AI voice assistant.</Say>
    <Pause length="1"/>
    <Say voice="Polly.Amy">The LiveKit SIP trunk is being configured. Please try again shortly. Goodbye!</Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Generate a unique room name for this call
    room_name = f"call_{call_sid}"

    try:
        from app.services.livekit_service import LiveKitService

        # Create LiveKit room for the call
        livekit = LiveKitService()
        await livekit.create_room(
            room_name=room_name,
            empty_timeout=300,  # 5 minutes
            max_participants=3,  # Caller + Agent + possible transfer
            metadata={"call_sid": call_sid, "from": from_number, "to": to_number},
        )

        logger.info("livekit_room_created", room_name=room_name, call_sid=call_sid)

        # Build SIP URI for the LiveKit room
        # Format: sip:<room_name>@<livekit_sip_domain>
        sip_uri = f"sip:{room_name}@{livekit_sip_uri}"

        # Return TwiML that dials the LiveKit SIP endpoint
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial callerId="{to_number}" timeout="30">
        <Sip>{sip_uri}</Sip>
    </Dial>
</Response>"""

        logger.info("twilio_dial_sip", sip_uri=sip_uri, call_sid=call_sid)

    except Exception as e:
        logger.error("livekit_room_creation_failed", error=str(e), call_sid=call_sid)
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Amy">I'm sorry, there was an error connecting your call. Please try again later.</Say>
    <Hangup/>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


@router.post("/webhooks/twilio/voice")
async def twilio_voice_webhook(request: Request):
    """Handle incoming Twilio voice webhooks (legacy endpoint)."""
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    call_status = form_data.get("CallStatus")

    logger.info(
        "twilio_webhook",
        call_sid=call_sid,
        status=call_status,
    )

    # Return TwiML response
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Hello! Thank you for calling.</Say>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


@router.post("/webhooks/livekit")
async def livekit_webhook(
    request: dict[str, Any],
):
    """Handle LiveKit room webhooks."""
    event_type = request.get("event")

    logger.info("livekit_webhook", event_type=event_type)

    return {"status": "ok"}
