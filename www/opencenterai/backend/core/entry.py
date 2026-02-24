"""
core/entry.py -- Entry logic: 5 guards + trade execution + risk derivation
===========================================================================
Extracted from trading_engine.py (lines 300-677).

5 GUARDS (everything else REMOVED):
    1. IG connected?
    2. Market open? (night block + IG weekly close)
    3. Daily loss limit not hit? (with drawdown confidence boost tiers)
    4. Trade cooldown (min_trade_interval + loss direction cooldown)
    5. Max positions / max exposure check

NO contrarian logic. NO WAIT overrides. NO recovery mode.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.state import EngineState

logger = logging.getLogger(__name__)

# =========================================================================
# Signal-to-direction mapping (canonical, from constants.py)
# =========================================================================
SIGNAL_TO_DIRECTION: Dict[str, str] = {
    "LONG": "BUY",
    "SHORT": "SELL",
}


# =========================================================================
# 5 ENTRY GUARDS
# =========================================================================

def can_enter_trade(
    signal: str,
    confidence: float,
    state: EngineState,
    params: Dict[str, Any],
    positions: List[Dict],
    *,
    ig_connected: bool = False,
    is_night_block: bool = False,
    is_ig_weekly_closed: bool = False,
    is_ig_pre_close_buffer: bool = False,
) -> Tuple[bool, str]:
    """
    The 5 ONLY entry guards.  Returns (can_trade, block_reason).

    ``params`` keys used:
        min_confidence, drawdown_conf_boost_tiers, min_trade_interval_sec,
        max_open_positions, max_total_exposure_eth
    """
    # -- 1. IG connected? --
    if not ig_connected:
        return False, "IG_DISCONNECTED"

    # -- 2. Market open? --
    if is_night_block:
        return False, "NIGHT_BLOCK"
    if is_ig_weekly_closed:
        return False, "IG_WEEKLY_CLOSED"
    if is_ig_pre_close_buffer:
        return False, "IG_PRE_CLOSE_BUFFER"

    # -- 3. Daily loss limit --
    if state.daily_loss_limit_hit:
        return False, f"DAILY_LOSS_LIMIT_HIT:{round(state.daily_pnl_eur, 2)}EUR"

    # Drawdown confidence boost: raise required confidence when losing
    effective_min_conf = params.get("min_confidence", 60)
    tiers = params.get("drawdown_conf_boost_tiers", [])
    for threshold, boost in tiers:
        if state.daily_pnl_eur <= threshold:
            effective_min_conf += boost

    if confidence < effective_min_conf:
        return False, f"CONFIDENCE_LOW:{int(confidence)}<{effective_min_conf}"

    # -- 4. Trade cooldown --
    min_trade_interval = params.get("min_trade_interval_sec", 180)
    if state.last_trade_time:
        elapsed = (datetime.now() - state.last_trade_time).total_seconds()
        if elapsed < min_trade_interval:
            return False, f"TRADE_COOLDOWN:{int(elapsed)}s<{min_trade_interval}s"

    # Loss direction cooldown
    trade_dir = SIGNAL_TO_DIRECTION.get(signal, "BUY")
    cooldown_until = state.direction_cooldown_until.get(trade_dir, 0.0)
    if time.time() < cooldown_until:
        remaining = int(cooldown_until - time.time())
        return False, f"LOSS_COOLDOWN:{remaining}s"

    # -- 5. Max positions / exposure --
    max_positions = params.get("max_open_positions", 3)
    if len(positions) >= max_positions:
        return False, f"MAX_POSITIONS:{len(positions)}/{max_positions}"

    max_exposure = params.get("max_total_exposure_eth", 4.0)
    open_exposure = sum(float(p.get("size", 0) or 0) for p in positions)
    if open_exposure >= max_exposure - 0.01:
        return False, f"MAX_EXPOSURE:{round(open_exposure, 2)}/{max_exposure}ETH"

    return True, "OK"


# =========================================================================
# RISK DERIVATION (SL / TP calculation)
# =========================================================================

def derive_risk_points(
    prediction: Dict[str, Any],
    current_price: float,
    direction: str,
    params: Dict[str, Any],
) -> Tuple[float, float, str]:
    """
    Compute SL/TP in points.
    Priority: AI price levels > ATR-based > PCT fallback.
    Returns (sl_points, tp_points, source_label).

    ``params`` keys used:
        ai_autonomous_risk_enabled, ai_autonomous_sl_atr_mult,
        ai_autonomous_tp_rr_trend, ai_autonomous_tp_rr_range,
        ai_autonomous_tp_rr_transition, ai_autonomous_min_rr,
        ai_autonomous_max_rr, sl_pct, tp_pct
    """
    # Minimum SL floor -- IG DEMO ETH rejects stops < ~20 pts
    min_sl_pts = max(25.0, current_price * 0.013) if current_price > 0 else 25.0

    ai_autonomous_min_rr = params.get("ai_autonomous_min_rr", 1.2)

    # -- 1. AI provides explicit target / stop price levels --
    ai_target = float(
        prediction.get("level_target", 0)
        or prediction.get("target", 0)
        or 0
    )
    ai_stop = float(
        prediction.get("level_invalidation", 0)
        or prediction.get("stop", 0)
        or 0
    )

    if ai_target > 0 and ai_stop > 0 and current_price > 0:
        if direction == "BUY":
            raw_sl = current_price - ai_stop
            raw_tp = ai_target - current_price
        else:
            raw_sl = ai_stop - current_price
            raw_tp = current_price - ai_target

        sl_pts = max(min_sl_pts, raw_sl)
        tp_pts = max(1.0, raw_tp)

        if sl_pts > raw_sl + 0.5:
            logger.info(
                f"SL floor applied: AI={round(raw_sl, 2)}pts -> "
                f"min={round(sl_pts, 2)}pts (floor={round(min_sl_pts, 2)}pts "
                f"for price={round(current_price, 2)})"
            )

        # Enforce minimum R:R
        rr = tp_pts / sl_pts if sl_pts > 0 else 0
        if rr < ai_autonomous_min_rr:
            tp_pts = sl_pts * ai_autonomous_min_rr

        return round(sl_pts, 2), round(tp_pts, 2), "AI_LEVELS"

    # -- 2. ATR-based (if AI provides ATR) --
    indicators = prediction.get("indicators") or {}
    atr = float(indicators.get("atr", 0) or prediction.get("atr", 0) or 0)
    regime = str(prediction.get("regime", "TRANSITION")).upper()

    ai_autonomous_risk_enabled = params.get("ai_autonomous_risk_enabled", True)
    if atr > 0 and ai_autonomous_risk_enabled:
        sl_atr_mult = params.get("ai_autonomous_sl_atr_mult", 1.5)
        sl_pts = max(min_sl_pts, atr * sl_atr_mult)

        rr_map = {
            "TREND_UP": params.get("ai_autonomous_tp_rr_trend", 2.0),
            "TREND_DOWN": params.get("ai_autonomous_tp_rr_trend", 2.0),
            "RANGE": params.get("ai_autonomous_tp_rr_range", 1.5),
            "TRANSITION": params.get("ai_autonomous_tp_rr_transition", 1.8),
        }
        rr = rr_map.get(regime, params.get("ai_autonomous_tp_rr_transition", 1.8))
        ai_autonomous_max_rr = params.get("ai_autonomous_max_rr", 4.0)
        rr = max(ai_autonomous_min_rr, min(ai_autonomous_max_rr, rr))
        tp_pts = sl_pts * rr

        return round(sl_pts, 2), round(tp_pts, 2), f"ATR_{regime}"

    # -- 3. PCT-based fallback --
    sl_pct = params.get("sl_pct", 0.01)
    tp_pct = params.get("tp_pct", 0.02)
    sl_pts = max(min_sl_pts, current_price * sl_pct)
    tp_pts = max(min_sl_pts, current_price * tp_pct)

    return round(sl_pts, 2), round(tp_pts, 2), "PCT_FALLBACK"


# =========================================================================
# TRADE EXECUTION
# =========================================================================

def execute_entry(
    ig_client,
    trade_dir: str,
    trade_size: float,
    stop_dist: float,
    limit_dist: float,
    confidence: float,
    current_price: float,
    prediction: Dict[str, Any],
    state: EngineState,
    params: Dict[str, Any],
    pred_ts: int = 0,
    *,
    trade_repo=None,
) -> Dict[str, Any]:
    """
    Open a position via ig_client with computed SL/TP.

    Returns dict with keys: success, deal_id, error (on failure).
    Side-effects: updates state, logs to trade_repo (MongoDB).
    """

    # -- Apply next-trade-secure adjustments if armed --
    secure_next = False
    nts_enabled = params.get("next_trade_secure_after_loss_enabled", False)
    if state.next_trade_secure_armed and nts_enabled:
        secure_next = True
        stop_mult = params.get("next_trade_secure_stop_mult", 0.7)
        tp_mult = params.get("next_trade_secure_tp_mult", 1.3)
        size_ratio = params.get("next_trade_secure_size_ratio", 0.5)
        stop_dist = round(stop_dist * stop_mult, 2)
        limit_dist = round(limit_dist * tp_mult, 2)
        trade_size = round(trade_size * size_ratio, 2)
        logger.info(
            f"Next-trade secure: SL x{stop_mult} TP x{tp_mult} Size x{size_ratio}"
        )

    # -- Minimum distance floors --
    min_stop_floor = max(25.0, current_price * 0.013) if current_price > 0 else 25.0
    stop_dist = max(min_stop_floor, stop_dist)
    limit_dist = max(5.0, limit_dist)
    trade_size = max(0.1, min(4.0, trade_size))

    # -- R:R enforcement --
    rr = round(limit_dist / stop_dist, 2) if stop_dist > 0 else 0
    if rr < 1.0:
        limit_dist = round(stop_dist * 1.5, 2)
        rr = round(limit_dist / stop_dist, 2)

    ai_ref = f"OC_{trade_dir}_{int(confidence)}_{int(time.time())}"

    logger.info(
        f"ENTRY: {trade_dir} {trade_size} ETH | "
        f"SL={stop_dist}pts TP={limit_dist}pts RR={rr} | "
        f"conf={int(confidence)}%"
    )

    # -- Open position via IG --
    raw_result = ig_client.open_position(
        direction=trade_dir,
        size=trade_size,
        sl_pts=stop_dist,
        tp_pts=limit_dist,
    )
    # Convert OrderResult dataclass to dict for downstream .get() access
    result = raw_result.to_dict() if hasattr(raw_result, "to_dict") else (raw_result if isinstance(raw_result, dict) else {"success": False})

    if not result or not result.get("success"):
        err = str(
            result.get("error", "Unknown") if isinstance(result, dict) else "Unknown"
        )
        logger.error(f"ENTRY FAILED: {err}")
        return {"success": False, "error": err}

    # -- Success bookkeeping --
    deal_id = str(result.get("deal_id") or result.get("deal_reference") or "")
    state.last_trade_time = datetime.now()
    state.last_signal = trade_dir
    state.trades_executed += 1
    state.daily_trades += 1
    state.last_entry_pred_ts = pred_ts
    state.last_block_reason = "ENTRY_EXECUTED"

    logger.info(f"TRADE EXECUTED: {trade_dir} {trade_size} ETH | Deal: {deal_id}")

    # Track open timestamp
    if deal_id:
        from zoneinfo import ZoneInfo
        PARIS_TZ = ZoneInfo("Europe/Paris")
        state.open_timestamp_by_deal[deal_id] = datetime.now(PARIS_TZ).isoformat()

    # Store risk targets
    if deal_id:
        sl_eur = _estimate_eur_from_points(stop_dist, trade_size)
        tp_eur = _estimate_eur_from_points(limit_dist, trade_size)
        state.position_risk_targets[deal_id] = {
            "sl_points": round(stop_dist, 2),
            "tp_points": round(limit_dist, 2),
            "sl_eur": sl_eur,
            "tp_eur": tp_eur,
            "timestamp": pred_ts or int(time.time()),
        }

    # Apply next-trade-secure profile to the position
    if secure_next and deal_id:
        state.secure_gain_profile_by_deal[deal_id] = {
            "gain_trigger_ratio": params.get("next_trade_secure_gain_trigger_ratio", 0.3),
            "gain_lock_ratio": params.get("next_trade_secure_gain_lock_ratio", 0.5),
            "partial_min_profit_eur": params.get("next_trade_secure_partial_min_profit_eur", 5.0),
        }
        state.next_trade_secure_armed = False
        state.next_trade_secure_reason = ""
        logger.info(f"Secure profile APPLIED on {deal_id}")

    # -- MongoDB logging --
    if trade_repo is not None:
        try:
            trade_repo.log_trade_open(
                trade_id=deal_id,
                deal_id=deal_id,
                direction=trade_dir,
                size=trade_size,
                entry_price=current_price,
                sl_pts=stop_dist,
                tp_pts=limit_dist,
                rr_ratio=rr,
                ai_entry={
                    "action": str(prediction.get("action", "")),
                    "confidence": confidence,
                    "regime": str(prediction.get("regime", "")),
                    "direction": str(prediction.get("direction", "")),
                    "entry_mode": str(prediction.get("entry_mode", "")),
                    "thinking": state.last_claude_thinking[:200] if hasattr(state, 'last_claude_thinking') else "",
                    "reason": state.last_claude_reason[:150] if hasattr(state, 'last_claude_reason') else "",
                },
                market_at_entry={"price": current_price},
            )
        except Exception as e:
            logger.warning(f"MongoDB trade_open FAILED: {e}")

    return {
        "success": True,
        "deal_id": deal_id,
        "direction": trade_dir,
        "size": trade_size,
        "sl_pts": stop_dist,
        "tp_pts": limit_dist,
        "rr": rr,
        "secure_next": secure_next,
    }


# =========================================================================
# HELPERS
# =========================================================================

def _estimate_eur_from_points(pts: float, size: float) -> float:
    """ETH CFD: 1 point = $1 per lot ~ 1 EUR per lot."""
    return round(abs(float(pts or 0)) * abs(float(size or 0)), 2)
