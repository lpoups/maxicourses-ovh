"""
OpenCenterAI — WebSocket Manager
==================================
Centralized WebSocket connection management and event broadcasting.

Events:
  - price_update      : Real-time ETH/USD price ticks
  - position_update   : Open positions PnL refresh
  - signal_update     : New AI signal / analysis result
  - trade_event       : Trade opened, closed, partial close
  - engine_status     : Engine state changes (started, stopped, error)
  - ai_thinking       : AI analysis in progress (streaming thinking)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)


class WSManager:
    """
    Manages active WebSocket connections and broadcasts events.

    Usage:
        ws_manager = WSManager()

        # In a WebSocket endpoint:
        await ws_manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                ...
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

        # From anywhere in the app:
        await ws_manager.broadcast("price_update", {"bid": 3450.5, "offer": 3451.2})
    """

    VALID_EVENTS = {
        "price_update",
        "position_update",
        "signal_update",
        "trade_event",
        "engine_status",
        "ai_thinking",
    }

    def __init__(self) -> None:
        self._connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    # ── Properties ───────────────────────────────────────────────
    @property
    def connection_count(self) -> int:
        return len(self._connections)

    @property
    def connections(self) -> List[WebSocket]:
        return list(self._connections)

    # ── Connect / Disconnect ─────────────────────────────────────
    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        client = ws.client.host if ws.client else "unknown"
        logger.info(
            "WS connected: %s (total=%d)", client, self.connection_count
        )

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket from the active pool (sync-safe)."""
        try:
            self._connections.remove(ws)
        except ValueError:
            pass
        client = ws.client.host if ws.client else "unknown"
        logger.info(
            "WS disconnected: %s (remaining=%d)", client, self.connection_count
        )

    # ── Broadcast ────────────────────────────────────────────────
    async def broadcast(self, event: str, data: Any) -> int:
        """
        Send an event to ALL connected clients.
        Returns the number of clients that received the message.
        """
        if event not in self.VALID_EVENTS:
            logger.warning("Unknown WS event: %s", event)

        message = self._build_message(event, data)
        sent = 0
        stale: List[WebSocket] = []

        for ws in list(self._connections):
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(message)
                    sent += 1
                else:
                    stale.append(ws)
            except Exception:
                stale.append(ws)

        # Clean up broken connections
        for ws in stale:
            self.disconnect(ws)

        return sent

    async def send_to(self, ws: WebSocket, event: str, data: Any) -> bool:
        """Send an event to a single client. Returns True on success."""
        message = self._build_message(event, data)
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_text(message)
                return True
        except Exception:
            self.disconnect(ws)
        return False

    # ── Sync bridge for background threads ──────────────────────
    def emit(self, event: str, data: Any) -> None:
        """
        Sync-safe bridge to broadcast from a background thread.
        Used by TradingEngine (runs in a separate thread).
        """
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.broadcast(event, data), loop=loop)
        except RuntimeError:
            # No running event loop (e.g., during startup) —
            # try to create a new loop or schedule on the main loop.
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(
                        asyncio.ensure_future, self.broadcast(event, data)
                    )
                else:
                    loop.run_until_complete(self.broadcast(event, data))
            except Exception as e:
                logger.debug("WS emit failed (no loop): %s", e)

    # ── Helpers ──────────────────────────────────────────────────
    @staticmethod
    def _build_message(event: str, data: Any) -> str:
        """Serialize an event + payload to JSON string."""
        payload = {
            "event": event,
            "data": data,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(payload, default=str)

    async def close_all(self) -> None:
        """Gracefully close every connection (used at shutdown)."""
        for ws in list(self._connections):
            try:
                await ws.close(code=1001, reason="Server shutting down")
            except Exception:
                pass
        self._connections.clear()
        logger.info("All WebSocket connections closed")


# ═════════════════════════════════════════════════════════════════
# MODULE-LEVEL SINGLETON
# ═════════════════════════════════════════════════════════════════
ws_manager = WSManager()
