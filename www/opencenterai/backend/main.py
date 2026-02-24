"""
OpenCenterAI Trading — FastAPI Application Entry Point
========================================================
Trust Claude, Execute Fast, Log Everything.
"""

import os
import sys
import logging
from contextlib import asynccontextmanager

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env BEFORE any settings import
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import AppSettings, TradingParams
from config.constants import APP_NAME, APP_VERSION
from utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # ── Startup ────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("%s v%s — Starting up", APP_NAME, APP_VERSION)
    logger.info("=" * 60)

    # Load settings from environment (.env already loaded at module level)
    settings = AppSettings.from_env()
    app.state.settings = settings
    logger.info("Settings loaded (IG=%s, DB=%s)", settings.ig_mode, settings.mongo_db)

    # Initialize middleware settings (for verify_auth)
    from api.middleware import init_settings
    init_settings(settings)

    # Initialize MongoDB
    from db.mongo import init_mongo
    db = init_mongo(settings.mongo_uri, settings.mongo_db)
    app.state.db = db
    logger.info("MongoDB initialized")

    # Load trading params from MongoDB
    from db.config_repo import load_trading_params
    params = load_trading_params()
    app.state.params = params
    logger.info("Trading params loaded (mode=%s, enabled=%s)", params.mode, params.enabled)

    # Initialize IG broker client
    from broker.ig_client import IGClient
    ig_client = IGClient(settings)
    app.state.ig_client = ig_client
    logger.info("IG client initialized (mode=%s)", settings.ig_mode)

    # Initialize Prophet (Claude AI)
    from ai.prophet import ProphetEngine
    prophet = ProphetEngine(settings)
    app.state.prophet = prophet
    logger.info("Prophet engine initialized")

    # WebSocket manager — use the MODULE-LEVEL singleton
    # CRITICAL: trading.py imports `from api.websocket import ws_manager`
    # so we MUST use the same instance, otherwise broadcasts go to 0 clients
    from api.websocket import ws_manager
    app.state.ws_manager = ws_manager

    # Start TickCollector — runs independently of trading engine
    # Collects IG prices every 5s, builds MongoDB candles, emits WebSocket updates
    from services.tick_collector import TickCollector
    tick_collector = TickCollector(ig_client=ig_client, ws_manager=ws_manager)
    tick_collector.start()
    app.state.tick_collector = tick_collector
    logger.info("TickCollector started (independent of engine)")

    # Initialize Trading Engine
    from core.engine import TradingEngine
    import db.trade_repo as trade_repo
    import db.config_repo as config_repo
    engine = TradingEngine(
        settings=settings,
        params=params,
        ig_client=ig_client,
        prophet=prophet,
        ws_manager=ws_manager,
        tick_collector=tick_collector,
        trade_repo=trade_repo,
        config_repo=config_repo,
    )
    app.state.engine = engine
    logger.info("Trading engine ready")

    # Start engine only if enabled in MongoDB config
    # Respects user preference (dashboard stop/start persists across restarts)
    if params.enabled:
        logger.info("Auto-starting engine (enabled=True in config)")
        engine.start()
    else:
        logger.info("Engine NOT started (enabled=False in config — start via dashboard)")

    yield

    # ── Shutdown ───────────────────────────────────────────
    logger.info("Shutting down...")

    if hasattr(app.state, 'tick_collector'):
        app.state.tick_collector.stop()

    if hasattr(app.state, 'engine') and app.state.engine.state.running:
        app.state.engine.stop()

    if hasattr(app.state, 'ig_client'):
        app.state.ig_client.disconnect()

    from db.mongo import close_mongo
    close_mongo()

    logger.info("%s shut down cleanly", APP_NAME)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    # Setup logging
    log_level = os.environ.get("OC_LOG_LEVEL", "INFO")
    log_file = os.environ.get("OC_LOG_FILE", "logs/trading.log")
    setup_logging(log_level, log_file)

    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description="ETH/USD Automated Trading with Claude AI",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    from api.router import register_routes
    register_routes(app)

    # WebSocket endpoint
    from fastapi import WebSocket, WebSocketDisconnect

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        ws_manager = app.state.ws_manager
        await ws_manager.connect(websocket)
        try:
            while True:
                # Keep connection alive, receive messages (ping/pong)
                data = await websocket.receive_text()
                # Client can send commands via WS if needed
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    # Status endpoint (no auth required)
    @app.get("/api/status")
    async def get_status():
        engine = app.state.engine
        ig = app.state.ig_client
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "running": engine.state.running,
            "mode": app.state.params.mode,
            "ig_connected": ig.connected,
            "ai_available": engine.state.ai_available,
            "daily_pnl_eur": engine.state.daily_pnl_eur,
            "daily_trades": engine.state.daily_trades,
            "daily_wins": engine.state.daily_wins,
            "daily_losses": engine.state.daily_losses,
            "current_session": engine.state.current_session,
            "last_analysis_time": str(engine.state.last_analysis_time) if engine.state.last_analysis_time else None,
            "last_trade_time": str(engine.state.last_trade_time) if engine.state.last_trade_time else None,
        }

    @app.get("/api/account")
    async def get_account():
        ig = app.state.ig_client
        try:
            account = ig.get_account_info()
            return {"success": True, **account}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return app


# Create app instance
app = create_app()

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("OC_PORT", "5002"))
    host = os.environ.get("OC_HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=False, log_level="info")
