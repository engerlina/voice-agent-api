"""Voice AI pipeline orchestrator (STT -> LLM -> TTS) with multilingual support."""

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
from app.services.rag_service import RAGService

logger = get_logger(__name__)


# =============================================================================
# MULTILINGUAL CONFIGURATION
# Common languages in Australia + global support
# =============================================================================

# Deepgram language codes
# See: https://developers.deepgram.com/docs/models-languages-overview
DEEPGRAM_LANGUAGES = {
    "en": "en-AU",      # English (Australian)
    "en-au": "en-AU",   # English (Australian)
    "en-us": "en-US",   # English (US)
    "en-gb": "en-GB",   # English (UK)
    "zh": "zh-CN",      # Mandarin Chinese (Simplified)
    "zh-cn": "zh-CN",   # Mandarin Chinese (Simplified)
    "zh-tw": "zh-TW",   # Mandarin Chinese (Traditional)
    "yue": "zh-CN",     # Cantonese (falls back to Mandarin - Deepgram limitation)
    "vi": "vi",         # Vietnamese
    "ar": "ar",         # Arabic
    "el": "el",         # Greek
    "it": "it",         # Italian
    "hi": "hi",         # Hindi
    "tl": "tl",         # Tagalog/Filipino
    "es": "es",         # Spanish
    "ko": "ko",         # Korean
    "ja": "ja",         # Japanese
    "fr": "fr",         # French
    "de": "de",         # German
    "pt": "pt-BR",      # Portuguese (Brazilian)
    "auto": None,       # Auto-detect (Deepgram will detect)
}

# ElevenLabs multilingual voices
# Using eleven_multilingual_v2 model for non-English languages
ELEVENLABS_VOICES = {
    # Default/English voices
    "en": {
        "voice_id": "21m00Tcm4TlvDq8ikWAM",  # Rachel - natural English
        "model": "eleven_turbo_v2",
    },
    # Multilingual voices (use multilingual model)
    "zh": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",  # Nicole - multilingual
        "model": "eleven_multilingual_v2",
    },
    "yue": {  # Cantonese
        "voice_id": "ThT5KcBeYPX3keUQqHPh",  # Nicole - multilingual
        "model": "eleven_multilingual_v2",
    },
    "vi": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",  # Nicole - multilingual
        "model": "eleven_multilingual_v2",
    },
    "ar": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
    "el": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
    "it": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
    "hi": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
    "tl": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
    "es": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
    "ko": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
    "ja": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
    "fr": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
    "de": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
    "pt": {
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "model": "eleven_multilingual_v2",
    },
}

# Language names for system prompts
LANGUAGE_NAMES = {
    "en": "English",
    "zh": "Mandarin Chinese",
    "yue": "Cantonese",
    "vi": "Vietnamese",
    "ar": "Arabic",
    "el": "Greek",
    "it": "Italian",
    "hi": "Hindi",
    "tl": "Tagalog",
    "es": "Spanish",
    "ko": "Korean",
    "ja": "Japanese",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
}


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
    detected_language: str | None = None  # For auto-detect mode


