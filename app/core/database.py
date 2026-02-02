"""Database connection and session management."""

from typing import AsyncGenerator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class."""

    pass


# Query parameters that Supabase adds but asyncpg doesn't support
UNSUPPORTED_PARAMS = {"connection_limit", "pool_timeout", "pgbouncer", "statement_cache_size"}


def get_async_database_url(url: str) -> str:
    """Convert database URL to async-compatible format for asyncpg."""
    # Parse the URL
    parsed = urlparse(url)

    # Convert scheme to asyncpg
    scheme = parsed.scheme
    if scheme in ("postgresql", "postgres"):
        scheme = "postgresql+asyncpg"

    # Filter out unsupported query parameters
    if parsed.query:
        params = parse_qs(parsed.query)
        filtered_params = {k: v for k, v in params.items() if k not in UNSUPPORTED_PARAMS}
        query = urlencode(filtered_params, doseq=True)
    else:
        query = ""

    # Reconstruct URL
    return urlunparse((
        scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        query,
        parsed.fragment,
    ))


engine = create_async_engine(
    get_async_database_url(settings.database_url),
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables and run migrations."""
    import subprocess
    import sys
    from sqlalchemy import text

    # Run Alembic migrations
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            print(f"Alembic migrations completed: {result.stdout}")
        else:
            print(f"Alembic migration warning: {result.stderr}")
    except Exception as e:
        print(f"Could not run Alembic migrations: {e}")

    async with engine.begin() as conn:
        # Create tables if they don't exist (fallback)
        await conn.run_sync(Base.metadata.create_all)

        # Add is_admin column to users table if it doesn't exist
        try:
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE"
            ))
        except Exception:
            # Column might already exist or DB doesn't support IF NOT EXISTS
            pass

        # Ensure stt_provider column exists in tenant_settings
        try:
            await conn.execute(text(
                "ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS stt_provider VARCHAR(50) DEFAULT 'deepgram' NOT NULL"
            ))
        except Exception:
            # Column might already exist
            pass
