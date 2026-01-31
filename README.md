# Voice Agent Platform

Multi-tenant Voice AI Platform with LiveKit, RAG, and Telephony Integration.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            Railway Project                               │
├─────────────────┬─────────────────┬─────────────┬─────────────┬─────────┤
│   FastAPI API   │  LiveKit Server │  Postgres   │    Redis    │  Worker │
│                 │                 │  (pgvector) │             │         │
│  - Auth/Tenants │  - WebRTC Media │  - Users    │  - Sessions │  - Docs │
│  - Calls CRUD   │  - Room Control │  - Calls    │  - Cache    │  - RAG  │
│  - RAG Search   │  - SIP Bridge   │  - Vectors  │  - Queues   │         │
│  - Webhooks     │                 │             │             │         │
└────────┬────────┴────────┬────────┴──────┬──────┴──────┬──────┴─────────┘
         │                 │               │             │
         ▼                 ▼               │             │
    ┌─────────┐      ┌──────────┐         │             │
    │ Twilio  │      │ Callers  │         │             │
    │ SIP     │◄────►│ (PSTN)   │         │             │
    └─────────┘      └──────────┘         │             │
                                          │             │
    ┌─────────────────────────────────────┴─────────────┘
    │              External Services
    ├─────────────┬─────────────┬─────────────┐
    │   OpenAI    │  Deepgram   │ ElevenLabs  │
    │   (LLM)     │   (STT)     │   (TTS)     │
    └─────────────┴─────────────┴─────────────┘
```

## Features

- **Multi-Tenancy**: Full tenant isolation with role-based access control
- **Voice AI Pipeline**: STT → LLM → TTS with streaming support
- **RAG Integration**: Document upload, chunking, and vector search with pgvector
- **Real-Time Communication**: LiveKit for WebRTC voice handling
- **Telephony**: Twilio/SIP integration for PSTN calls
- **Session Management**: Redis-backed call state and rate limiting

## Project Structure

```
app/
├── api/
│   ├── deps.py           # Auth & tenant dependencies
│   └── v1/
│       └── routes/
│           ├── auth.py       # Login, signup, token refresh
│           ├── tenants.py    # Tenant management
│           ├── users.py      # User management
│           ├── calls.py      # Call CRUD & initiation
│           ├── documents.py  # Document upload & RAG search
│           └── webhooks.py   # Twilio & LiveKit webhooks
├── core/
│   ├── config.py         # Settings from env vars
│   └── logging.py        # Structured logging
├── db/
│   ├── base.py           # SQLAlchemy base & mixins
│   └── session.py        # Async session management
├── models/
│   ├── tenant.py         # Tenant & TenantConfig
│   ├── user.py           # User & UserTenant
│   ├── call.py           # Call, CallEvent, CallTranscript
│   └── document.py       # Document & DocumentChunk (vectors)
├── schemas/              # Pydantic request/response models
├── services/
│   ├── auth.py           # JWT & password handling
│   ├── redis.py          # Session state & caching
│   ├── livekit.py        # LiveKit room management
│   ├── rag.py            # Document processing & search
│   └── voice_pipeline.py # STT/LLM/TTS orchestration
├── worker/
│   ├── livekit_agent.py      # LiveKit voice agent
│   └── document_processor.py # Async document ingestion
└── main.py               # FastAPI app factory
```

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Docker & Docker Compose
- API keys for: OpenAI, Deepgram, ElevenLabs, Twilio

### 2. Local Development

```bash
# Clone and setup
cd voice-agent-platform
cp .env.example .env
# Edit .env with your API keys

# Start services with Docker Compose
docker-compose up -d

# Run migrations
docker-compose exec api alembic upgrade head

# API is now available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

### 3. Create Your First Tenant

```bash
# Sign up (creates user + tenant)
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@clinic.com",
    "password": "securepassword",
    "full_name": "Admin User",
    "tenant_name": "My Clinic"
  }'

# Response includes access_token for subsequent requests
```

### 4. Upload Documents for RAG

```bash
# Get token from signup/login response
TOKEN="your-access-token"

# Upload a document
curl -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Services FAQ",
    "content": "We offer general checkups, vaccinations, and lab work..."
  }'
```

## Railway Deployment

### 1. Create Railway Project

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and create project
railway login
railway init
```

### 2. Add Services

1. **API Service**: Deploy from GitHub repo
2. **Postgres**: Add PostgreSQL plugin (enable pgvector)
3. **Redis**: Add Redis plugin
4. **LiveKit**: Deploy livekit/livekit-server container

### 3. Configure Environment

Set these variables in Railway dashboard:

```
# App
SECRET_KEY=<generate-secure-key>
APP_ENV=production

# Database (auto-populated by Railway)
DATABASE_URL=${{Postgres.DATABASE_URL}}

# Redis (auto-populated by Railway)
REDIS_URL=${{Redis.REDIS_URL}}

# LiveKit
LIVEKIT_URL=wss://your-livekit.railway.app
LIVEKIT_API_KEY=<your-key>
LIVEKIT_API_SECRET=<your-secret>

# AI Services
OPENAI_API_KEY=sk-...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...

# Twilio
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...
```

### 4. Deploy

```bash
railway up
```

## API Endpoints

### Authentication
- `POST /api/v1/auth/signup` - Register user & create tenant
- `POST /api/v1/auth/login` - Get access token
- `POST /api/v1/auth/refresh` - Refresh token
- `GET /api/v1/auth/me` - Get current user

### Tenants
- `GET /api/v1/tenants/` - List user's tenants
- `GET /api/v1/tenants/current` - Get current tenant
- `PATCH /api/v1/tenants/current` - Update tenant
- `GET /api/v1/tenants/current/config` - Get tenant config
- `PATCH /api/v1/tenants/current/config` - Update config

### Calls
- `GET /api/v1/calls/` - List calls (paginated)
- `GET /api/v1/calls/{id}` - Get call details with transcripts
- `POST /api/v1/calls/` - Initiate outbound call
- `POST /api/v1/calls/{id}/end` - End active call

### Documents
- `GET /api/v1/documents/` - List documents
- `POST /api/v1/documents/` - Create from text
- `POST /api/v1/documents/upload` - Upload file
- `POST /api/v1/documents/search` - RAG vector search
- `DELETE /api/v1/documents/{id}` - Delete document

### Webhooks
- `POST /api/v1/webhooks/twilio/voice` - Twilio voice events
- `POST /api/v1/webhooks/twilio/status` - Twilio status callbacks
- `POST /api/v1/webhooks/livekit/room` - LiveKit room events

## Configuration

### Tenant Config Options

```json
{
  "business_hours": {
    "monday": {"open": "09:00", "close": "17:00"},
    "saturday": null
  },
  "timezone": "America/New_York",
  "system_prompt": "You are a helpful assistant for...",
  "greeting_message": "Hello! How can I help?",
  "voice_id": "elevenlabs-voice-id",
  "llm_model": "gpt-4-turbo-preview",
  "temperature": 0.7,
  "transfer_number": "+1234567890",
  "rag_enabled": true,
  "rag_top_k": 5,
  "rag_similarity_threshold": 0.7
}
```

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# With coverage
pytest --cov=app
```

### Code Quality

```bash
# Lint
ruff check app/

# Type check
mypy app/
```

## License

MIT
# Trigger redeploy
