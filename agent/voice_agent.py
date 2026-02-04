"""LiveKit Voice Agent - handles incoming calls with AI voice assistant.

This agent fetches tenant-specific settings from the API to customize
the voice, LLM model, and behavior per user. It also records transcripts
of conversations when call_recording_enabled is set, and can record
audio to S3 using LiveKit Egress.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

from livekit import api
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, openai, silero, elevenlabs

load_dotenv()

# API base URL for fetching tenant settings
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


class CallRecorder:
    """Handles call recording, transcript storage, and audio egress."""

    def __init__(self, api_base_url: str):
        self.api_base_url = api_base_url
        self.call_id: Optional[str] = None
        self.transcripts: list[dict] = []
        self.call_start_time: float = 0
        self.agent_response_count: int = 0
        self.egress_id: Optional[str] = None
        self.lkapi: Optional[api.LiveKitAPI] = None

    async def create_call(
        self,
        room_name: str,
        call_sid: Optional[str] = None,
        caller_number: Optional[str] = None,
        callee_number: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """Create a call record in the API."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base_url}/api/v1/calls/internal/create",
                    json={
                        "room_name": room_name,
                        "call_sid": call_sid,
                        "caller_number": caller_number,
                        "callee_number": callee_number,
                        "user_id": user_id,
                        "direction": "inbound",
                    },
                    timeout=5.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    self.call_id = data.get("id")
                    self.call_start_time = time.time()
                    print(f"Call record created: {self.call_id}")
                    return self.call_id
        except Exception as e:
            print(f"Error creating call record: {e}")
        return None

    async def start_audio_recording(self, room_name: str) -> Optional[str]:
        """Start LiveKit Egress to record audio to S3."""
        # Check if S3 is configured
        bucket = os.getenv("AWS_S3_BUCKET")
        region = os.getenv("AWS_REGION")
        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

        if not all([bucket, region, access_key, secret_key]):
            print("S3 not configured, skipping audio recording")
            return None

        try:
            # Initialize LiveKit API client
            self.lkapi = api.LiveKitAPI(
                url=os.getenv("LIVEKIT_URL"),
                api_key=os.getenv("LIVEKIT_API_KEY"),
                api_secret=os.getenv("LIVEKIT_API_SECRET"),
            )

            # Generate a unique filepath for the recording
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filepath = f"recordings/{room_name}_{timestamp}.ogg"

            # Create room composite egress request (audio only)
            req = api.RoomCompositeEgressRequest(
                room_name=room_name,
                audio_only=True,
                file_outputs=[
                    api.EncodedFileOutput(
                        file_type=api.EncodedFileType.OGG,
                        filepath=filepath,
                        s3=api.S3Upload(
                            bucket=bucket,
                            region=region,
                            access_key=access_key,
                            secret=secret_key,
                        ),
                    )
                ],
            )

            # Start the egress
            result = await self.lkapi.egress.start_room_composite_egress(req)
            self.egress_id = result.egress_id
            print(f"Audio recording started: egress_id={self.egress_id}, filepath={filepath}")
            return self.egress_id

        except Exception as e:
            print(f"Error starting audio recording: {e}")
            return None

    async def stop_audio_recording(self) -> Optional[str]:
        """Stop LiveKit Egress and return the recording URL."""
        if not self.egress_id or not self.lkapi:
            return None

        try:
            # Stop the egress
            result = await self.lkapi.egress.stop_egress(api.StopEgressRequest(
                egress_id=self.egress_id
            ))

            # Get the recording URL from the result
            recording_url = None
            if result.file_results:
                for file_result in result.file_results:
                    if file_result.location:
                        recording_url = file_result.location
                        break

            print(f"Audio recording stopped: {recording_url}")
            return recording_url

        except Exception as e:
            print(f"Error stopping audio recording: {e}")
            return None
        finally:
            # Clean up the API client
            if self.lkapi:
                await self.lkapi.aclose()
                self.lkapi = None

    def add_transcript(self, speaker: str, text: str, confidence: Optional[float] = None):
        """Add a transcript entry."""
        if not text.strip():
            return

        current_time_ms = int((time.time() - self.call_start_time) * 1000)

        self.transcripts.append({
            "speaker": speaker,
            "text": text.strip(),
            "confidence": confidence,
            "start_time_ms": current_time_ms,
            "end_time_ms": current_time_ms + 100,  # Approximate
        })

        if speaker == "agent":
            self.agent_response_count += 1

        print(f"[{speaker}] {text.strip()}")

    async def save_transcripts(self) -> bool:
        """Save accumulated transcripts to the API."""
        if not self.call_id or not self.transcripts:
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base_url}/api/v1/calls/internal/transcripts",
                    json={
                        "call_id": self.call_id,
                        "entries": self.transcripts,
                    },
                    timeout=5.0,
                )
                if response.status_code == 200:
                    print(f"Saved {len(self.transcripts)} transcript entries")
                    self.transcripts = []  # Clear after saving
                    return True
        except Exception as e:
            print(f"Error saving transcripts: {e}")
        return False

    async def end_call(self, ended_by: str = "caller") -> bool:
        """Mark the call as ended and save final data."""
        if not self.call_id:
            return False

        # Save any remaining transcripts
        await self.save_transcripts()

        # Stop audio recording and get the URL
        recording_url = await self.stop_audio_recording()

        duration = int(time.time() - self.call_start_time) if self.call_start_time else 0

        try:
            update_data = {
                "status": "completed",
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": duration,
                "ended_by": ended_by,
                "agent_response_count": self.agent_response_count,
            }

            # Include recording URL if available
            if recording_url:
                update_data["recording_url"] = recording_url
            if self.egress_id:
                update_data["egress_id"] = self.egress_id

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base_url}/api/v1/calls/internal/{self.call_id}/update",
                    json=update_data,
                    timeout=10.0,  # Increased timeout for egress stop
                )
                if response.status_code == 200:
                    print(f"Call ended: {self.call_id}, duration: {duration}s, recording: {recording_url}")
                    return True
        except Exception as e:
            print(f"Error ending call: {e}")
        return False


