"""
core/state.py -- Runtime state dataclass (volatile, never persisted to disk)
=============================================================================
All fields reset on restart. This is the single source of truth for
the engine's ephemeral runtime state.

NO JSON file I/O. NO disk persistence. Pure in-memory state.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict


@dataclass
class EngineState:
    """
    Volatile runtime state for the trading engine.
    Reset on every restart -- never persisted to disk.
    """

    # -- Lifecycle --
    running: bool = False
    enabled: bool = True

    # -- Daily counters (reset at midnight Paris) --
    daily_pnl_eur: float = 0.0
    daily_trades: int = 0
    daily_wins: int = 0
    daily_losses: int = 0
    daily_loss_limit_hit: bool = False
    last_reset_date: Optional[object] = None  # date object

    # -- Trade timing --
    last_trade_time: Optional[datetime] = None
    last_analysis_time: Optional[datetime] = None
    last_ai_analysis_ts: float = 0.0
    last_prediction_ts: int = 0
    last_entry_pred_ts: int = 0
    last_check_and_trade_ts: float = 0.0

    # -- Loss tracking --
    last_loss_direction: Optional[str] = None
    loss_cooldown_until: Optional[datetime] = None
    loss_streak_count: int = 0
    direction_cooldown_until: Dict[str, float] = field(
        default_factory=lambda: {"BUY": 0.0, "SELL": 0.0}
    )

    # -- Next trade secure --
    next_trade_secure_armed: bool = False
    next_trade_secure_loss_eur: float = 0.0
    next_trade_secure_reason: str = ""

    # -- Connection / availability --
    ig_connected: bool = False
    ai_available: bool = True
    ig_connect_fail_streak: int = 0
    next_ig_connect_attempt_ts: float = 0.0

    # -- Session --
    current_session: str = "UNKNOWN"
    last_signal: Optional[str] = None
    last_block_reason: str = "INIT"
    trades_executed: int = 0
    had_position: bool = False

    # -- AI tracking --
    last_claude_thinking: str = ""
    last_claude_reason: str = ""

    # -- Position tracking dicts --
    max_unrealized_by_deal: Dict[str, float] = field(default_factory=dict)
    min_unrealized_by_deal: Dict[str, float] = field(default_factory=dict)
    trailing_stop_by_deal: Dict[str, float] = field(default_factory=dict)
    last_gain_lock_by_deal: Dict[str, float] = field(default_factory=dict)
    position_risk_targets: Dict[str, Dict] = field(default_factory=dict)
    partial_exit_state_by_deal: Dict[str, Dict] = field(default_factory=dict)
    secure_gain_profile_by_deal: Dict[str, Dict] = field(default_factory=dict)
    open_timestamp_by_deal: Dict[str, str] = field(default_factory=dict)

    # -- Hybrid --
    last_hybrid_source: str = "SERVER"
    last_hybrid_status: str = "IDLE"
    last_hybrid_ingest_ts: float = 0
