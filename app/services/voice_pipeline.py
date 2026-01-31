"""Voice AI pipeline orchestrator (STT -> LLM -> TTS)."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from anthropic import AsyncAnthropic
from deepgram import DeepgramClient, LiveTranscriptionEvents, PrerecordedOptions
from elevenlabs import AsyncElevenLabs
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.call import Call, CallTranscript
from app.models.tenant import TenantConfig
from app.services.rag import RAGService

logger = get_logger(__name__)


@dataclass
class ConversationMessage:
    """A message in the conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class VoiceSessionState:
    """State for an active voice session."""

    call_id: uuid.UUID
    tenant_id: uuid.UUID
    room_name: str
    conversation: list[ConversationMessage] = field(default_factory=list)
    is_active: bool = True
    last_user_speech_time: datetime | None = None
    response_count: int = 0


class VoicePipeline:
    """Orchestrates the voice AI pipeline for a call session."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_config: TenantConfig,
        call: Call,
    ) -> None:
        self.db = db
        self.config = tenant_config
        self.call = call
        self.rag = RAGService(db)

        # Initialize AI clients
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.anthropic = (
            AsyncAnthropic(api_key=settings.anthropic_api_key)
            if settings.anthropic_api_key
            else None
        )
        self.deepgram = DeepgramClient(settings.deepgram_api_key)
        self.elevenlabs = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)

        # Session state
        self.state = VoiceSessionState(
            call_id=call.id,
            tenant_id=call.tenant_id,
            room_name=f"call_{call.id}",
        )

    def _build_system_prompt(self, context: str = "") -> str:
        """Build the system prompt with tenant config and RAG context."""
        base_prompt = self.config.system_prompt or (
            "You are a helpful voice assistant. Be concise and conversational. "
            "Keep responses brief (1-2 sentences) unless more detail is needed."
        )

        if context:
            return f"""{base_prompt}

Use the following information to help answer questions:

{context}

Remember to be conversational and concise in your responses."""

        return base_prompt

    async def transcribe_audio(self, audio_data: bytes) -> str:
        """Transcribe audio using Deepgram."""
        try:
            options = PrerecordedOptions(
                model="nova-2",
                smart_format=True,
                punctuate=True,
                diarize=False,
            )

            response = await self.deepgram.listen.asyncrest.v1.transcribe_file(
                {"buffer": audio_data, "mimetype": "audio/webm"},
                options,
            )

            transcript = response.results.channels[0].alternatives[0].transcript
            return transcript

        except Exception as e:
            logger.error("Transcription failed", error=str(e))
            return ""

    async def generate_response(self, user_message: str) -> str:
        """Generate LLM response with RAG context."""
        # Get relevant context from RAG
        context = ""
        if self.config.rag_enabled:
            context = await self.rag.get_context_for_query(
                tenant_id=self.call.tenant_id,
                query=user_message,
                top_k=self.config.rag_top_k,
            )

        # Build messages
        system_prompt = self._build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history
        for msg in self.state.conversation[-10:]:  # Last 10 messages
            messages.append({"role": msg.role, "content": msg.content})

        # Add current user message
        messages.append({"role": "user", "content": user_message})

        # Generate response
        try:
            if "claude" in self.config.llm_model.lower() and self.anthropic:
                response = await self.anthropic.messages.create(
                    model=self.config.llm_model,
                    max_tokens=500,
                    system=system_prompt,
                    messages=messages[1:],  # Anthropic handles system separately
                    temperature=self.config.temperature,
                )
                assistant_message = response.content[0].text
            else:
                response = await self.openai.chat.completions.create(
                    model=self.config.llm_model,
                    messages=messages,
                    max_tokens=500,
                    temperature=self.config.temperature,
                )
                assistant_message = response.choices[0].message.content or ""

            # Store in conversation history
            self.state.conversation.append(
                ConversationMessage(role="user", content=user_message)
            )
            self.state.conversation.append(
                ConversationMessage(role="assistant", content=assistant_message)
            )
            self.state.response_count += 1

            return assistant_message

        except Exception as e:
            logger.error("LLM response generation failed", error=str(e))
            return "I'm sorry, I'm having trouble processing your request. Could you please repeat that?"

    async def synthesize_speech(self, text: str) -> AsyncGenerator[bytes, None]:
        """Synthesize speech using ElevenLabs (streaming)."""
        voice_id = self.config.voice_id or settings.elevenlabs_voice_id

        try:
            audio_stream = await self.elevenlabs.generate(
                text=text,
                voice=voice_id,
                model="eleven_turbo_v2",
                stream=True,
            )

            async for chunk in audio_stream:
                yield chunk

        except Exception as e:
            logger.error("Speech synthesis failed", error=str(e))
            # Return empty audio or fallback

    async def process_speech_turn(self, audio_data: bytes) -> AsyncGenerator[bytes, None]:
        """Process a complete speech turn: STT -> LLM -> TTS."""
        # Transcribe user speech
        user_text = await self.transcribe_audio(audio_data)

        if not user_text.strip():
            return

        logger.info(
            "User speech transcribed",
            call_id=str(self.call.id),
            text=user_text,
        )

        # Save transcript
        transcript = CallTranscript(
            call_id=self.call.id,
            speaker="caller",
            text=user_text,
            start_time_ms=0,  # Would be set from actual timing
            end_time_ms=0,
        )
        self.db.add(transcript)

        # Generate response
        response_text = await self.generate_response(user_text)

        logger.info(
            "Agent response generated",
            call_id=str(self.call.id),
            text=response_text,
        )

        # Save agent transcript
        agent_transcript = CallTranscript(
            call_id=self.call.id,
            speaker="agent",
            text=response_text,
            start_time_ms=0,
            end_time_ms=0,
        )
        self.db.add(agent_transcript)

        await self.db.commit()

        # Update call metrics
        self.call.agent_response_count = self.state.response_count

        # Stream synthesized speech
        async for audio_chunk in self.synthesize_speech(response_text):
            yield audio_chunk

    async def get_greeting(self) -> AsyncGenerator[bytes, None]:
        """Get the greeting message as audio."""
        greeting = self.config.greeting_message
        async for chunk in self.synthesize_speech(greeting):
            yield chunk

    async def cleanup(self) -> None:
        """Clean up session state."""
        self.state.is_active = False
        await self.db.commit()


class VoicePipelineManager:
    """Manager for voice pipeline sessions."""

    def __init__(self) -> None:
        self._sessions: dict[uuid.UUID, VoicePipeline] = {}

    async def create_session(
        self,
        db: AsyncSession,
        tenant_config: TenantConfig,
        call: Call,
    ) -> VoicePipeline:
        """Create a new voice pipeline session."""
        pipeline = VoicePipeline(db, tenant_config, call)
        self._sessions[call.id] = pipeline
        return pipeline

    def get_session(self, call_id: uuid.UUID) -> VoicePipeline | None:
        """Get an existing session."""
        return self._sessions.get(call_id)

    async def end_session(self, call_id: uuid.UUID) -> None:
        """End and cleanup a session."""
        pipeline = self._sessions.pop(call_id, None)
        if pipeline:
            await pipeline.cleanup()


# Global pipeline manager
pipeline_manager = VoicePipelineManager()