class VoicePipeline:
    """Orchestrates the voice AI pipeline for a call session with multilingual support."""

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

        # Language configuration
        self.language = getattr(self.config, "language", "en") or "en"
        self.auto_detect = getattr(self.config, "auto_detect_language", False)

    def _get_deepgram_language(self) -> str | None:
        """Get Deepgram language code for STT."""
        if self.auto_detect:
            return None  # Deepgram will auto-detect

        # Use detected language from previous turn if available
        lang = self.state.detected_language or self.language
        return DEEPGRAM_LANGUAGES.get(lang, DEEPGRAM_LANGUAGES.get("en"))

    def _get_elevenlabs_config(self) -> dict:
        """Get ElevenLabs voice and model configuration."""
        lang = self.state.detected_language or self.language

        # Use custom voice_id if set in tenant config
        if self.config.voice_id:
            # For custom voice, determine model based on language
            is_english = lang.startswith("en")
            return {
                "voice_id": self.config.voice_id,
                "model": "eleven_turbo_v2" if is_english else "eleven_multilingual_v2",
            }

        # Use default voice for language
        config = ELEVENLABS_VOICES.get(lang, ELEVENLABS_VOICES["en"])
        return config

    def _build_system_prompt(self, context: str = "") -> str:
        """Build the system prompt with tenant config, RAG context, and language instructions."""
        base_prompt = self.config.system_prompt or (
            "You are a helpful voice assistant. Be concise and conversational. "
            "Keep responses brief (1-2 sentences) unless more detail is needed."
        )

        # Add language instruction for non-English
        lang = self.state.detected_language or self.language
        if lang != "en" and not lang.startswith("en"):
            lang_name = LANGUAGE_NAMES.get(lang, lang)
            language_instruction = (
                f"\n\nIMPORTANT: The caller is speaking {lang_name}. "
                f"You MUST respond in {lang_name}. Be natural and fluent."
            )
            base_prompt = base_prompt + language_instruction

        if context:
            return f"""{base_prompt}

Use the following information to help answer questions:

{context}

Remember to be conversational and concise in your responses."""

        return base_prompt

    async def transcribe_audio(self, audio_data: bytes) -> str:
        """Transcribe audio using Deepgram with multilingual support."""
        try:
            deepgram_lang = self._get_deepgram_language()

            options = PrerecordedOptions(
                model="nova-2",
                smart_format=True,
                punctuate=True,
                diarize=False,
                language=deepgram_lang,
                detect_language=self.auto_detect,
            )

            response = await self.deepgram.listen.asyncrest.v1.transcribe_file(
                {"buffer": audio_data, "mimetype": "audio/webm"},
                options,
            )

            result = response.results.channels[0]
            transcript = result.alternatives[0].transcript

            # Store detected language for subsequent responses
            if self.auto_detect and hasattr(result, "detected_language"):
                detected = result.detected_language
                if detected:
                    self.state.detected_language = detected
                    logger.info(
                        "Language detected",
                        call_id=str(self.call.id),
                        detected_language=detected,
                    )

            return transcript

        except Exception as e:
            logger.error("Transcription failed", error=str(e))
            return ""

    async def generate_response(self, user_message: str) -> str:
        """Generate LLM response with RAG context and language awareness."""
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
            # Return error in configured language
            lang = self.state.detected_language or self.language
            if lang == "zh":
                return "对不起，我在处理您的请求时遇到了问题。请您再说一遍好吗？"
            elif lang == "vi":
                return "Xin lỗi, tôi gặp khó khăn khi xử lý yêu cầu của bạn. Bạn có thể nhắc lại được không?"
            elif lang == "ar":
                return "أنا آسف، أواجه مشكلة في معالجة طلبك. هل يمكنك إعادة ذلك من فضلك؟"
            elif lang == "es":
                return "Lo siento, tengo problemas para procesar tu solicitud. ¿Podrías repetirlo?"
            return "I'm sorry, I'm having trouble processing your request. Could you please repeat that?"

    async def synthesize_speech(self, text: str) -> AsyncGenerator[bytes, None]:
        """Synthesize speech using ElevenLabs with multilingual support."""
        voice_config = self._get_elevenlabs_config()
        voice_id = voice_config["voice_id"]
        model = voice_config["model"]

        try:
            audio_stream = await self.elevenlabs.generate(
                text=text,
                voice=voice_id,
                model=model,
                stream=True,
            )

            async for chunk in audio_stream:
                yield chunk

        except Exception as e:
            logger.error(
                "Speech synthesis failed",
                error=str(e),
                voice_id=voice_id,
                model=model,
            )
            # Return empty audio or fallback

    async def process_speech_turn(self, audio_data: bytes) -> AsyncGenerator[bytes, None]:
        """Process a complete speech turn: STT -> LLM -> TTS."""
        # Transcribe user speech
        user_text = await self.transcribe_audio(audio_data)

        if not user_text.strip():
            return

        lang = self.state.detected_language or self.language
        logger.info(
            "User speech transcribed",
            call_id=str(self.call.id),
            text=user_text,
            language=lang,
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
            language=lang,
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
