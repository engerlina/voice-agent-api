"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Any, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Trvel API"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "change-me-in-production"

    # Database (Supabase PostgreSQL)
    database_url: str = "postgresql+asyncpg://localhost:5432/trvel"
    database_pool_size: int = 20

    # Redis (for voice agent session state)
    redis_url: str = "redis://localhost:6379/0"

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    test_stripe_secret_key: str = ""
    test_stripe_webhook_secret: str = ""
    test_mode: bool = False

    # Website URLs (for Stripe redirects)
    website_url: str = "https://trvel.co"

    # API Base URL (for SMS QR code links)
    api_base_url: str = "https://trvel-fastapi-production.up.railway.app"

    # eSIM Go
    esimgo_api_key: str = ""

    # Email (Resend)
    resend_api_key: str = ""
    resend_from_email: str = "hello@trvel.co"
    resend_from_name: str = "Trvel"

    # SMS (Twilio) - Used for both eSIM and Voice
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Telegram (Alerts)
    telegram_bot_token: str = ""
    telegram_alerts_chat_id: str = ""
    telegram_support_chat_id: str = ""

    # AI Services
    openai_api_key: str = ""
    openai_model: str = "gpt-4-turbo-preview"
    openai_embedding_model: str = "text-embedding-3-small"
    anthropic_api_key: str = ""

    # LiveKit (Voice Agent)
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_sip_uri: str = ""  # SIP trunk domain for Twilio→LiveKit (e.g., "sip.livekit.cloud")

    # Deepgram (STT for Voice Agent)
    deepgram_api_key: str = ""

    # ElevenLabs (TTS for Voice Agent)
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    # Vector Store (RAG)
    vector_store_type: str = "pgvector"
    pinecone_api_key: str | None = None
    pinecone_environment: str | None = None
    pinecone_index: str | None = None

    # JWT Settings (for voice agent auth)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Rate Limiting
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # API Authentication
    api_key_header: str = "x-api-key"
    api_keys: str = ""  # Comma-separated list

    # SLA Configuration (critical for Trvel)
    sla_qr_delivery_seconds: int = 30
    sla_support_response_minutes: int = 3
    sla_connection_guarantee_minutes: int = 10

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [v]
        return v

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.app_env.lower() == "production"

    @property
    def async_database_url(self) -> str:
        """Get async database URL for SQLAlchemy."""
        url = str(self.database_url)
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def valid_api_keys(self) -> List[str]:
        """Get list of valid API keys."""
        if not self.api_keys:
            return []
        return [key.strip() for key in self.api_keys.split(",") if key.strip()]

    @property
    def active_stripe_secret_key(self) -> str:
        """Get the active Stripe key based on test mode."""
        if self.test_mode and self.test_stripe_secret_key:
            return self.test_stripe_secret_key
        return self.stripe_secret_key

    @property
    def active_stripe_webhook_secret(self) -> str:
        """Get the active Stripe webhook secret based on test mode."""
        if self.test_mode and self.test_stripe_webhook_secret:
            return self.test_stripe_webhook_secret
        return self.stripe_webhook_secret

    @property
    def voice_agent_enabled(self) -> bool:
        """Check if voice agent is configured."""
        return bool(self.livekit_url and self.livekit_api_key and self.deepgram_api_key)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
