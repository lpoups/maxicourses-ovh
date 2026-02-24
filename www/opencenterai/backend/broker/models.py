"""
OpenCenterAI Trading -- Broker Data Models
============================================
Typed dataclasses for all broker-level objects.
No business logic here -- pure data containers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    """An open position on the broker."""

    deal_id: str
    epic: str
    direction: str  # "BUY" or "SELL"
    size: float
    entry_price: float
    current_price: float = 0.0
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    pnl: float = 0.0
    currency: str = "USD"
    expiry: str = "-"
    created_at: str = ""
    bid: float = 0.0
    offer: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to dict with legacy alias fields for core/ modules."""
        from dataclasses import asdict
        d = asdict(self)
        # Legacy aliases expected by core/exit.py and core/entry.py
        d["profit_loss"] = d["pnl"]
        d["current_level"] = d["current_price"]
        d["level"] = d["entry_price"]
        d["open_level"] = d["entry_price"]
        return d


@dataclass
class Trade:
    """A closed (historical) trade record."""

    trade_id: str
    deal_id: str
    direction: str  # "BUY" or "SELL"
    size: float
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    status: str = ""  # e.g. "CLOSED", "OPEN"
    instrument: str = ""
    date: str = ""
    date_display: str = ""
    action_type: str = ""


@dataclass
class Ticker:
    """Real-time market snapshot for a single instrument."""

    epic: str
    name: str = ""
    bid: float = 0.0
    offer: float = 0.0
    high: float = 0.0
    low: float = 0.0
    change_pct: float = 0.0
    market_status: str = "CLOSED"
    min_size: float = 0.1
    min_stop_distance: Optional[float] = None
    min_limit_distance: Optional[float] = None
    timestamp: float = 0.0


@dataclass
class Candle:
    """A single OHLCV candle."""

    timestamp: int  # Unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


@dataclass
class OrderResult:
    """Outcome of an order submission (open or close)."""

    success: bool
    deal_id: str = ""
    deal_reference: str = ""
    reason: str = ""
    error: str = ""
    direction: str = ""
    size: float = 0.0
    # Extra metadata for fallback/retry paths
    opened_without_attached_orders: bool = False
    risk_attached: bool = True
    duplicate_recent_success: bool = False
    profile: str = ""

    def to_dict(self) -> dict:
        """Serialize to a plain dict for API responses / logging."""
        return {
            "success": self.success,
            "deal_id": self.deal_id,
            "deal_reference": self.deal_reference,
            "reason": self.reason,
            "error": self.error,
            "direction": self.direction,
            "size": self.size,
        }
