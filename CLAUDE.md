# Voice Agent API - Architecture Guide

## Project Overview

Multi-tenant Voice AI Agent API built with FastAPI. Combines eSIM/travel services with AI voice agent capabilities using LiveKit, Twilio, and RAG-powered conversations.

## Quick Start

```bash
# Install dependencies
pip install -e .

# Set environment variables (see Configuration section)
cp .env.example .env

# Run locally
uvicorn app.main:app --reload

# Run with Docker
docker-compose up
```

## Project Structure

```
app/
├── api/v1/
│   ├── endpoints/           # Route handlers by domain
│   │   ├── auth.py          # Authentication (signup, login, refresh)
│   │   ├── voice.py         # Voice agent (calls, documents, LiveKit)
│   │   ├── settings.py      # User/tenant settings
│   │   ├── admin.py         # Admin operations
│   │   ├── webhooks.py      # Twilio/LiveKit webhooks
│   │   └── health.py        # Health checks
│   └── router.py            # Route aggregation
├── core/
│   ├── config.py            # Pydantic settings
│   ├── database.py          # SQLAlchemy async engine
│   ├── logging.py           # Structured logging (structlog)
│   └── security.py          # JWT, password hashing
├── db/
│   └── base.py              # SQLAlchemy Base, mixins
├── models/                   # SQLAlchemy ORM models
├── schemas/                  # Pydantic request/response DTOs
├── services/                 # Business logic
│   ├── voice_pipeline.py    # STT → LLM → TTS orchestration
│   ├── rag_service.py       # Document processing, vector search
│   ├── livekit_service.py   # Room/token management
│   └── redis_service.py     # Session state, caching
├── main.py                   # FastAPI app factory
alembic/                      # Database migrations
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI (async) |
| Database | PostgreSQL + pgvector |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Cache | Redis |
| Voice/WebRTC | LiveKit |
| Telephony | Twilio SIP |
| STT | Deepgram |
| TTS | ElevenLabs |
| LLM | OpenAI / Anthropic |
| Embeddings | OpenAI text-embedding-3-small |

## Voice Pipeline Architecture

```
Caller (PSTN)
    ↓
Twilio SIP Trunk → POST /api/v1/webhooks/twilio/voice
    ↓
LiveKit Room (WebRTC bridge)
    ↓
VoicePipeline:
  1. Audio → Deepgram STT → text
  2. RAG context lookup (pgvector)
  3. LLM response (OpenAI/Anthropic)
  4. ElevenLabs TTS → audio stream
    ↓
LiveKit → Caller
```

## Database Models

### Core Entities

- **User** - Authentication, belongs to tenant
- **Tenant** - Organization/clinic with config
- **TenantConfig** - Org-level AI settings (prompts, RAG)
- **TenantSettings** - User-level preferences (voice, model)

### Voice Entities

- **Call** - Call record with status, timing, metrics
- **CallEvent** - Audit trail of call events
- **CallTranscript** - Speaker turns with timestamps

### RAG Entities

- **Document** - Knowledge base documents
- **DocumentChunk** - Chunks with pgvector embeddings (1536 dims)

### Telephony

- **PhoneNumber** - Twilio numbers assigned to users

## Multi-Tenancy

All tenant-scoped models use `TenantMixin` which adds:
- `tenant_id: UUID` foreign key with CASCADE delete
- Index for query performance

**Important**: Always filter queries by `tenant_id` for data isolation.

## API Patterns

### Authentication
```python
# Get current user in endpoints
@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
```

### Database Sessions
```python
@router.post("/items")
async def create_item(
    data: ItemCreate,
    db: AsyncSession = Depends(get_db)
):
    # Use db session
```

### Error Responses
- 400: Validation errors
- 401: Not authenticated
- 403: Not authorized
- 404: Resource not found
- 500: Internal error (details hidden in production)

## Configuration

Required environment variables:

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Redis
REDIS_URL=redis://localhost:6379

# Auth
SECRET_KEY=your-secret-key-change-in-production
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

# LiveKit
LIVEKIT_URL=wss://your-livekit.livekit.cloud
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret
LIVEKIT_SIP_URI=your-sip-trunk.livekit.cloud  # Required for Twilio→LiveKit calls

# Twilio
TWILIO_ACCOUNT_SID=your-account-sid
TWILIO_AUTH_TOKEN=your-auth-token

# AI Services
OPENAI_API_KEY=your-openai-key
DEEPGRAM_API_KEY=your-deepgram-key
ELEVENLABS_API_KEY=your-elevenlabs-key

# Optional
ANTHROPIC_API_KEY=your-anthropic-key
```

## Code Conventions

### Model Naming
- Use `extra_data` instead of `metadata` (SQLAlchemy reserved)
- UUIDs for all primary keys
- Timestamps via `TimestampMixin`

### Imports
```python
# Models import Base from app.db.base
from app.db.base import Base, TimestampMixin, TenantMixin

# NOT from app.core.database (legacy)
```

### Async Patterns
```python
# Always use async for I/O
async def fetch_data():
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
```

### Error Handling
```python
# Log errors with context
try:
    result = await operation()
except Exception as e:
    logger.error("operation_failed", error=str(e), context=context)
    raise HTTPException(status_code=500, detail="Operation failed")
```

## Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=app --cov-report=html

# Specific test
pytest tests/test_voice.py -v
```

## Deployment

### Railway
- Auto-deploys from GitHub master branch
- Uses `railway.toml` configuration
- Health check at `/health`

### Database Migrations
```bash
# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

**Note**: Migrations run automatically on startup via `init_db()`.

## Common Issues

### Import Errors
If you see `ModuleNotFoundError: No module named 'app.db.base'`:
- Ensure `app/db/__init__.py` exists
- Ensure `app/db/base.py` exists with Base, mixins

### SQLAlchemy Reserved Attributes
Don't use `metadata` as column name - use `extra_data` instead:
```python
extra_data: Mapped[dict | None] = mapped_column("metadata", JSON)
```

### pgvector Extension
Ensure PostgreSQL has pgvector extension:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Security Notes

- Webhook endpoints should verify signatures (Twilio, LiveKit)
- Use `get_current_user` dependency for auth
- Admin checks via `is_admin` flag on User model
- API keys stored in environment variables only
- Passwords hashed with PBKDF2 (100k iterations)

## TODO / Known Limitations

1. Many voice endpoints are incomplete (marked TODO)
2. Call recording not implemented (LiveKit egress)
3. Conversation history stored in-memory (lost on restart)
4. No webhook signature verification
5. No rate limiting middleware
6. Test coverage needed
