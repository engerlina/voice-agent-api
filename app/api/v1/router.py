"""API v1 router - combines all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, checkout, customers, esim, health, orders, plans, support, voice, webhooks

api_router = APIRouter()

# Authentication
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# Core Trvel eSIM endpoints
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(customers.router, prefix="/customers", tags=["Customers"])
api_router.include_router(orders.router, prefix="/orders", tags=["Orders"])
api_router.include_router(plans.router, prefix="/plans", tags=["Plans"])
api_router.include_router(checkout.router, prefix="/checkout", tags=["Checkout"])
api_router.include_router(support.router, prefix="/support", tags=["Support"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
api_router.include_router(esim.router, prefix="/esim", tags=["eSIM"])

# Voice Agent endpoints
api_router.include_router(voice.router, prefix="/voice", tags=["Voice Agent"])
