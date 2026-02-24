"""
core/risk.py -- Risk management
=================================
Pure functions for risk computation. No side-effects, no I/O.

Functions:
    - compute_trailing_level()   -- Multi-tier trailing stop computation
    - should_lock_gains()        -- Check if gain lock should trigger
    - compute_dynamic_sl_tp()    -- ATR/regime-based SL/TP
    - get_drawdown_confidence_boost() -- Raise min confidence when losing
    - check_daily_limit()        -- Daily loss limit check
    - is_next_trade_secure_triggered() -- Arm next-trade-secure after big loss
    - apply_next_trade_secure_params() -- Modify params for protected trade
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =========================================================================
# TRAILING LEVEL COMPUTATION
# =========================================================================

# Default trailing tiers: (gain_pct_of_entry, lock_pct_of_profit)
DEFAULT_TRAILING_TIERS = [
    (0.005, 0.0),    # +0.5% -> breakeven
    (0.008, 0.35),   # +0.8% -> lock 35%
    (0.012, 0.45),   # +1.2% -> lock 45%
    (0.018, 0.55),   # +1.8% -> lock 55%
    (0.025, 0.65),   # +2.5% -> lock 65%
    (0.035, 0.70),   # +3.5% -> lock 70%
]


def compute_trailing_level(
    entry_price: float,
    direction: str,
    current_price: float,
    peak_pnl: float,
    params: Dict[str, Any],
    prev_trailing: Optional[float] = None,
) -> Optional[float]:
    """
    Compute the trailing stop price level using multi-tier progressive system.

    Uses TRAILING_TIERS from params (or defaults). Each tier defines a
    gain threshold (as % of entry price in points) and the % of profit
    to lock at that tier. Interpolation between tiers for smooth trailing.

    Returns the trailing stop price level, or None if profit is too low.
    The returned value only moves in the protective direction (up for BUY,
    down for SELL) -- it never widens.
    """
    if entry_price <= 0 or current_price <= 0:
        return None

    # Profit in points
    if direction == "BUY":
        profit_pts = current_price - entry_price
    elif direction == "SELL":
        profit_pts = entry_price - current_price
    else:
        return None

    if profit_pts <= 0:
        return None

    # Build dynamic tiers from params or use defaults
    trailing_tiers_pct = params.get("trailing_tiers", DEFAULT_TRAILING_TIERS)
    ref_price = max(1.0, entry_price)

    # Convert % tiers to absolute point tiers
    trail_tiers = [
        (ref_price * pct, lock_pct)
        for pct, lock_pct in trailing_tiers_pct
    ]

    # Find the highest tier reached
    best_lock_pct = -1.0
    best_tier_pts = 0.0
    for tier_pts, tier_pct in trail_tiers:
        if profit_pts >= tier_pts:
            best_lock_pct = tier_pct
            best_tier_pts = tier_pts

    if best_lock_pct < 0:
        return None

    # Interpolation between tiers for smooth trailing
    next_tier_pct = best_lock_pct
    next_tier_pts = best_tier_pts
    for tier_pts, tier_pct in trail_tiers:
        if tier_pts > best_tier_pts:
            next_tier_pts = tier_pts
            next_tier_pct = tier_pct
            break

    if next_tier_pts > best_tier_pts and profit_pts > best_tier_pts:
        progress = min(
            1.0,
            (profit_pts - best_tier_pts) / (next_tier_pts - best_tier_pts),
        )
        lock_pct = best_lock_pct + (next_tier_pct - best_lock_pct) * progress
    else:
        lock_pct = best_lock_pct

    lock_pts = profit_pts * lock_pct

    # Compute trail stop price
    if direction == "BUY":
        trail_stop = entry_price + lock_pts
        if prev_trailing is not None:
            trail_stop = max(trail_stop, prev_trailing)
    else:  # SELL
        trail_stop = entry_price - lock_pts
        if prev_trailing is not None:
            trail_stop = min(trail_stop, prev_trailing)

    return round(trail_stop, 2)


# =========================================================================
# GAIN LOCK CHECK
# =========================================================================

def should_lock_gains(
    pnl: float,
    tp_eur_target: float,
    prev_lock_eur: float,
    params: Dict[str, Any],
    secure_profile: Optional[Dict] = None,
) -> bool:
    """
    Check whether gain lock should trigger for a position.

    Returns True if PnL has reached the trigger threshold and the lock
    amount is materially higher than the previous lock.
    """
    if not params.get("preserve_gains_enabled", True) or tp_eur_target <= 0:
        return False

    if pnl <= 0:
        return False

    # Override from secure profile
    trigger_ratio = params.get("preserve_gain_trigger_ratio", 0.4)
    lock_ratio = params.get("preserve_gain_lock_ratio", 0.5)
    if secure_profile:
        trigger_ratio = float(secure_profile.get("gain_trigger_ratio", trigger_ratio))
        lock_ratio = float(secure_profile.get("gain_lock_ratio", lock_ratio))

    trigger_eur = tp_eur_target * max(0.05, min(1.0, trigger_ratio))
    if pnl < trigger_eur:
        return False

    lock_eur = max(0.0, pnl * max(0.05, min(1.0, lock_ratio)))
    return lock_eur > prev_lock_eur + 2.0


# =========================================================================
# DYNAMIC SL / TP COMPUTATION
# =========================================================================

def compute_dynamic_sl_tp(
    entry_price: float,
    direction: str,
    atr: float,
    regime: str,
    params: Dict[str, Any],
) -> Tuple[float, float]:
    """
    Compute SL/TP in absolute price levels using ATR and market regime.

    Returns (stop_loss_price, take_profit_price).
    """
    # Minimum SL floor
    min_sl_pts = max(25.0, entry_price * 0.013) if entry_price > 0 else 25.0

    if atr > 0 and params.get("ai_autonomous_risk_enabled", True):
        sl_atr_mult = params.get("ai_autonomous_sl_atr_mult", 1.5)
        sl_pts = max(min_sl_pts, atr * sl_atr_mult)

        rr_map = {
            "TREND_UP": params.get("ai_autonomous_tp_rr_trend", 2.0),
            "TREND_DOWN": params.get("ai_autonomous_tp_rr_trend", 2.0),
            "RANGE": params.get("ai_autonomous_tp_rr_range", 1.5),
            "TRANSITION": params.get("ai_autonomous_tp_rr_transition", 1.8),
        }
        min_rr = params.get("ai_autonomous_min_rr", 1.2)
        max_rr = params.get("ai_autonomous_max_rr", 4.0)
        rr = rr_map.get(regime.upper(), params.get("ai_autonomous_tp_rr_transition", 1.8))
        rr = max(min_rr, min(max_rr, rr))
        tp_pts = sl_pts * rr
    else:
        # PCT fallback
        sl_pct = params.get("sl_pct", 0.01)
        tp_pct = params.get("tp_pct", 0.02)
        sl_pts = max(min_sl_pts, entry_price * sl_pct)
        tp_pts = max(min_sl_pts, entry_price * tp_pct)

    # Convert to absolute prices
    if direction == "BUY":
        sl_price = entry_price - sl_pts
        tp_price = entry_price + tp_pts
    else:  # SELL
        sl_price = entry_price + sl_pts
        tp_price = entry_price - tp_pts

    return round(sl_price, 2), round(tp_price, 2)


# =========================================================================
# DRAWDOWN CONFIDENCE BOOST
# =========================================================================

def get_drawdown_confidence_boost(
    daily_pnl: float,
    tiers: List[Tuple[float, int]],
) -> int:
    """
    Return the additional confidence points required based on daily drawdown.

    ``tiers`` is a list of (pnl_threshold, boost_points). For each tier
    where daily_pnl <= threshold, the boost is added cumulatively.

    Example tiers: [(-20, 5), (-40, 10), (-60, 15)]
    If daily_pnl = -45 -> boost = 5 + 10 = 15 (first two tiers triggered)
    """
    total_boost = 0
    for threshold, boost in tiers:
        if daily_pnl <= threshold:
            total_boost += boost
    return total_boost


# =========================================================================
# DAILY LIMIT CHECK
# =========================================================================

def check_daily_limit(daily_pnl: float, limit: float) -> bool:
    """
    Check if the daily loss limit has been hit.
    Returns True if trading should STOP (limit breached).
    """
    if limit <= 0:
        return False
    return daily_pnl <= -limit


# =========================================================================
# NEXT TRADE SECURE
# =========================================================================

def is_next_trade_secure_triggered(
    last_loss_eur: float,
    threshold: float,
) -> bool:
    """
    Check if a loss is large enough to arm next-trade-secure mode.
    ``last_loss_eur`` should be the absolute value of the loss.
    """
    return abs(last_loss_eur) >= threshold


def apply_next_trade_secure_params(
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a modified copy of params with next-trade-secure adjustments.
    Reduces position size, tightens SL, extends TP.

    Keys used from params:
        next_trade_secure_size_ratio, next_trade_secure_stop_mult,
        next_trade_secure_tp_mult, position_size_eth,
        stop_distance_pts, limit_distance_pts
    """
    modified = dict(params)

    size_ratio = params.get("next_trade_secure_size_ratio", 0.5)
    stop_mult = params.get("next_trade_secure_stop_mult", 0.7)
    tp_mult = params.get("next_trade_secure_tp_mult", 1.3)

    # Apply multipliers
    orig_size = params.get("position_size_eth", 2.0)
    modified["position_size_eth"] = round(orig_size * size_ratio, 2)

    orig_stop = params.get("stop_distance_pts", 30.0)
    modified["stop_distance_pts"] = round(orig_stop * stop_mult, 2)

    orig_limit = params.get("limit_distance_pts", 60.0)
    modified["limit_distance_pts"] = round(orig_limit * tp_mult, 2)

    # Gain lock overrides
    modified["preserve_gain_trigger_ratio"] = params.get(
        "next_trade_secure_gain_trigger_ratio", 0.3
    )
    modified["preserve_gain_lock_ratio"] = params.get(
        "next_trade_secure_gain_lock_ratio", 0.5
    )
    modified["partial_exit_min_profit_eur"] = params.get(
        "next_trade_secure_partial_min_profit_eur", 5.0
    )

    logger.info(
        f"Next-trade-secure params: size {orig_size}->{modified['position_size_eth']} "
        f"SL {orig_stop}->{modified['stop_distance_pts']} "
        f"TP {orig_limit}->{modified['limit_distance_pts']}"
    )

    return modified


# =========================================================================
# HELPERS
# =========================================================================

def estimate_eur_from_points(pts: float, size: float) -> float:
    """ETH CFD: 1 point = $1 per lot ~ 1 EUR per lot."""
    return round(abs(float(pts or 0)) * abs(float(size or 0)), 2)


def position_age_sec(pos: Dict) -> int:
    """Age of a position in seconds."""
    from datetime import datetime
    try:
        created = pos.get("created_date_utc") or pos.get("created_date") or ""
        if not created:
            return 0
        if isinstance(created, str):
            for fmt in (
                "%Y-%m-%dT%H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
            ):
                try:
                    dt = datetime.strptime(created[:19], fmt[:19])
                    return max(0, int((datetime.utcnow() - dt).total_seconds()))
                except Exception:
                    continue
        return 0
    except Exception:
        return 0
