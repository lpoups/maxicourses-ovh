"""
core -- Trading engine core modules
=====================================
    state.py   -> EngineState dataclass (volatile runtime state)
    entry.py   -> Entry logic (5 guards + execution + risk derivation)
    exit.py    -> All exit mechanisms (4 primary + partial + gain lock)
    risk.py    -> Risk management (trailing, SL/TP, drawdown, daily limits)
    engine.py  -> Main TradingEngine orchestrator class
"""

from core.state import EngineState
from core.engine import TradingEngine

__all__ = ["EngineState", "TradingEngine"]
