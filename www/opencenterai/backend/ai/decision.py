"""
OpenCenterAI Trading - AI Decision Sanitizer
=============================================
Extracted from refonte_v2.py (2026-02-21).
Sanitizes and validates LLM output so the execution engine receives
deterministic, coherent fields.

Responsibilities:
- sanitize_ai_decision() - Clean/normalize Claude tool_use output
- evaluate_execution_firewall() - Hard firewall before trade execution
- Helper normalizers: _norm_action, _norm_bias, etc.

CRITICAL: NO signal inversion. LONG=LONG, SHORT=SHORT, WAIT=WAIT, EXIT=EXIT.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List


# ===================================================================
# HELPERS
# ===================================================================

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _i(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return int(default)
        return int(v)
    except Exception:
        return int(default)


def _u(v: Any, default: str = "") -> str:
    if v is None:
        return default
    txt = str(v).strip().upper()
    return txt if txt else default


# ===================================================================
# NORMALIZERS
# ===================================================================

def _norm_action(v: Any) -> str:
    """Normalize action string. NO signal inversion."""
    a = _u(v, "WAIT")
    if "PARTIAL_EXIT_LONG" in a:
        return "PARTIAL_EXIT_LONG"
    if "PARTIAL_EXIT_SHORT" in a:
        return "PARTIAL_EXIT_SHORT"
    if "PARTIAL_EXIT" in a or "PARTIAL" in a:
        return "PARTIAL_EXIT_LONG"  # default partial to long
    if "HEDGE_LONG" in a:
        return "HEDGE_LONG"
    if "HEDGE_SHORT" in a:
        return "HEDGE_SHORT"
    if "EXIT_LONG" in a or "EXIT LONG" in a:
        return "EXIT_LONG"
    if "EXIT_SHORT" in a or "EXIT SHORT" in a:
        return "EXIT_SHORT"
    if "QUITTER" in a:
        return "CLOSE"
    if "CLOSE" in a:
        return "CLOSE"
    if "KEEP" in a or "HOLD_POSITION" in a or "HOLD" in a:
        return "KEEP"
    if "LONG" in a or "BUY" in a:
        return "LONG"
    if "SHORT" in a or "SELL" in a:
        return "SHORT"
    return "WAIT"


def _norm_bias(v: Any) -> str:
    """Normalize direction/bias string."""
    t = _u(v, "NEUTRAL")
    if any(tok in t for tok in ("BEAR", "DOWN", "SHORT", "SELL")):
        return "BEAR"
    if any(tok in t for tok in ("BULL", "UP", "LONG", "BUY")):
        return "BULL"
    return "NEUTRAL"


def _side_from_trade_dir(trade_dir: str) -> str:
    return "LONG" if str(trade_dir).upper() == "BUY" else "SHORT"


# ===================================================================
# MAIN SANITIZER
# ===================================================================

def sanitize_ai_decision(
    ai_data: Dict[str, Any],
    snapshot: Dict[str, Any],
    position_direction: str = "",
    prev_action: str = "",
    prev_action_ts: float = 0.0,
) -> Dict[str, Any]:
    """
    Sanitize LLM output so execution receives deterministic, coherent fields.

    Guards:
    - GUARD A: min confidence 40 for entries (LONG/SHORT)
    - GUARD B: min confidence 50 for exits (EXIT_LONG/EXIT_SHORT)
    - GUARD C: anti-flip-flop temporal (LONG->SHORT in < 60s)
    - Position context: converts LONG/SHORT to EXIT/KEEP when position is open

    CRITICAL: NO signal inversion. LONG=LONG, SHORT=SHORT.
    """
    raw = ai_data if isinstance(ai_data, dict) else {}
    out: Dict[str, Any] = {}

    last_close = _f(snapshot.get("last_close"), 0.0)
    atr = max(0.0, _f(snapshot.get("atr"), 0.0))
    min_conf = _i(snapshot.get("min_confidence"), 60)
    min_size = max(0.1, _f(snapshot.get("min_position_size"), 1.0))
    max_size = max(min_size, _f(snapshot.get("max_position_size"), 2.0))
    rec_stop_mult = _clamp(_f(snapshot.get("rec_stop_mult"), 1.0), 0.7, 1.7)
    rec_target_mult = _clamp(_f(snapshot.get("rec_target_mult"), 1.7), 1.2, 3.0)

    action = _norm_action(raw.get("action", "WAIT"))

    # === GUARD 1: Position open -- convert LONG/SHORT to EXIT/KEEP ===
    _pos_dir = str(position_direction).upper().strip()
    if _pos_dir and _pos_dir not in ("", "NONE") and action in ("LONG", "SHORT"):
        if _pos_dir in ("BUY", "LONG") and action == "SHORT":
            action = "EXIT_LONG"
        elif _pos_dir in ("SELL", "SHORT") and action == "LONG":
            action = "EXIT_SHORT"
        elif _pos_dir in ("BUY", "LONG") and action == "LONG":
            action = "KEEP"
        elif _pos_dir in ("SELL", "SHORT") and action == "SHORT":
            action = "KEEP"

    # === Regime ===
    regime = _u(raw.get("regime", "TRANSITION"), "TRANSITION")
    if regime not in {"TREND_UP", "TREND_DOWN", "RANGE", "TRANSITION"}:
        regime = "TRANSITION"

    # === Confidence ===
    confidence = _i(raw.get("confidence"), 0)
    confidence = int(_clamp(float(confidence), 0.0, 100.0))

    # === GUARD A: Min confidence for entries (40% floor) ===
    if action in ("LONG", "SHORT") and confidence < 40:
        action = "WAIT"

    # === GUARD B: EXIT must have min confidence 50% ===
    if action in ("EXIT_LONG", "EXIT_SHORT") and confidence < 50:
        action = "KEEP"

    # === GUARD C: Anti-flip direction (LONG->SHORT in < 60s) ===
    _prev = str(prev_action).upper().strip()
    _now_ts = time.time()
    _elapsed = _now_ts - prev_action_ts if prev_action_ts > 0 else 9999

    if _prev and _elapsed > 0:
        if _prev == "LONG" and action == "SHORT" and _elapsed < 60:
            action = "WAIT"
        elif _prev == "SHORT" and action == "LONG" and _elapsed < 60:
            action = "WAIT"

    # === Trend strength ===
    trend_strength = _i(raw.get("trend_strength"), _i(snapshot.get("trend_score"), 0))
    trend_strength = int(_clamp(float(trend_strength), 0.0, 100.0))

    # === Scores ===
    score_long = int(_clamp(float(_i(raw.get("score_long"), 0)), 0.0, 100.0))
    score_short = int(_clamp(float(_i(raw.get("score_short"), 0)), 0.0, 100.0))
    if score_long == 0 and score_short == 0:
        if action == "LONG":
            score_long = int(_clamp(max(52, confidence), 0.0, 100.0))
            score_short = int(_clamp(100 - score_long, 0.0, 100.0))
        elif action == "SHORT":
            score_short = int(_clamp(max(52, confidence), 0.0, 100.0))
            score_long = int(_clamp(100 - score_short, 0.0, 100.0))
        else:
            score_long = 48
            score_short = 48

    # === Wait reason ===
    wait_reason = _u(raw.get("wait_reason_code", "NONE"), "NONE")
    if wait_reason not in {
        "NONE", "LOW_EDGE", "CONFLICT", "LATE_ENTRY", "LOW_VOLUME",
        "REVERSAL_RISK", "MTF_CONFLICT", "COUNTER_TREND", "NO_SETUP",
        "RANGE_BOUND", "OTHER",
    }:
        wait_reason = "OTHER"

    # === Direction ===
    direction = _u(raw.get("direction", "NEUTRAL"), "NEUTRAL")
    if action in {"LONG"}:
        direction = "BULLISH"
    elif action in {"SHORT"}:
        direction = "BEARISH"
    elif action in {"WAIT", "KEEP", "CLOSE", "EXIT_LONG", "EXIT_SHORT"}:
        direction = "NEUTRAL"

    # === Entry mode (accepts RANGE_BOUNCE) ===
    entry_mode = _u(raw.get("entry_mode", "NONE"), "NONE")
    if entry_mode not in {"BREAKOUT", "PULLBACK", "RANGE_BOUNCE", "MEAN_REVERSION", "NONE"}:
        entry_mode = "NONE"

    # === Position advice ===
    position_advice = _u(raw.get("position_advice", "KEEP"), "KEEP")
    if position_advice not in {"KEEP", "QUITTER", "SECURISER", "HEDGE"}:
        position_advice = "KEEP"

    # === Low-edge neutralization ===
    if action in {"LONG", "SHORT"}:
        edge_now = abs(score_long - score_short)
        dir_score = score_long if action == "LONG" else score_short
        if confidence < 40 and dir_score < 50 and edge_now < 4:
            action = "WAIT"
            direction = "NEUTRAL"
            wait_reason = "LOW_EDGE"

    # === Position size ===
    size = _f(raw.get("size"), min_size)
    size = _clamp(size, min_size, max_size)

    # === Adaptive risk shaping from recent execution behavior (non-blocking) ===
    learn_short_loss = _i(snapshot.get("trade_learning_short_loss_6m"), 0)
    learn_flip_after_win = _i(snapshot.get("trade_learning_flip_after_win_20m"), 0)
    if action in {"LONG", "SHORT"}:
        adapt_pressure = 0
        if learn_short_loss >= 3:
            adapt_pressure += 1
        if learn_flip_after_win >= 2:
            adapt_pressure += 1
        if adapt_pressure > 0:
            confidence = int(_clamp(float(confidence - (2 * adapt_pressure)), 0.0, 100.0))
            cap_ratio = 0.55 if adapt_pressure >= 2 else 0.75
            size_cap = min_size + ((max_size - min_size) * cap_ratio)
            size = min(size, size_cap)

    if action == "WAIT":
        size = min_size

    # === Target & Stop ===
    target = _f(raw.get("target"), 0.0)
    stop = _f(raw.get("stop"), 0.0)
    invalidation = _f(raw.get("invalidation_level"), 0.0)
    if invalidation > 0 and stop <= 0:
        stop = invalidation

    if last_close > 0 and atr > 0:
        stop_dist = _clamp(rec_stop_mult * atr, 0.8 * atr, 1.5 * atr)
        target_dist = _clamp(rec_target_mult * atr, 1.2 * atr, 2.5 * atr)
        if action == "LONG":
            if target <= last_close:
                target = last_close + target_dist
            if stop >= last_close or stop <= 0:
                stop = last_close - stop_dist
            rr = (target - last_close) / max(1e-9, last_close - stop)
            if rr < 1.3:
                target = last_close + ((last_close - stop) * 1.3)
        elif action == "SHORT":
            if target >= last_close or target <= 0:
                target = last_close - target_dist
            if stop <= last_close or stop <= 0:
                stop = last_close + stop_dist
            rr = (last_close - target) / max(1e-9, stop - last_close)
            if rr < 1.3:
                target = last_close - ((stop - last_close) * 1.3)
        else:
            target = 0.0
            stop = 0.0

    # === Reason & thinking ===
    reason = str(raw.get("reason", "") or "").strip()
    if not reason:
        reason = "Chartist analysis: structure + S/R zones + patterns + confluence."
    reason = reason[:180]

    thinking = str(raw.get("thinking", "") or "").strip()[:400]

    # === Trigger snapshot (fallback uses snapshot data) ===
    trigger_snapshot = str(raw.get("trigger_snapshot", "") or "").strip()[:220]
    if not trigger_snapshot:
        _snap_mtf_bias = _u(snapshot.get("mtf_bias"), "NEUTRAL")
        _snap_mtf_score = _f(snapshot.get("mtf_score"), 50.0)
        _snap_prec_side = _u(snapshot.get("precision_consensus_side"), "NONE")
        _snap_prec_str = _i(snapshot.get("precision_consensus_strength"), 0)
        _snap_chart_bias = _u(snapshot.get("chart_pattern_bias"), "NEUTRAL")
        _snap_chart_str = _i(snapshot.get("chart_pattern_strength"), 0)
        trigger_snapshot = (
            f"mtf={_snap_mtf_bias}:{round(_snap_mtf_score, 1)} "
            f"prec={_snap_prec_side}:{_snap_prec_str} "
            f"chart={_snap_chart_bias}:{_snap_chart_str}"
        )[:220]

    # === Horizon forecast ===
    horizon_forecast = raw.get("horizon_forecast", {})
    if isinstance(horizon_forecast, dict):
        for k in ("15m", "30m", "1h", "4h"):
            v = _u(horizon_forecast.get(k), "NEUTRAL")
            if v not in ("BULL", "BEAR", "NEUTRAL"):
                v = "NEUTRAL"
            horizon_forecast[k] = v
    else:
        horizon_forecast = {"15m": "NEUTRAL", "30m": "NEUTRAL", "1h": "NEUTRAL", "4h": "NEUTRAL"}

    out.update({
        "regime": regime,
        "direction": direction,
        "action": action,
        "trend_strength": trend_strength,
        "confidence": confidence,
        "entry_mode": entry_mode,
        "position_advice": position_advice,
        "score_long": score_long,
        "score_short": score_short,
        "wait_reason_code": wait_reason,
        "trigger_snapshot": trigger_snapshot,
        "horizon_forecast": horizon_forecast,
        "thinking": thinking,
        "reason": reason,
        "size": round(float(size), 2),
        "target": round(float(target), 2),
        "stop": round(float(stop), 2),
        "invalidation_level": round(float(stop), 2),
    })
    return out


# ===================================================================
# EXECUTION FIREWALL
# ===================================================================

def evaluate_execution_firewall(
    prediction: Dict[str, Any],
    precision_ctx: Dict[str, Any],
    trade_dir: str,
    probability: int,
) -> Dict[str, Any]:
    """
    Single hard firewall before execution.
    Requires confluence support and rejects strong contradictions.
    Claude is the primary decision maker -- firewall only blocks clear errors.
    """
    pred = prediction if isinstance(prediction, dict) else {}
    pctx = precision_ctx if isinstance(precision_ctx, dict) else {}
    out = {
        "allow": True,
        "block_reason": "",
        "support_votes": 0,
        "oppose_votes": 0,
        "required_votes": 3,
        "notes": [],
    }

    side = _side_from_trade_dir(trade_dir)
    score_long = _i(pred.get("score_long"), 0)
    score_short = _i(pred.get("score_short"), 0)
    edge = abs(score_long - score_short)
    mtf_bias = _norm_bias(pred.get("mtf_bias", "NEUTRAL"))
    mtf_score = _f(pred.get("mtf_score"), 50.0)
    impulse_dir = _norm_bias(pred.get("impulse_dir", "NEUTRAL"))
    impulse_atr = abs(_f(pred.get("impulse_atr"), 0.0))
    of_bias = _norm_bias(pred.get("orderflow_bias", "NEUTRAL"))
    of_strength = _i(pred.get("orderflow_strength"), 0)
    chart_bias = _norm_bias(pctx.get("chart_pattern_bias", pred.get("chart_pattern_bias", "NEUTRAL")))
    chart_strength = _i(pctx.get("chart_pattern_strength", pred.get("chart_pattern_strength", 0)))
    precision_side = _u(pctx.get("consensus_side", "NONE"), "NONE")
    precision_strength = _i(pctx.get("consensus_strength", 0), 0)
    precision_timing = _i(pctx.get("timing_score", pred.get("precision_timing_score", 0)), 0)
    precision_latency = _i(pctx.get("latency_risk", pred.get("precision_latency_risk", 100)), 100)
    hard_reason = str(pctx.get("hard_block_reason", "") or "").strip()
    rev_risk = _f(pred.get("reversal_risk_long" if side == "LONG" else "reversal_risk_short"), 0.0)

    support = 0
    oppose = 0
    notes: List[str] = []

    # Hard contradictions
    if side == "LONG" and mtf_bias == "BEAR" and mtf_score < 42:
        out.update({"allow": False, "block_reason": "FW_MTF_OPPOSE_LONG"})
        return out
    if side == "SHORT" and mtf_bias == "BULL" and mtf_score > 58:
        out.update({"allow": False, "block_reason": "FW_MTF_OPPOSE_SHORT"})
        return out
    if hard_reason:
        out.update({"allow": False, "block_reason": f"FW_PRECISION_{hard_reason}"})
        return out
    if side == "LONG" and chart_bias == "BEAR" and chart_strength >= 75:
        out.update({"allow": False, "block_reason": "FW_CHART_OPPOSE_LONG"})
        return out
    if side == "SHORT" and chart_bias == "BULL" and chart_strength >= 75:
        out.update({"allow": False, "block_reason": "FW_CHART_OPPOSE_SHORT"})
        return out
    if rev_risk >= 85:
        out.update({"allow": False, "block_reason": "FW_REVERSAL_EXTREME"})
        return out

    # Votes
    if side == "LONG":
        if score_long >= max(58, score_short + 8):
            support += 1
            notes.append("score")
        else:
            oppose += 1
        if precision_side == "LONG" and precision_strength >= 65 and precision_timing >= 50 and precision_latency <= 70:
            support += 1
            notes.append("precision")
        elif precision_side == "SHORT" and precision_strength >= 65:
            oppose += 1
        if mtf_bias == "BULL" and mtf_score >= 55:
            support += 1
            notes.append("mtf")
        elif mtf_bias == "BEAR" and mtf_score <= 45:
            oppose += 1
        if chart_bias == "BULL" and chart_strength >= 52:
            support += 1
            notes.append("chart")
        elif chart_bias == "BEAR" and chart_strength >= 52:
            oppose += 1
        if of_bias == "BULL" and of_strength >= 58:
            support += 1
            notes.append("orderflow")
        elif of_bias == "BEAR" and of_strength >= 58:
            oppose += 1
        if impulse_dir == "BULL" and impulse_atr >= 0.35:
            support += 1
            notes.append("impulse")
        elif impulse_dir == "BEAR" and impulse_atr >= 0.35:
            oppose += 1
    else:
        if score_short >= max(58, score_long + 8):
            support += 1
            notes.append("score")
        else:
            oppose += 1
        if precision_side == "SHORT" and precision_strength >= 65 and precision_timing >= 50 and precision_latency <= 70:
            support += 1
            notes.append("precision")
        elif precision_side == "LONG" and precision_strength >= 65:
            oppose += 1
        if mtf_bias == "BEAR" and mtf_score <= 45:
            support += 1
            notes.append("mtf")
        elif mtf_bias == "BULL" and mtf_score >= 55:
            oppose += 1
        if chart_bias == "BEAR" and chart_strength >= 52:
            support += 1
            notes.append("chart")
        elif chart_bias == "BULL" and chart_strength >= 52:
            oppose += 1
        if of_bias == "BEAR" and of_strength >= 58:
            support += 1
            notes.append("orderflow")
        elif of_bias == "BULL" and of_strength >= 58:
            oppose += 1
        if impulse_dir == "BEAR" and impulse_atr >= 0.35:
            support += 1
            notes.append("impulse")
        elif impulse_dir == "BULL" and impulse_atr >= 0.35:
            oppose += 1

    # Firewall -- Claude is the primary decision maker, not the firewall
    min_prob = 58
    if support >= 3:
        min_prob = 55
    if support < 2 and edge < 6:
        out.update({
            "allow": False,
            "block_reason": f"FW_WEAK_CONFLUENCE:support={support}:edge={edge}",
        })
    elif oppose >= 4 and support < 3:
        out.update({
            "allow": False,
            "block_reason": f"FW_OPPOSE_STACK:oppose={oppose}:support={support}",
        })
    elif int(probability or 0) < min_prob:
        out.update({
            "allow": False,
            "block_reason": f"FW_PROB_LOW:{int(probability or 0)}<{min_prob}",
        })

    out["support_votes"] = int(support)
    out["oppose_votes"] = int(oppose)
    out["notes"] = notes[:6]
    return out


# ===================================================================
# VALIDATION HELPER
# ===================================================================

def validate_decision(decision: Dict[str, Any]) -> bool:
    """Quick check that a sanitized decision has all required fields."""
    required = {
        "regime", "direction", "action", "confidence",
        "score_long", "score_short", "size", "target", "stop",
    }
    return all(k in decision for k in required)
