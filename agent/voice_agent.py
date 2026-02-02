"""LiveKit Voice Agent - handles incoming calls with AI voice assistant.

This agent fetches tenant-specific settings from the API to customize
the voice, LLM model, and behavior per user. It also records transcripts
of conversations when call_recording_enabled is set.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, openai, silero, elevenlabs

load_dotenv()

# API base URL for fetching tenant settings
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


class CallRecorder:
    """Handles call recording and transcript storage."""

    def __init__(self, api_base_url: str):
        self.api_base_url = api_base_url
        self.call_id: Optional[str] = None
        self.transcripts: list[dict] = []
        self.call_start_time: float = 0
        self.agent_response_count: int = 0

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

        duration = int(time.time() - self.call_start_time) if self.call_start_time else 0

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base_url}/api/v1/calls/internal/{self.call_id}/update",
                    json={
                        "status": "completed",
                        "ended_at": datetime.now(timezone.utc).isoformat(),
                        "duration_seconds": duration,
                        "ended_by": ended_by,
                        "agent_response_count": self.agent_response_count,
                    },
                    timeout=5.0,
                )
                if response.status_code == 200:
                    print(f"Call ended: {self.call_id}, duration: {duration}s")
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
    if settings:
        print(f"Using tenant settings for user: {settings.get('user_id', 'unknown')}")
        instructions = settings.get("system_prompt") or get_default_instructions()
        welcome_message = settings.get("welcome_message", "Hello! How can I help you today?")
        voice_id = settings.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        llm_model = settings.get("llm_model", "gpt-4o-mini")
        call_recording_enabled = settings.get("call_recording_enabled", False)
    else:
        print("Using default settings (no tenant settings found)")
        instructions = get_default_instructions()
        welcome_message = "Hello! Thank you for calling. I'm your AI voice assistant. How can I help you today?"
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        llm_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    print(f"LLM Model: {llm_model}")
    print(f"Voice ID: {voice_id}")
    print(f"Call Recording: {'enabled' if call_recording_enabled else 'disabled'}")

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

    # Create the agent with tenant-specific instructions
    agent = Agent(instructions=instructions)

    # Start the agent session with STT/LLM/TTS configuration
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=openai.LLM(model=llm_model),
        tts=elevenlabs.TTS(voice_id=voice_id),
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