async def fetch_tenant_settings_by_user(user_id: str) -> dict:
    """Fetch tenant settings from the API by user_id."""
    if not user_id:
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/api/v1/settings/agent/user/{user_id}",
                timeout=5.0,
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        print(f"Error fetching tenant settings by user_id: {e}")

    return None


async def fetch_tenant_settings_by_phone(phone_number: str) -> dict:
    """Fetch tenant settings from the API by phone number."""
    if not phone_number:
        return None

    try:
        # URL encode the phone number (+ becomes %2B)
        encoded_phone = phone_number.replace("+", "%2B")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/api/v1/settings/agent/by-phone/{encoded_phone}",
                timeout=5.0,
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        print(f"Error fetching tenant settings by phone: {e}")

    return None


def extract_phone_from_participant(identity: str) -> Optional[str]:
    """Extract phone number from participant identity.

    LiveKit SIP participants have identities like 'sip_+61491491560'
    """
    if identity.startswith("sip_"):
        # Extract the phone number after 'sip_'
        phone = identity[4:]  # Remove 'sip_' prefix
        # Normalize to E.164 format if needed
        if phone and not phone.startswith("+"):
            phone = "+" + phone
        return phone
    return None


def get_default_instructions() -> str:
    """Default system instructions for the agent."""
    return """You are a helpful AI voice assistant. You are friendly, professional, and concise.

Key behaviors:
- Keep responses brief and conversational (1-2 sentences when possible)
- Be helpful and answer questions directly
- If you don't know something, say so honestly
- For appointments or bookings, collect the necessary information step by step
- Always confirm important details before ending the call

You are currently handling a phone call. The caller has just connected."""


def extract_sip_number(sip_uri: str) -> Optional[str]:
    """Extract phone number from a SIP URI like 'sip:+61340525699@...'."""
    if not sip_uri:
        return None
    # Handle formats like "sip:+61340525699@domain" or "+61340525699"
    if sip_uri.startswith("sip:"):
        sip_uri = sip_uri[4:]  # Remove 'sip:' prefix
    # Extract number before @ if present
    if "@" in sip_uri:
        sip_uri = sip_uri.split("@")[0]
    # Clean up and normalize
    phone = sip_uri.strip()
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    return phone if phone else None


