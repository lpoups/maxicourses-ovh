"""
core/engine.py -- Main TradingEngine class
=============================================
Orchestrates the trading loop by composing modules:
    - core.state   -> EngineState (volatile runtime state)
    - core.entry   -> can_enter_trade(), execute_entry(), derive_risk_points()
    - core.exit    -> check_exits(), flatten_for_pre_close(), close_position()
    - core.risk    -> compute_trailing_level(), check_daily_limit(), etc.

External dependencies (injected):
    - broker.ig_client  -> IG REST API wrapper
    - ai.prophet        -> Claude prediction engine
    - db.trade_repo     -> MongoDB trade logging
    - db.config_repo    -> MongoDB config persistence
    - config.settings   -> Application settings
    - config.constants  -> SIGNAL_TO_DIRECTION, TRAILING_TIERS, etc.

NO JSON file I/O. Uses threading for the main loop.
"""

import logging
import time
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from core.state import EngineState
from core.entry import (
    SIGNAL_TO_DIRECTION,
    can_enter_trade,
    derive_risk_points,
    execute_entry,
)
from core.exit import (
    check_exits,
    flatten_for_pre_close,
)
from core.risk import (
    check_daily_limit,
    get_drawdown_confidence_boost,
)
from config.constants import ETH_EPIC

logger = logging.getLogger(__name__)

PARIS_TZ = ZoneInfo("Europe/Paris")


