"""Health check endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    timestamp: str
    version: str
    database: str


@router.get("", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Health check endpoint.

    Verifies API is running and database is connected.
    """
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version="1.0.0",
        database=db_status,
    )


@router.get("/ready")
async def readiness_check() -> dict:
    """Readiness check for Kubernetes/Docker."""
    return {"ready": True}


@router.get("/live")
async def liveness_check() -> dict:
    """Liveness check for Kubernetes/Docker."""
    return {"alive": True}
