"""LiveKit Voice Agent - handles incoming calls with AI voice assistant."""

import os
from dotenv import load_dotenv

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, openai, silero, elevenlabs

load_dotenv()


async def entrypoint(ctx: JobContext):
    """Main entrypoint for the voice agent."""

    # Connect to the room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for a participant (the caller)
    participant = await ctx.wait_for_participant()

    print(f"Participant joined: {participant.identity}")
    print(f"Room: {ctx.room.name}")

    # Create the agent with model settings
    agent = Agent(
        instructions="""You are a helpful AI voice assistant. You are friendly, professional, and concise.

Key behaviors:
- Keep responses brief and conversational (1-2 sentences when possible)
- Be helpful and answer questions directly
- If you don't know something, say so honestly
- For appointments or bookings, collect the necessary information step by step
- Always confirm important details before ending the call

You are currently handling a phone call. The caller has just connected.""",
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=openai.LLM(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        ),
        tts=elevenlabs.TTS(
            voice_id=os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
        ),
    )

    # Start the agent session
    session = AgentSession()
    await session.start(agent, room=ctx.room)

    # Greet the caller
    await session.say(
        "Hello! Thank you for calling. I'm your AI voice assistant. How can I help you today?"
    )


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=os.getenv("LIVEKIT_API_KEY"),
            api_secret=os.getenv("LIVEKIT_API_SECRET"),
            ws_url=os.getenv("LIVEKIT_URL"),
        )
    )
