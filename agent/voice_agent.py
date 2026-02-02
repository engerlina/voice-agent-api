"""LiveKit Voice Agent - handles incoming calls with AI voice assistant.

This agent fetches tenant-specific settings from the API to customize
the voice, LLM model, and behavior per user.
"""

import json
import os
from typing import Optional

import httpx
from dotenv import load_dotenv

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, openai, silero, elevenlabs

load_dotenv()

# API base URL for fetching tenant settings
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


async def fetch_tenant_settings(user_id: str) -> dict:
    """Fetch tenant settings from the API."""
    if not user_id:
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/api/v1/settings/agent/{user_id}",
                timeout=5.0,
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        print(f"Error fetching tenant settings: {e}")

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


async def entrypoint(ctx: JobContext):
    """Main entrypoint for the voice agent."""

    # Connect to the room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for a participant (the caller)
    participant = await ctx.wait_for_participant()

    print(f"Participant joined: {participant.identity}")
    print(f"Room: {ctx.room.name}")

    # Parse room metadata to get user_id
    user_id = None
    room_metadata = {}
    if ctx.room.metadata:
        try:
            room_metadata = json.loads(ctx.room.metadata)
            user_id = room_metadata.get("user_id")
            print(f"User ID from room metadata: {user_id}")
        except json.JSONDecodeError:
            print(f"Could not parse room metadata: {ctx.room.metadata}")

    # Fetch tenant-specific settings
    settings = await fetch_tenant_settings(user_id) if user_id else None

    # Use tenant settings or defaults
    if settings:
        print(f"Using tenant settings for user: {user_id}")
        instructions = settings.get("system_prompt") or get_default_instructions()
        welcome_message = settings.get("welcome_message", "Hello! How can I help you today?")
        voice_id = settings.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        llm_model = settings.get("llm_model", "gpt-4o-mini")
    else:
        print("Using default settings (no tenant settings found)")
        instructions = get_default_instructions()
        welcome_message = "Hello! Thank you for calling. I'm your AI voice assistant. How can I help you today?"
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        llm_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    print(f"LLM Model: {llm_model}")
    print(f"Voice ID: {voice_id}")

    # Create the agent with tenant-specific settings
    agent = Agent(
        instructions=instructions,
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=openai.LLM(model=llm_model),
        tts=elevenlabs.TTS(voice_id=voice_id),
    )

    # Start the agent session
    session = AgentSession()
    await session.start(agent, room=ctx.room)

    # Greet the caller with tenant-specific welcome message
    await session.say(welcome_message)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=os.getenv("LIVEKIT_API_KEY"),
            api_secret=os.getenv("LIVEKIT_API_SECRET"),
            ws_url=os.getenv("LIVEKIT_URL"),
        )
    )