class TradingEngine:
    """
    Main trading engine -- orchestrates entry, exit, and risk management.

    Philosophy: "Trust Claude, Execute Fast, Log Everything"
    - Claude is the brain -> no guard overrides his decisions
    - The engine executes -> 5 entry checks, 4 exit mechanisms
    - MongoDB records -> every decision, every trade, to learn from

    Constructor args:
        settings   -- application settings (AppSettings instance)
        params     -- TradingParams from MongoDB (dataclass or dict)
        ig_client  -- IG REST API client instance
        prophet    -- Claude prediction engine instance
        ws_manager -- WebSocket manager for real-time events
    """

    def __init__(
        self,
        settings,
        params,
        ig_client,
        prophet,
        ws_manager,
        *,
        tick_collector=None,
        trade_repo=None,
        config_repo=None,
    ):
        self.settings = settings
        # Convert TradingParams dataclass to dict for .get() access in core modules
        self.params = params.to_dict() if hasattr(params, "to_dict") else (params if isinstance(params, dict) else {})
        self.ig = ig_client
        self.prophet = prophet
        self.ws = ws_manager
        self.tick_collector = tick_collector
        self.trade_repo = trade_repo
        self.config_repo = config_repo

        # Volatile runtime state (never persisted)
        self.state = EngineState()
        self.state.last_reset_date = datetime.now(PARIS_TZ).date()

        # Threading
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        logger.info(
            f"TradingEngine initialised | "
            f"min_confidence={self.params.get('min_confidence', 60)}% "
            f"size={self.params.get('position_size_eth', 2.0)} ETH"
        )

    # =================================================================
    # LIFECYCLE
    # =================================================================

    def start(self):
        """Start the trading engine background loop."""
        if self.state.running:
            logger.warning("TradingEngine already running")
            return
        self.state.enabled = True
        self.state.running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="TradingEngine",
        )
        self._thread.start()
        logger.info("TradingEngine started")

    def stop(self):
        """Stop the trading engine gracefully."""
        self.state.running = False
        self.state.enabled = False
        if self._thread:
            self._thread.join(timeout=15)
            self._thread = None
        logger.info("TradingEngine stopped")

    # =================================================================
    # MAIN LOOP
    # =================================================================

    def _run_loop(self):
        """
        Main loop -- runs every loop_interval_sec (default 5s).
        Separates: position management (every loop) vs entry evaluation.
        Analysis frequency: 60s with position, 180s without position.
        """
        logger.info("TradingEngine loop started")
        loop_interval = self.params.get("loop_interval_sec", 5)

        while self.state.running:
            try:
                if not self.state.enabled:
                    time.sleep(loop_interval)
                    continue

                self._reset_daily_if_needed()

                # -- Manage open positions (every loop, ~5s) --
                positions = self._manage_open_positions()

                # -- Dynamic check interval: 60s with position, 180s without --
                has_position = bool(positions) if positions else False
                check_interval = 60 if has_position else 180

                # -- Evaluate entries (every check_interval) --
                now = time.time()
                if now - self.state.last_check_and_trade_ts >= check_interval:
                    self.state.last_check_and_trade_ts = now
                    self._check_and_trade()

            except Exception as e:
                logger.error(f"TradingEngine loop error: {e}", exc_info=True)

            time.sleep(loop_interval)

        logger.info("TradingEngine loop stopped")

    # =================================================================
    # DAILY RESET
    # =================================================================

    def _reset_daily_if_needed(self):
        """Reset daily counters at midnight Paris time."""
        try:
            today = datetime.now(PARIS_TZ).date()
            if today != self.state.last_reset_date:
                self.state.daily_trades = 0
                self.state.daily_pnl_eur = 0.0
                self.state.daily_wins = 0
                self.state.daily_losses = 0
                self.state.daily_loss_limit_hit = False
                self.state.loss_streak_count = 0
                self.state.last_reset_date = today
                logger.info("Daily reset: trades=0, pnl=0, loss_limit cleared")
        except Exception as e:
            logger.warning(f"Daily reset error: {e}")

    # =================================================================
    # POSITION MANAGEMENT (every loop)
    # =================================================================

    def _manage_open_positions(self):
        """
        Manage open positions -- called EVERY loop iteration (~5s).
        Checks the 4 exit mechanisms in priority order for each position.
        Returns the positions list (for dynamic frequency).
        """
        if not self.ig.connected:
            return []

        # IG weekly close window -> no actions
        if self._is_ig_weekly_closed():
            return []

        raw_positions = self.ig.get_positions() or []
        # Convert Position dataclasses to dicts for core/ module compatibility
        positions = [p.to_dict() if hasattr(p, "to_dict") else p for p in raw_positions]
        if not positions:
            return []

        # Pre-close buffer: flatten before weekly close
        if self._is_ig_pre_close_buffer():
            flatten_for_pre_close(
                ig_client=self.ig,
                positions=positions,
                state=self.state,
                params=self.params,
                trade_repo=self.trade_repo,
            )
            return positions

        # Read latest AI prediction
        prediction = {}
        try:
            pred_src = self.prophet.get_latest_prediction()
            prediction = dict(pred_src) if isinstance(pred_src, dict) else {}
        except Exception:
            prediction = {}

        # Check exits for each open position
        for pos in positions:
            try:
                exit_reason = check_exits(
                    pos=pos,
                    state=self.state,
                    params=self.params,
                    prediction=prediction,
                    ig_client=self.ig,
                    trade_repo=self.trade_repo,
                )
                if exit_reason:
                    # Emit WebSocket event
                    self._emit_exit_event(pos, exit_reason)
            except Exception as e:
                deal_id = pos.get("deal_id", "?")
                logger.error(f"Exit check error for {deal_id}: {e}", exc_info=True)

        return positions

    # =================================================================
    # AI ANALYSIS
    # =================================================================

    def _build_market_snapshot(self, positions: List[Dict]) -> Dict[str, Any]:
        """
        Build a market data snapshot for Claude AI analysis.
        Fetches candles from multiple timeframes, computes indicators,
        and packages everything into a dict that gets JSON-dumped in the prompt.
        """
        snapshot: Dict[str, Any] = {}

        try:
            # --- Current price from ticker ---
            ticker = self.ig.get_ticker(ETH_EPIC) if hasattr(self.ig, "get_ticker") else None
            if ticker:
                snapshot["current_price"] = ticker.bid
                snapshot["bid"] = ticker.bid
                snapshot["offer"] = ticker.offer
                snapshot["spread"] = round(ticker.offer - ticker.bid, 2)

            # --- Fetch candles for multiple timeframes (minimal counts to save IG quota) ---
            candles_5m = self.ig.get_candles(ETH_EPIC, "5min", 60)
            candles_15m = self.ig.get_candles(ETH_EPIC, "15min", 30)
            candles_1h = self.ig.get_candles(ETH_EPIC, "1h", 30)
            candles_4h = self.ig.get_candles(ETH_EPIC, "4h", 20)

            # Convert Candle dataclasses to dicts for TechnicalAnalysis
            def _to_dicts(candle_list):
                if not candle_list:
                    return []
                return [
                    {"open": c.open, "high": c.high, "low": c.low,
                     "close": c.close, "volume": c.volume}
                    for c in candle_list
                ]

            c5m = _to_dicts(candles_5m)
            c15m = _to_dicts(candles_15m)
            c1h = _to_dicts(candles_1h)
            c4h = _to_dicts(candles_4h)

            # --- Compute indicators on 5m candles ---
            if len(c5m) >= 50:
                from indicators.technical import TechnicalAnalysis as TA

                ta = TA(c5m)

                snapshot["rsi_14"] = round(ta.get_rsi(), 2)

                macd_l, macd_s, macd_h = ta.get_macd()
                snapshot["macd"] = {
                    "line": round(macd_l, 4),
                    "signal": round(macd_s, 4),
                    "histogram": round(macd_h, 4),
                }

                bb_u, bb_m, bb_l = ta.get_bollinger()
                snapshot["bollinger"] = {
                    "upper": round(bb_u, 2),
                    "middle": round(bb_m, 2),
                    "lower": round(bb_l, 2),
                }

                snapshot["atr_14"] = round(ta.get_atr(), 2)

                stoch_k, stoch_d = ta.get_stochastic()
                snapshot["stochastic"] = {
                    "k": round(stoch_k, 2),
                    "d": round(stoch_d, 2),
                }

                adx_v, plus_di, minus_di = ta.get_adx()
                snapshot["adx"] = round(adx_v, 2)
                snapshot["adx_dmi"] = {
                    "adx": round(adx_v, 2),
                    "+di": round(plus_di, 2),
                    "-di": round(minus_di, 2),
                }

                snapshot["ema_9"] = round(ta.get_ema(9), 2)
                snapshot["ema_21"] = round(ta.get_ema(21), 2)
                snapshot["ema_50"] = round(ta.get_ema(50), 2)
                snapshot["ema_200"] = round(ta.get_ema(200), 2)

                snapshot["trend_5m"] = ta.get_trend()

                # Last 20 candles for Claude to read
                snapshot["candles_5m"] = [
                    {
                        "o": round(c["open"], 2),
                        "h": round(c["high"], 2),
                        "l": round(c["low"], 2),
                        "c": round(c["close"], 2),
                        "v": c["volume"],
                    }
                    for c in c5m[-20:]
                ]

                if not snapshot.get("current_price"):
                    snapshot["current_price"] = ta.current_price

            # --- Trend biases from higher timeframes ---
            if len(c15m) >= 20:
                from indicators.technical import TechnicalAnalysis as TA
                ta15 = TA(c15m)
                snapshot["trend_15m"] = ta15.get_trend()

            if len(c1h) >= 20:
                from indicators.technical import TechnicalAnalysis as TA
                ta1h = TA(c1h)
                snapshot["trend_1h_bias"] = ta1h.get_trend()
            else:
                snapshot["trend_1h_bias"] = "NEUTRAL"

            if len(c4h) >= 20:
                from indicators.technical import TechnicalAnalysis as TA
                ta4h = TA(c4h)
                snapshot["trend_4h_bias"] = ta4h.get_trend()
            else:
                snapshot["trend_4h_bias"] = "NEUTRAL"

            # --- Multi-TF confluence ---
            try:
                from indicators.multi_tf import compute_multi_tf_confluence
                mtf = compute_multi_tf_confluence(
                    {"5m": c5m, "15m": c15m, "1h": c1h, "4h": c4h}
                )
                snapshot["multi_tf_confluence"] = {
                    "score": mtf.get("score", 0),
                    "direction": mtf.get("direction", "NEUTRAL"),
                }
            except Exception:
                snapshot["multi_tf_confluence"] = {"score": 0, "direction": "NEUTRAL"}

            # --- Position info ---
            has_pos = len(positions) > 0
            snapshot["has_position"] = has_pos
            if has_pos:
                pos = positions[0]
                snapshot["position_direction"] = pos.get("direction", "")
                snapshot["position_pnl"] = round(
                    float(pos.get("pnl", 0) or pos.get("profit_loss", 0) or 0), 2
                )
                snapshot["position_entry_price"] = float(
                    pos.get("entry_price", 0) or pos.get("level", 0) or 0
                )
                snapshot["position_size"] = float(pos.get("size", 0) or 0)

            # --- Daily stats ---
            snapshot["daily_pnl_eur"] = round(self.state.daily_pnl_eur, 2)
            snapshot["daily_trades"] = self.state.daily_trades
            snapshot["daily_wins"] = self.state.daily_wins
            snapshot["daily_losses"] = self.state.daily_losses

            # --- Signal history ---
            if hasattr(self.prophet, "_signal_history"):
                snapshot["recent_signals"] = [
                    {
                        "action": s.get("action"),
                        "confidence": s.get("confidence"),
                        "price": s.get("price"),
                    }
                    for s in self.prophet._signal_history[-5:]
                ]

        except Exception as e:
            logger.error(f"Error building market snapshot: {e}", exc_info=True)

        return snapshot

    def _run_ai_analysis(self, positions: List[Dict]) -> Dict[str, Any]:
        """
        Run a full AI analysis cycle via Claude.
        Builds a market snapshot and calls prophet.analyze().
        """
        try:
            snapshot = self._build_market_snapshot(positions)
            if not snapshot.get("current_price"):
                logger.warning("AI analysis skipped: no price data available")
                return {}

            has_pos = len(positions) > 0
            pos_dir = ""
            if has_pos:
                pos_dir = positions[0].get("direction", "")

            decision = self.prophet.analyze(
                snapshot=snapshot,
                has_position=has_pos,
                position_direction=pos_dir,
            )

            self.state.last_analysis_time = datetime.now(PARIS_TZ)
            self.state.ai_available = True

            action = decision.get("action", "WAIT") if decision else "WAIT"
            conf = decision.get("confidence", 0) if decision else 0
            logger.info(f"AI analysis complete: {action} ({conf}%%)")

            return decision or {}

        except Exception as e:
            logger.error(f"AI analysis error: {e}", exc_info=True)
            self.state.ai_available = False
            return {}

    # =================================================================
    # ENTRY EVALUATION (every check_interval)
    # =================================================================

    def _check_and_trade(self):
        """
        Evaluate AI signal and execute a trade if conditions are met.
        Called every check_interval_sec (default 60s).
        """
        # Check IG connection with backoff
        if not self.ig.connected:
            if not self._ig_reconnect_with_backoff():
                return

        # Read positions (convert dataclasses to dicts)
        raw_positions = self.ig.get_positions() or []
        positions = [p.to_dict() if hasattr(p, "to_dict") else p for p in raw_positions]
        self._cleanup_stale_tracking(positions)

        has_pos = len(positions) > 0
        if self.state.had_position and not has_pos:
            logger.info("Position(s) closed -> ready for next opportunity")
        self.state.had_position = has_pos

        # Run AI analysis (builds snapshot, calls Claude, updates latest_prediction)
        self._run_ai_analysis(positions)

        # Read AI prediction (just updated by analyze())
        prediction = {}
        try:
            pred_src = self.prophet.get_latest_prediction()
            prediction = dict(pred_src) if isinstance(pred_src, dict) else {}
        except Exception as e:
            logger.warning(f"Prophet prediction unavailable: {e}")
            return

        pred_ts = int(prediction.get("timestamp", 0) or 0)
        is_new = pred_ts > 0 and pred_ts != self.state.last_prediction_ts

        if is_new:
            self.state.last_prediction_ts = pred_ts
            self.state.last_ai_analysis_ts = time.time()
            self.state.last_claude_thinking = str(
                prediction.get("ai_thinking", "") or ""
            )[:300]
            self.state.last_claude_reason = str(
                prediction.get("reason", "") or ""
            )[:180]

        # Extract signal
        signal = str(prediction.get("signal", "WAIT")).upper()
        confidence = float(
            prediction.get("probability", 0)
            or prediction.get("confidence", 0)
            or 0
        )
        action = str(prediction.get("action", "WAIT")).upper()

        self.state.last_signal = signal
        logger.info(f"Signal: {signal} {int(confidence)}% (action={action})")

        # No entry signal -> skip
        if signal not in ("LONG", "SHORT"):
            self.state.last_block_reason = (
                "AI_WAIT" if signal == "WAIT" else f"AI_{signal}"
            )
            return

        # Check entry guards
        can_trade, reason = can_enter_trade(
            signal=signal,
            confidence=confidence,
            state=self.state,
            params=self.params,
            positions=positions,
            ig_connected=self.ig.connected,
            is_night_block=self._is_night_block(),
            is_ig_weekly_closed=self._is_ig_weekly_closed(),
            is_ig_pre_close_buffer=self._is_ig_pre_close_buffer(),
        )
        if not can_trade:
            self.state.last_block_reason = reason
            logger.info(f"Entry blocked: {reason}")
            return

        # Map signal to direction
        trade_dir = SIGNAL_TO_DIRECTION.get(signal, "BUY")

        # Resolve current price
        current_price = self._resolve_current_price(prediction)
        if current_price <= 0:
            logger.warning("Entry skipped: current_price unavailable")
            return

        # Derive SL/TP
        stop_dist, limit_dist, risk_src = derive_risk_points(
            prediction=prediction,
            current_price=current_price,
            direction=trade_dir,
            params=self.params,
        )

        trade_size = self.params.get("position_size_eth", 2.0)

        # Night block double-check
        entry_block_enabled = self.params.get("entry_block_hours_enabled", True)
        if entry_block_enabled:
            try:
                cur_hour = datetime.now(PARIS_TZ).hour
                block_hours = self.params.get("entry_block_hours_paris", [0, 1, 2, 3, 4, 5])
                if cur_hour in block_hours:
                    logger.warning(f"NIGHT BLOCK: {trade_dir} at {cur_hour}h Paris")
                    return
            except Exception:
                pass

        # Execute entry
        result = execute_entry(
            ig_client=self.ig,
            trade_dir=trade_dir,
            trade_size=trade_size,
            stop_dist=stop_dist,
            limit_dist=limit_dist,
            confidence=confidence,
            current_price=current_price,
            prediction=prediction,
            state=self.state,
            params=self.params,
            pred_ts=pred_ts,
            trade_repo=self.trade_repo,
        )

        if result.get("success"):
            # Emit WebSocket event
            self._emit_entry_event(result, prediction)
            # Force AI analysis (transition mode)
            try:
                self.prophet.force_analysis()
                logger.info("AI Force Analysis triggered")
            except Exception:
                pass

    # =================================================================
    # SCHEDULE CHECKS
    # =================================================================

    def _is_night_block(self) -> bool:
        """No trades between 00h and 06h (Paris time)."""
        if not self.params.get("entry_block_hours_enabled", True):
            return False
        try:
            hour = datetime.now(PARIS_TZ).hour
            block_hours = self.params.get("entry_block_hours_paris", [0, 1, 2, 3, 4, 5])
            return hour in block_hours
        except Exception:
            return False

    def _is_ig_weekly_closed(self) -> bool:
        """IG closed: Friday 23h -> Saturday 9h (Paris)."""
        try:
            now = datetime.now(PARIS_TZ)
            wd = now.weekday()  # 0=Mon, 4=Fri, 5=Sat
            hour = now.hour
            return (wd == 4 and hour >= 23) or (wd == 5 and hour < 9)
        except Exception:
            return False

    def _is_ig_pre_close_buffer(self) -> bool:
        """Friday pre-close buffer (N min before 22h Paris)."""
        try:
            now = datetime.now(PARIS_TZ)
            if now.weekday() != 4:
                return False
            mins = now.hour * 60 + now.minute
            buffer_min = self.params.get("ig_weekly_preclose_buffer_min", 15)
            cutoff = 22 * 60
            start = cutoff - max(1, buffer_min)
            return start <= mins < cutoff
        except Exception:
            return False

    # =================================================================
    # IG RECONNECTION
    # =================================================================

    def _ig_reconnect_with_backoff(self) -> bool:
        """Reconnect to IG with exponential backoff."""
        now = time.time()
        if now < self.state.next_ig_connect_attempt_ts:
            return False

        if not self.ig.ensure_connected():
            self.state.ig_connect_fail_streak = min(
                8, self.state.ig_connect_fail_streak + 1,
            )
            base_sec = self.params.get("ig_connect_retry_base_sec", 10)
            max_sec = self.params.get("ig_connect_retry_max_sec", 300)
            backoff = min(
                max_sec,
                base_sec * (2 ** (self.state.ig_connect_fail_streak - 1)),
            )
            self.state.next_ig_connect_attempt_ts = now + backoff
            self.state.last_block_reason = "IG_DISCONNECTED"
            logger.info(
                f"IG reconnect backoff {backoff}s "
                f"(fail={self.state.ig_connect_fail_streak})"
            )
            return False

        self.state.ig_connect_fail_streak = 0
        self.state.next_ig_connect_attempt_ts = 0.0
        logger.info("IG reconnected")
        return True

    # =================================================================
    # PRICE RESOLUTION
    # =================================================================

    def _resolve_current_price(self, prediction: Dict[str, Any]) -> float:
        """
        Resolve current price from multiple sources, in priority order:
        1. prediction dict (current_price, last_close, entry_price, price)
        2. TickCollector latest_bid (always fresh if collector is running)
        3. IG ticker direct call (Ticker is a dataclass, use .bid not .get())
        """
        current_price = float(prediction.get("current_price", 0) or 0)

        if current_price <= 0:
            for key in ("last_close", "entry_price", "price"):
                current_price = float(prediction.get(key, 0) or 0)
                if current_price > 0:
                    logger.info(f"Price via prediction['{key}']: {current_price}")
                    break

        # Fallback 2: TickCollector (always running, always fresh)
        if current_price <= 0 and self.tick_collector:
            current_price = self.tick_collector.latest_bid
            if current_price > 0:
                logger.info(f"Price via TickCollector: {current_price}")

        # Fallback 3: IG ticker direct call (Ticker is a dataclass!)
        if current_price <= 0:
            try:
                ticker = self.ig.get_ticker(ETH_EPIC)
                if ticker and ticker.bid > 0:
                    current_price = ticker.bid
                    logger.info(f"Price via IG ticker: {current_price}")
            except Exception:
                pass

        return current_price

    # =================================================================
    # TRACKING CLEANUP
    # =================================================================

    def _cleanup_stale_tracking(self, positions: List[Dict]):
        """Remove tracking for deals no longer in open positions."""
        open_deals = {
            str(p.get("deal_id", ""))
            for p in positions
            if p.get("deal_id")
        }
        for tracking_dict in (
            self.state.max_unrealized_by_deal,
            self.state.min_unrealized_by_deal,
            self.state.trailing_stop_by_deal,
            self.state.last_gain_lock_by_deal,
            self.state.position_risk_targets,
            self.state.partial_exit_state_by_deal,
            self.state.secure_gain_profile_by_deal,
        ):
            stale = [k for k in tracking_dict if k not in open_deals]
            for k in stale:
                tracking_dict.pop(k, None)

    # =================================================================
    # WEBSOCKET EVENTS
    # =================================================================

    def _emit_entry_event(self, result: Dict, prediction: Dict):
        """Emit a WebSocket event after a successful entry."""
        if self.ws is None:
            return
        try:
            self.ws.emit("trade_entry", {
                "deal_id": result.get("deal_id"),
                "direction": result.get("direction"),
                "size": result.get("size"),
                "sl_pts": result.get("sl_pts"),
                "tp_pts": result.get("tp_pts"),
                "rr": result.get("rr"),
                "signal": prediction.get("signal"),
                "confidence": prediction.get("probability")
                or prediction.get("confidence"),
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.debug(f"WS emit entry error: {e}")

    def _emit_exit_event(self, pos: Dict, reason: str):
        """Emit a WebSocket event after a position exit."""
        if self.ws is None:
            return
        try:
            self.ws.emit("trade_exit", {
                "deal_id": pos.get("deal_id"),
                "direction": pos.get("direction"),
                "pnl": pos.get("profit_loss"),
                "reason": reason,
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.debug(f"WS emit exit error: {e}")

    # =================================================================
    # API INTERFACE
    # =================================================================

    def get_status(self) -> Dict[str, Any]:
        """Engine status -- ~40 fields for the dashboard."""
        s = self.state
        p = self.params
        return {
            # Core
            "enabled": s.enabled,
            "running": s.running,
            "mode": p.get("mode", "AUTO"),
            "min_confidence": p.get("min_confidence", 60),
            "check_interval": p.get("check_interval_sec", 60),
            "frequency_mode": p.get("frequency_mode", "NORMAL"),
            "hybrid_analysis_mode": p.get("hybrid_analysis_mode", "SERVER"),

            # Position
            "position_size": p.get("position_size_eth", 2.0),
            "max_open_positions": p.get("max_open_positions", 3),
            "max_total_exposure_eth": p.get("max_total_exposure_eth", 4.0),

            # Risk
            "sl_pct": p.get("sl_pct", 0.01),
            "tp_pct": p.get("tp_pct", 0.02),
            "stop_distance_pts": p.get("stop_distance_pts", 30.0),
            "limit_distance_pts": p.get("limit_distance_pts", 60.0),
            "hard_loss_cap_pct": p.get("hard_loss_cap_pct", 0.02),
            "daily_loss_limit_eur": p.get("daily_loss_limit_eur", 100.0),
            "daily_pnl_eur": round(s.daily_pnl_eur, 2),
            "daily_loss_limit_hit": s.daily_loss_limit_hit,

            # Trailing / AI risk
            "preserve_gains_enabled": p.get("preserve_gains_enabled", True),
            "ai_autonomous_risk_enabled": p.get("ai_autonomous_risk_enabled", True),

            # Exits
            "profit_retrace_enabled": p.get("profit_retrace_enabled", True),
            "partial_exit_enabled": p.get("partial_exit_enabled", True),
            "ai_blind_exit_enabled": p.get("ai_blind_exit_enabled", True),
            "ai_exit_only_mode": True,

            # Trading state
            "last_trade_time": (
                s.last_trade_time.isoformat() if s.last_trade_time else None
            ),
            "last_signal": s.last_signal,
            "trades_executed": s.trades_executed,
            "trades_today": s.daily_trades,
            "loss_streak": s.loss_streak_count,
            "last_block_reason": s.last_block_reason,

            # Tracking
            "position_risk_targets": s.position_risk_targets,
            "trailing_stop_by_deal": {
                k: round(v, 2) for k, v in s.trailing_stop_by_deal.items()
            },
            "max_unrealized_by_deal": {
                k: round(v, 2) for k, v in s.max_unrealized_by_deal.items()
            },
            "next_trade_secure_pending": s.next_trade_secure_armed,
            "next_trade_secure_reason": s.next_trade_secure_reason,

            # Schedule
            "entry_block_hours_paris": p.get(
                "entry_block_hours_paris", [0, 1, 2, 3, 4, 5]
            ),
            "ig_weekly_closed_window": self._is_ig_weekly_closed(),
            "ig_pre_close_buffer_active": self._is_ig_pre_close_buffer(),

            # Compat flags
            "dynamic_mode": True,
            "dynamic_manage_open_risk": True,
            "prevent_sl_widening": p.get("prevent_sl_widening", True),
            "immediate_entry_mode": True,
        }

    def set_config(self, **kwargs):
        """
        Update runtime-configurable params.
        Accepts dashboard params + backward compat from old auto_trader.
        """
        changed = []

        if "enabled" in kwargs:
            val = kwargs["enabled"]
            if val and not self.state.running:
                self.start()
            elif not val and self.state.running:
                self.stop()
            self.state.enabled = bool(val)
            changed.append("enabled")

        # Direct param overrides
        CONFIG_MAP = {
            "mode": ("mode", str, None, None),
            "frequency_mode": ("frequency_mode", str, None, None),
            "position_size": ("position_size_eth", float, 0.1, 4.0),
            "stop_distance_pts": ("stop_distance_pts", float, 1, 200),
            "limit_distance_pts": ("limit_distance_pts", float, 1, 200),
            "hybrid_analysis_mode": ("hybrid_analysis_mode", str, None, None),
            "min_confidence": ("min_confidence", int, 35, 95),
            "check_interval": ("check_interval_sec", int, 10, 3600),
            "max_open_positions": ("max_open_positions", int, 1, 5),
            "max_total_exposure_eth": ("max_total_exposure_eth", float, 0.1, 10.0),
            "loss_cooldown_min": ("loss_cooldown_min", int, 0, 60),
            "daily_loss_limit_eur": ("daily_loss_limit_eur", float, 0, 500),
            "hard_loss_cap_eur": ("hard_loss_cap_eur", float, 5, 500),
        }

        for key, (param_key, conv, lo, hi) in CONFIG_MAP.items():
            if key in kwargs:
                val = conv(kwargs[key])
                if conv == str:
                    val = val.upper()
                elif lo is not None and hi is not None:
                    val = max(lo, min(hi, val))
                self.params[param_key] = val
                changed.append(key)

        # Boolean toggles
        BOOL_MAP = {
            "profit_retrace_enabled": "profit_retrace_enabled",
            "partial_exit_enabled": "partial_exit_enabled",
            "preserve_gains_enabled": "preserve_gains_enabled",
            "hard_loss_cap_enabled": "hard_loss_cap_enabled",
            "ai_autonomous_risk_enabled": "ai_autonomous_risk_enabled",
        }
        for key, param_key in BOOL_MAP.items():
            if key in kwargs:
                self.params[param_key] = bool(kwargs[key])
                changed.append(key)

        if changed:
            logger.info(f"Config updated: {', '.join(changed)}")

    def set_hybrid_config(
        self,
        mode: Optional[str] = None,
        max_age_sec: Optional[int] = None,
        persist: bool = False,
    ):
        """Backward compat -- configure hybrid analysis mode."""
        if mode:
            self.params["hybrid_analysis_mode"] = str(mode).upper()
        if max_age_sec is not None:
            self.params["hybrid_prediction_max_age_sec"] = int(max_age_sec)

    def ingest_hybrid_prediction(
        self, prediction: dict, source: str = "UNKNOWN",
    ) -> dict:
        """Backward compat -- ingest hybrid prediction from external source."""
        logger.info(
            f"Hybrid prediction ingested from {source}: "
            f"{prediction.get('signal', 'N/A')}"
        )
        return {"status": "ok", "source": source}
