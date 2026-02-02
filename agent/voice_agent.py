"""LiveKit Voice Agent - handles incoming calls with AI voice assistant."""

import os
import asyncio
from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, openai, silero, elevenlabs

load_dotenv()


async def entrypoint(ctx: JobContext):
    """Main entrypoint for the voice agent."""

    # Wait for a participant to connect
    await ctx.connect()

    # Get room metadata for context
    room_metadata = ctx.room.metadata or ""
    participant = await ctx.wait_for_participant()

    print(f"Participant joined: {participant.identity}")
    print(f"Room: {ctx.room.name}, Metadata: {room_metadata}")

    # Configure the voice assistant
    initial_ctx = openai.llm.ChatContext().append(
        role="system",
        text="""You are a helpful AI voice assistant. You are friendly, professional, and concise.

Key behaviors:
- Keep responses brief and conversational (1-2 sentences when possible)
- Be helpful and answer questions directly
- If you don't know something, say so honestly
- For appointments or bookings, collect the necessary information step by step
- Always confirm important details before ending the call

You are currently handling a phone call. The caller has just connected.""",
    )

    # Create the voice assistant with STT, LLM, and TTS
    assistant = VoiceAssistant(
        vad=silero.VAD.load(),  # Voice Activity Detection
        stt=deepgram.STT(
            model="nova-2",
            language="en",
        ),
        llm=openai.LLM(
            model=os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview"),
            temperature=0.7,
        ),
        tts=elevenlabs.TTS(
            voice_id=os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
            model_id="eleven_turbo_v2",
        ),
        chat_ctx=initial_ctx,
    )

    # Start the assistant
    assistant.start(ctx.room, participant)

    # Greet the caller
    await assistant.say(
        "Hello! Thank you for calling. I'm your AI voice assistant. How can I help you today?",
        allow_interruptions=True,
    )


def main():
    """Run the voice agent worker."""
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            # Agent will handle SIP calls
            api_key=os.getenv("LIVEKIT_API_KEY"),
            api_secret=os.getenv("LIVEKIT_API_SECRET"),
            ws_url=os.getenv("LIVEKIT_URL"),
        )
    )


if __name__ == "__main__":
    main()
