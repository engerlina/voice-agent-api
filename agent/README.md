# LiveKit Voice Agent

This is the voice AI agent that handles incoming phone calls via LiveKit.

## Architecture

```
Twilio (PSTN) → LiveKit SIP → LiveKit Room → Voice Agent
                                    ↓
                              STT (Deepgram)
                                    ↓
                              LLM (OpenAI)
                                    ↓
                              TTS (ElevenLabs)
                                    ↓
                              Audio → Caller
```

## Setup Options

### Option 1: LiveKit Cloud (Recommended)

1. Create a LiveKit Cloud account at https://cloud.livekit.io
2. Enable SIP in your project settings
3. Deploy the agent:
   ```bash
   lk cloud auth
   lk agent create
   ```
4. Configure Twilio SIP trunk to point to your LiveKit SIP endpoint

### Option 2: Self-Hosted on Railway

For self-hosted LiveKit on Railway, you need:

1. **LiveKit Server** - WebRTC signaling (you have this)
2. **LiveKit SIP** - SIP-to-WebRTC bridge (separate service)
3. **Voice Agent Worker** - This agent

#### Run the Agent Locally

```bash
cd agent
python voice_agent.py dev
```

#### Run with Docker

```bash
docker build -f Dockerfile.agent -t voice-agent .
docker run --env-file .env voice-agent
```

## Environment Variables

Required in `.env`:

```
LIVEKIT_URL=wss://your-livekit.railway.app
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret
OPENAI_API_KEY=your-openai-key
DEEPGRAM_API_KEY=your-deepgram-key
ELEVENLABS_API_KEY=your-elevenlabs-key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
```

## Testing

Use the LiveKit Playground to test:
1. Go to https://agents-playground.livekit.io
2. Connect with your LiveKit credentials
3. Talk to the agent

## Twilio Configuration

Configure your Twilio phone number webhook:
- Voice URL: `https://your-api.railway.app/api/v1/voice/twilio/incoming`
- Method: POST
