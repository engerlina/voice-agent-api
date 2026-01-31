"""Trvel FastAPI Application - Premium eSIM Provider for Australian Travelers.

This is the main entry point for the Trvel API.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import init_db
from app.core.logging import logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    setup_logging()
    logger.info("Starting Trvel API", version="1.0.0", env=settings.app_env)

    # Initialize database (create tables if needed)
    await init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
    logger.info("Shutting down Trvel API")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="""
## Trvel eSIM API

Premium travel eSIM provider for Australian travelers.

### Key Features
- **Instant QR Delivery**: eSIM QR codes delivered within seconds of payment
- **Multi-Channel Delivery**: Email → SMS → WhatsApp fallback
- **10-Minute Guarantee**: Automatic refund if customer can't connect
- **AI-Powered Support**: Intelligent support triage with 3-minute response SLA
- **Global Coverage**: 190+ destinations worldwide

### SLA Guarantees
- QR Code Delivery: < 30 seconds
- Support First Response: < 3 minutes
- Connection Guarantee: 10 minutes or full refund

### Authentication
All endpoints require API key authentication via `x-api-key` header.
    """,
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://trvel.co",
        "https://www.trvel.co",
        "https://app.trvel.co",
        "https://voice-agent-dashboard-jade.vercel.app",
        "https://voice-agent-dashboard.vercel.app",
        "http://localhost:3000",  # Development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )

    # Don't expose internal errors in production
    if settings.is_production:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )


# Include API router
app.include_router(api_router, prefix=settings.api_v1_prefix)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint - basic API info."""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "operational",
        "docs": f"{settings.api_v1_prefix}/docs" if settings.debug else None,
    }


# Simple health check for Railway (no DB required)
@app.get("/health")
async def health():
    """Simple health check for load balancer."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