async def entrypoint(ctx: JobContext):
    """Main entrypoint for the voice agent."""

    # Connect to the room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for a participant (the caller)
    participant = await ctx.wait_for_participant()

    print(f"Participant joined: {participant.identity}")
    print(f"Room: {ctx.room.name}")

    # Debug: Print all available participant attributes
    print(f"Participant attributes: {participant.attributes}")

    # Try to get user_id from room metadata first
    user_id = None
    called_number = None
    caller_number = None
    call_sid = None
    room_metadata = {}

    if ctx.room.metadata:
        try:
            room_metadata = json.loads(ctx.room.metadata)
            user_id = room_metadata.get("user_id")
            called_number = room_metadata.get("to")  # The number that was called
            caller_number = room_metadata.get("from")  # The caller's number
            call_sid = room_metadata.get("call_sid")
            print(f"Room metadata - user_id: {user_id}, to: {called_number}, from: {caller_number}")
        except json.JSONDecodeError:
            print(f"Could not parse room metadata: {ctx.room.metadata}")

    # For SIP calls, extract phone numbers from participant attributes
    # LiveKit SIP provides: sip.phoneNumber (caller), sip.trunkPhoneNumber (called), sip.trunkID, etc.
    attrs = participant.attributes or {}

    # Get the called number (our Twilio number) from SIP attributes
    # sip.trunkPhoneNumber = "Phone number associated with SIP trunk. For inbound trunks, this is the number dialed in to"
    if not called_number:
        sip_trunk_phone = attrs.get("sip.trunkPhoneNumber")
        if sip_trunk_phone:
            called_number = extract_sip_number(sip_trunk_phone)
            print(f"SIP trunkPhoneNumber: {sip_trunk_phone} -> {called_number}")

    # Get the caller number from SIP attributes
    # sip.phoneNumber = "User's phone number. For inbound trunks, this is the phone number the call originates from"
    if not caller_number:
        sip_phone = attrs.get("sip.phoneNumber")
        if sip_phone:
            caller_number = extract_sip_number(sip_phone)
            print(f"SIP phoneNumber: {sip_phone} -> {caller_number}")

    # Fallback: Extract caller number from participant identity
    if not caller_number:
        caller_number = extract_phone_from_participant(participant.identity)

    # Fetch tenant-specific settings
    settings = None

    # Method 1: Try user_id from metadata
    if user_id:
        print(f"Fetching settings by user_id: {user_id}")
        settings = await fetch_tenant_settings_by_user(user_id)

    # Method 2: Try called number from metadata
    if not settings and called_number:
        print(f"Fetching settings by called number: {called_number}")
        settings = await fetch_tenant_settings_by_phone(called_number)

    # Use tenant settings or defaults
    call_recording_enabled = False
    language = "en"
    auto_detect_language = False
    min_silence_duration = 0.4  # Default: faster response time
    if settings:
        # Update user_id from settings if not already set (e.g., when fetched by phone number)
        if not user_id:
            user_id = settings.get("user_id")
        print(f"Using tenant settings for user: {user_id or 'unknown'}")
        instructions = settings.get("system_prompt") or get_default_instructions()
        welcome_message = settings.get("welcome_message", "Hello! How can I help you today?")
        voice_id = settings.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        llm_model = settings.get("llm_model", "gpt-4o-mini")
        call_recording_enabled = settings.get("call_recording_enabled", False)
        language = settings.get("language", "en")
        auto_detect_language = settings.get("auto_detect_language", False)
        min_silence_duration = settings.get("min_silence_duration", 0.4)
    else:
        print("Using default settings (no tenant settings found)")
        instructions = get_default_instructions()
        welcome_message = "Hello! Thank you for calling. I'm your AI voice assistant. How can I help you today?"
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        llm_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    print(f"LLM Model: {llm_model}")
    print(f"Voice ID: {voice_id}")
    print(f"Call Recording: {'enabled' if call_recording_enabled else 'disabled'}")
    print(f"Language: {language}, Auto-detect: {auto_detect_language}")
    print(f"Response speed (min_silence_duration): {min_silence_duration}s")

    # Initialize call recorder
    recorder = CallRecorder(API_BASE_URL)

    # Create call record if recording is enabled
    if call_recording_enabled:
        await recorder.create_call(
            room_name=ctx.room.name,
            call_sid=call_sid,
            caller_number=caller_number,
            callee_number=called_number,
            user_id=user_id,
        )
        # Start audio recording to S3
        await recorder.start_audio_recording(ctx.room.name)

    # Create the agent with tenant-specific instructions
    # Add language instruction to system prompt based on settings
    if auto_detect_language:
        # When auto-detect is enabled, instruct LLM to detect and mirror the caller's language
        instructions = instructions + """

IMPORTANT LANGUAGE INSTRUCTION: You are in multilingual mode.
- Listen carefully to what language the caller is speaking
- ALWAYS respond in the SAME language that the caller uses
- If they speak Mandarin Chinese, respond in Mandarin Chinese
- If they speak Spanish, respond in Spanish
- If they speak any other language, respond in that language
- If you're unsure, continue in the language of their most recent message
- Be natural and fluent in your responses"""
    elif language != "en" and not language.startswith("en"):
        # Specific language configured (not English)
        language_names = {
            "zh": "Mandarin Chinese", "yue": "Cantonese", "vi": "Vietnamese",
            "ar": "Arabic", "el": "Greek", "it": "Italian", "hi": "Hindi",
            "tl": "Tagalog", "es": "Spanish", "ko": "Korean", "ja": "Japanese",
            "fr": "French", "de": "German", "pt": "Portuguese",
        }
        lang_name = language_names.get(language, language)
        instructions = instructions + f"\n\nIMPORTANT: The caller is speaking {lang_name}. You MUST respond in {lang_name}. Be natural and fluent."

    agent = Agent(instructions=instructions)

    # Configure STT based on language settings
    # Use nova-3 with language="multi" for auto-detection, or specific language otherwise
    if auto_detect_language:
        # Multilingual mode: Deepgram nova-3 with language="multi"
        stt_config = deepgram.STT(model="nova-3", language="multi")
        print("STT: Deepgram nova-3 multilingual mode (auto-detect)")
    else:
        # Map language code to Deepgram language format
        deepgram_languages = {
            "en": "en-AU", "en-au": "en-AU", "en-us": "en-US", "en-gb": "en-GB",
            "zh": "zh-CN", "zh-cn": "zh-CN", "zh-tw": "zh-TW", "yue": "zh-CN",
            "vi": "vi", "ar": "ar", "el": "el", "it": "it", "hi": "hi",
            "tl": "tl", "es": "es", "ko": "ko", "ja": "ja", "fr": "fr",
            "de": "de", "pt": "pt-BR",
        }
        stt_language = deepgram_languages.get(language, "en-AU")
        stt_config = deepgram.STT(model="nova-2", language=stt_language)
        print(f"STT: Deepgram nova-2 with language={stt_language}")

    # Configure TTS: use multilingual model for non-English
    is_english = language.startswith("en") and not auto_detect_language
    if is_english:
        tts_config = elevenlabs.TTS(voice_id=voice_id, model="eleven_turbo_v2")
        print("TTS: ElevenLabs turbo_v2 (English)")
    else:
        tts_config = elevenlabs.TTS(voice_id=voice_id, model="eleven_multilingual_v2")
        print("TTS: ElevenLabs multilingual_v2")

    # Configure VAD with response speed settings
    # Lower min_silence_duration = faster response (but may cut off user mid-sentence)
    vad_config = silero.VAD.load(
        min_silence_duration=min_silence_duration,  # Default 0.55s, we use 0.4s for faster response
        min_speech_duration=0.05,  # Minimum speech to start a chunk
    )

    # Start the agent session with STT/LLM/TTS configuration
    session = AgentSession(
        vad=vad_config,
        stt=stt_config,
        llm=openai.LLM(model=llm_model),
        tts=tts_config,
    )

    # Set up transcript capture if recording is enabled
    if call_recording_enabled:
        @session.on("conversation_item_added")
        def on_conversation_item(event):
            """Capture conversation items (user and agent messages)."""
            item = event.item
            role = item.role  # "user" or "assistant"
            text = item.text_content
            if text:
                speaker = "caller" if role == "user" else "agent"
                recorder.add_transcript(speaker, text)

    # Register cleanup callback for when call ends
    if call_recording_enabled:
        async def on_shutdown():
            """Save transcripts and end call when session ends."""
            print("Call ending, saving transcripts...")
            await recorder.end_call(ended_by="caller")

        ctx.add_shutdown_callback(on_shutdown)

    await session.start(agent, room=ctx.room)

    # Greet the caller with tenant-specific welcome message
    # The conversation_item_added event will capture this for transcripts
    await session.say(welcome_message)

    # Session continues running automatically - conversation loop is handled by AgentSession
    # Cleanup happens via ctx.add_shutdown_callback when participant disconnects


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=os.getenv("LIVEKIT_API_KEY"),
            api_secret=os.getenv("LIVEKIT_API_SECRET"),
            ws_url=os.getenv("LIVEKIT_URL"),
        )
    )
