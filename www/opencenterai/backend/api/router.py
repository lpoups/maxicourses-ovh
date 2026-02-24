"""
OpenCenterAI — Route Registration
====================================
Central entry point to attach all API routers to the FastAPI app.
"""

from fastapi import FastAPI

from api.trading import router as trading_router
from api.market import router as market_router
from api.config_api import router as config_router
from api.analytics import router as analytics_router


def register_routes(app: FastAPI) -> None:
    """Mount all API routers with their prefixes and tags."""
    app.include_router(trading_router, prefix="/api/trading", tags=["trading"])
    app.include_router(market_router, prefix="/api/market", tags=["market"])
    app.include_router(config_router, prefix="/api/config", tags=["config"])
    app.include_router(analytics_router, prefix="/api/analytics", tags=["analytics"])
