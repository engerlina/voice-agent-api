"""Voice Agent API - Inbound Voice Agent Bot with Tool Capabilities.

This is the main entry point for the Voice Agent API.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import init_db
from app.core.logging import logger, setup_logging

# Allowed CORS origins
CORS_ORIGINS = [
    "https://voice-agent-dashboard-jade.vercel.app",
    "https://voice-agent-dashboard.vercel.app",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://localhost:3003",
    "http://localhost:3004",
    "http://localhost:3005",
]


def get_cors_headers(request: Request) -> dict:
    """Get CORS headers based on request origin."""
    origin = request.headers.get("origin", "")
    if origin in CORS_ORIGINS:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        }
    return {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    setup_logging()
    logger.info("Starting Voice Agent API", version="1.0.0", env=settings.app_env)

    # Initialize database (create tables if needed)
    await init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
    logger.info("Shutting down Voice Agent API")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="""
## Voice Agent API

Inbound Voice Agent Bot with AI-powered conversations and tool capabilities.

### Key Features
- **Inbound Call Handling**: Answer and manage incoming voice calls via Twilio
- **AI-Powered Conversations**: Natural language processing for voice interactions
- **Tool Integration**: Execute actions during calls (send SMS, lookup data, etc.)
- **Phone Number Management**: Search and provision Twilio phone numbers
- **Real-time Transcription**: Live speech-to-text for call handling

### Available Tools
- **Send SMS**: Send text messages to callers or third parties
- **Data Lookup**: Query databases and external APIs during calls
- **Call Transfer**: Route calls to appropriate departments or agents
- **Appointment Scheduling**: Book and manage appointments
- **Custom Actions**: Extensible tool framework for business-specific needs

### Authentication
API endpoints require authentication via Bearer token or API key.
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
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# HTTP exception handler (4xx errors)
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with CORS headers."""
    cors_headers = get_cors_headers(request)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=cors_headers,
    )


# Global exception handler (5xx errors)
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

    # Get CORS headers for the response
    cors_headers = get_cors_headers(request)

    # Don't expose internal errors in production
    if settings.is_production:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers=cors_headers,
        )

    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers=cors_headers,
    )


# Include API router
app.include_router(api_router, prefix=settings.api_v1_prefix)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint - basic API info."""
    return {
        "name": settings.app_name,
        "version": "1.0.2",
        "status": "operational",
        "docs": f"{settings.api_v1_prefix}/docs" if settings.debug else None,
        "admin_enabled": True,
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
