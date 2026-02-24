"""
OpenCenterAI — Tick Collector Service
=======================================
Runs as a background thread, completely independent of TradingEngine.
Collects IG ticker prices every ~5s and:
  1. Emits price_update via WebSocket for frontend real-time display
  2. Builds OHLC candles in MongoDB from real IG bid prices
  3. Stores the latest price for other modules to read

This thread starts at application startup and never stops —
regardless of whether trading is enabled, paused, or stopped.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

from pymongo import UpdateOne

from config.constants import ETH_EPIC
from db.collections import CANDLE_CACHE

logger = logging.getLogger(__name__)

# Resolutions to build from ticks (IG format -> seconds per candle)
_TICK_RESOLUTIONS = {
    "1Min": 60,
    "5Min": 300,
    "15Min": 900,
    "1H": 3600,
    "4H": 14400,
}


class TickCollector:
    """
    Autonomous price collector — starts once, runs forever.

    Usage:
        collector = TickCollector(ig_client=ig, ws_manager=ws)
        collector.start()       # launches background thread
        ...
        price = collector.latest_bid   # read from anywhere
        collector.stop()        # graceful shutdown
    """

    def __init__(self, ig_client, ws_manager, interval_sec: float = 5.0):
        self.ig = ig_client
        self.ws = ws_manager
        self.interval = interval_sec

        # Latest known price (thread-safe reads via GIL)
        self.latest_bid: float = 0.0
        self.latest_offer: float = 0.0
        self.latest_ts: int = 0

        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ── Lifecycle ──────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="TickCollector",
        )
        self._thread.start()
        logger.info("TickCollector started (every %.0fs)", self.interval)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("TickCollector stopped")

    # ── Main loop ─────────────────────────────────────────────

    def _run(self):
        """Background loop — collect ticks forever."""
        while self._running:
            try:
                self._collect()
            except Exception as e:
                logger.debug("TickCollector error: %s", e)
            time.sleep(self.interval)

    def _collect(self):
        """Single tick collection cycle."""
        if not self.ig.connected:
            return

        ticker = self.ig.get_ticker(ETH_EPIC)
        if not ticker or not ticker.bid:
            return

        bid = ticker.bid
        offer = ticker.offer or bid
        spread = round(offer - bid, 2) if offer else 0
        now_ts = int(time.time())

        # Update latest known price
        self.latest_bid = bid
        self.latest_offer = offer
        self.latest_ts = now_ts

        # 1. Emit to WebSocket
        if self.ws:
            try:
                self.ws.emit("price_update", {
                    "bid": bid,
                    "offer": offer,
                    "spread": spread,
                    "high": ticker.high,
                    "low": ticker.low,
                    "change_pct": getattr(ticker, "change_pct", None),
                    "timestamp": now_ts,
                })
            except Exception:
                pass

        # 2. Build candles in MongoDB
        try:
            from db.mongo import get_db
            db = get_db()
            coll = db[CANDLE_CACHE]
            ops = []

            for res, period_sec in _TICK_RESOLUTIONS.items():
                candle_ts = now_ts - (now_ts % period_sec)
                ops.append(UpdateOne(
                    {"epic": ETH_EPIC, "resolution": res, "timestamp": candle_ts},
                    {
                        "$set": {"close": bid},
                        "$min": {"low": bid},
                        "$max": {"high": bid},
                        "$inc": {"volume": 1},
                        "$setOnInsert": {
                            "open": bid,
                            "epic": ETH_EPIC,
                            "resolution": res,
                            "timestamp": candle_ts,
                        },
                    },
                    upsert=True,
                ))

            if ops:
                coll.bulk_write(ops, ordered=False)

        except Exception as e:
            logger.debug("Tick candle write: %s", e)
