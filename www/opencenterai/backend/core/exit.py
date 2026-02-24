"""
core/exit.py -- All exit mechanisms
=====================================
Extracted from trading_engine.py (lines 678-1398).

4 EXIT MECHANISMS (priority order):
    1. HARD LOSS CAP   -- PnL <= -(hard_loss_cap_pct * size * entry_price)
    2. AI EXIT         -- Claude says EXIT/QUITTER -> immediate close, ZERO guards
    3. TRAILING EXIT   -- Software-based trailing using multi-tier system
    4. PROFIT RETRACE  -- Peak >= min_peak, drop >= force_drop_ratio

Additional exits:
    - AI BLIND EXIT    -- Protection when AI is unavailable
    - PARTIAL EXIT     -- Close portion to secure profits, keep remainder
    - GAIN LOCK        -- Tighten stop to lock in gains
    - FLATTEN PRE-CLOSE -- Close all before IG weekly close
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from core.state import EngineState

logger = logging.getLogger(__name__)

PARIS_TZ = ZoneInfo("Europe/Paris")


# =========================================================================
# EXIT ORCHESTRATOR
# =========================================================================

def check_exits(
    pos: Dict[str, Any],
    state: EngineState,
    params: Dict[str, Any],
    prediction: Dict[str, Any],
    ig_client,
    *,
    trade_repo=None,
) -> Optional[str]:
    """
    Orchestrate all exit checks for a single position (priority order).
    Returns the exit reason string if position was closed, else None.

    Called every loop iteration (~5s) for each open position.
    """
    deal_id = str(pos.get("deal_id") or "")
    if not deal_id:
        return None
    direction = str(pos.get("direction", "")).upper()
    if direction not in ("BUY", "SELL"):
        return None

    size = float(pos.get("size", 0) or 0)
    pnl = float(pos.get("profit_loss", 0) or 0)
    current_price = float(pos.get("current_level", 0) or 0)

    if size <= 0 or current_price <= 0:
        return None

    # Track peak / trough PnL
    prev_peak = state.max_unrealized_by_deal.get(deal_id, 0.0)
    if pnl > prev_peak:
        state.max_unrealized_by_deal[deal_id] = pnl
    prev_trough = state.min_unrealized_by_deal.get(deal_id, 0.0)
    if pnl < prev_trough:
        state.min_unrealized_by_deal[deal_id] = pnl

    # -- 1. HARD LOSS CAP --
    reason = _check_hard_loss_cap(pos, state, params, ig_client, trade_repo=trade_repo)
    if reason:
        return reason

    # -- 2. AI EXIT (ZERO guards) --
    reason = _check_ai_exit(pos, prediction, state, params, ig_client, trade_repo=trade_repo)
    if reason:
        return reason

    # -- 3. AI BLIND EXIT --
    reason = _check_ai_blind_exit(pos, state, params, ig_client, trade_repo=trade_repo)
    if reason:
        return reason

    # -- 4. TRAILING STOP: update levels + check exit --
    _update_trailing_stop(pos, current_price, direction, deal_id, state)
    reason = _check_trailing_exit(
        pos, ig_client, current_price, direction, deal_id, pnl, size,
        state, params, trade_repo=trade_repo,
    )
    if reason:
        return reason

    # -- 5. PROFIT RETRACE --
    reason = _check_profit_retrace(
        pos, ig_client, deal_id, pnl, direction, size,
        state, params, trade_repo=trade_repo,
    )
    if reason:
        return reason

    # -- 6. PARTIAL EXIT --
    _maybe_partial_exit(
        pos, ig_client, deal_id, direction, size, pnl,
        state, params, trade_repo=trade_repo,
    )

    # -- 7. GAIN LOCK --
    tp_eur = float(
        state.position_risk_targets.get(deal_id, {}).get("tp_eur", 0) or 0
    )
    _maybe_lock_gains(ig_client, pos, tp_eur, state, params)

    return None


# =========================================================================
# 1. HARD LOSS CAP
# =========================================================================

def _check_hard_loss_cap(
    pos: Dict, state: EngineState, params: Dict, ig_client,
    *, trade_repo=None,
) -> Optional[str]:
    """
    Safety net: loss >= hard_loss_cap_pct * size * entry_price -> immediate close.
    """
    pnl = float(pos.get("profit_loss", 0) or 0)
    if pnl >= 0:
        return None

    deal_id = str(pos.get("deal_id", ""))
    size = float(pos.get("size", 0) or 0)
    entry_price = float(
        pos.get("level", 0) or pos.get("open_level", 0) or 0
    )
    direction = str(pos.get("direction", "")).upper()

    hard_loss_cap_pct = params.get("hard_loss_cap_pct", 0.02)
    hard_loss_cap_eur = params.get("hard_loss_cap_eur", 80.0)

    if size > 0 and entry_price > 0:
        cap = max(10.0, size * entry_price * hard_loss_cap_pct)
    else:
        cap = hard_loss_cap_eur

    if pnl > -cap:
        return None

    logger.info(
        f"HARD LOSS CAP: {deal_id} at {round(pnl, 2)}EUR "
        f"(cap=-{round(cap, 2)}EUR [{hard_loss_cap_pct*100}% x {size}ETH x {round(entry_price, 1)}])"
    )

    close_position(
        ig_client=ig_client, deal_id=deal_id, direction=direction,
        size=size, pnl=pnl, reason="HARD_LOSS_CAP",
        state=state, params=params, trade_repo=trade_repo,
    )
    return "HARD_LOSS_CAP"


# =========================================================================
# 2. AI EXIT -- Claude says EXIT/QUITTER -> ZERO guards
# =========================================================================

def _check_ai_exit(
    pos: Dict, prediction: Dict, state: EngineState, params: Dict, ig_client,
    *, trade_repo=None,
) -> Optional[str]:
    """
    AI EXIT -- Claude says EXIT/QUITTER -> close IMMEDIATE.
    ZERO guards. ZERO minimum age. ZERO marker check.
    """
    advice = str(prediction.get("position_advice", "KEEP")).upper()
    action = str(prediction.get("action", "WAIT")).upper()

    deal_id = str(pos.get("deal_id", ""))
    direction = str(pos.get("direction", "")).upper()
    size = float(pos.get("size", 0) or 0)
    pnl = float(pos.get("profit_loss", 0) or 0)

    # QUITTER = immediate close
    if advice == "QUITTER":
        logger.info(
            f"AI EXIT (QUITTER): {deal_id} pnl={round(pnl, 2)}EUR -> close immediate"
        )
        close_position(
            ig_client=ig_client, deal_id=deal_id, direction=direction,
            size=size, pnl=pnl, reason="AI_EXIT_QUITTER",
            state=state, params=params, trade_repo=trade_repo,
        )
        return "AI_EXIT_QUITTER"

    # EXIT_LONG / EXIT_SHORT = immediate close
    if (
        (direction == "BUY" and action == "EXIT_LONG")
        or (direction == "SELL" and action == "EXIT_SHORT")
    ):
        logger.info(
            f"AI EXIT ({action}): {deal_id} pnl={round(pnl, 2)}EUR -> close immediate"
        )
        close_position(
            ig_client=ig_client, deal_id=deal_id, direction=direction,
            size=size, pnl=pnl, reason=f"AI_EXIT_{action}",
            state=state, params=params, trade_repo=trade_repo,
        )
        return f"AI_EXIT_{action}"

    # SECURISER = partial exit (close portion)
    partial_exit_enabled = params.get("partial_exit_enabled", True)
    partial_min_remaining = params.get("partial_exit_min_remaining_eth", 0.5)
    partial_min_close = params.get("partial_exit_min_close_eth", 0.5)
    partial_size_step = params.get("partial_exit_size_step", 1.0)

    if advice == "SECURISER" and partial_exit_enabled:
        if size > partial_min_remaining + partial_min_close:
            close_size = min(partial_size_step, size - partial_min_remaining)
            if close_size >= partial_min_close:
                logger.info(
                    f"AI SECURISER: {deal_id} pnl={round(pnl, 2)}EUR "
                    f"-> partial close {close_size} ETH"
                )
                close_position(
                    ig_client=ig_client, deal_id=deal_id, direction=direction,
                    size=close_size, pnl=pnl, reason="AI_SECURISER",
                    state=state, params=params, trade_repo=trade_repo,
                    partial=True, full_size=size,
                )
                return "AI_SECURISER"

    # PARTIAL_EXIT_LONG / PARTIAL_EXIT_SHORT
    if (
        (direction == "BUY" and action == "PARTIAL_EXIT_LONG")
        or (direction == "SELL" and action == "PARTIAL_EXIT_SHORT")
    ):
        if size > partial_min_remaining + partial_min_close:
            close_size = min(partial_size_step, size - partial_min_remaining)
            if close_size >= partial_min_close:
                logger.info(
                    f"AI PARTIAL ({action}): {deal_id} pnl={round(pnl, 2)}EUR "
                    f"-> close {close_size} ETH"
                )
                close_position(
                    ig_client=ig_client, deal_id=deal_id, direction=direction,
                    size=close_size, pnl=pnl, reason=f"AI_{action}",
                    state=state, params=params, trade_repo=trade_repo,
                    partial=True, full_size=size,
                )
                return f"AI_{action}"

    return None


# =========================================================================
# 3. AI BLIND EXIT -- protection when AI unavailable
# =========================================================================

def _check_ai_blind_exit(
    pos: Dict, state: EngineState, params: Dict, ig_client,
    *, trade_repo=None,
) -> Optional[str]:
    """
    AI BLIND EXIT -- protection when AI is unavailable.
    No analysis for N seconds AND loss > threshold -> close.
    """
    if not params.get("ai_blind_exit_enabled", True):
        return None

    blind_duration = time.time() - state.last_ai_analysis_ts
    min_blind_sec = params.get("ai_blind_exit_min_blind_sec", 180)
    if blind_duration < min_blind_sec:
        return None

    deal_id = str(pos.get("deal_id", ""))
    direction = str(pos.get("direction", "")).upper()
    size = float(pos.get("size", 0) or 0)
    pnl = float(pos.get("profit_loss", 0) or 0)

    # Loss threshold
    loss_eur = params.get("ai_blind_exit_loss_eur", 80.0)
    if pnl <= -loss_eur:
        logger.info(
            f"AI BLIND EXIT (loss): {deal_id} pnl={round(pnl, 2)}EUR "
            f"blind={int(blind_duration)}s -> close"
        )
        close_position(
            ig_client=ig_client, deal_id=deal_id, direction=direction,
            size=size, pnl=pnl, reason="AI_BLIND_EXIT_LOSS",
            state=state, params=params, trade_repo=trade_repo,
        )
        return "AI_BLIND_EXIT_LOSS"

    # Profit declining while blind
    entry_price = float(pos.get("level", 0) or pos.get("open_level", 0) or 0)
    current_price = float(pos.get("current_level", 0) or 0)
    if entry_price > 0 and current_price > 0:
        if direction == "BUY":
            profit_pts = current_price - entry_price
        else:
            profit_pts = entry_price - current_price

        peak_pnl = state.max_unrealized_by_deal.get(deal_id, 0.0)
        blind_profit_exit_pts = params.get("ai_blind_profit_exit_pts", 5.0)
        if (
            profit_pts > 0
            and profit_pts <= blind_profit_exit_pts
            and peak_pnl > pnl + 3.0
        ):
            logger.info(
                f"AI BLIND EXIT (profit declining): {deal_id} "
                f"pnl={round(pnl, 2)}EUR peak={round(peak_pnl, 2)}EUR "
                f"profit_pts={round(profit_pts, 1)} blind={int(blind_duration)}s -> close"
            )
            close_position(
                ig_client=ig_client, deal_id=deal_id, direction=direction,
                size=size, pnl=pnl, reason="AI_BLIND_EXIT_PROFIT_DECLINE",
                state=state, params=params, trade_repo=trade_repo,
            )
            return "AI_BLIND_EXIT_PROFIT_DECLINE"

    return None


# =========================================================================
# 4a. TRAILING STOP UPDATE (multi-tier progressive)
# =========================================================================

def _update_trailing_stop(
    pos: Dict,
    current_price: float,
    direction: str,
    deal_id: str,
    state: EngineState,
):
    """
    Update the software trailing stop level for a position.
    Uses multi-tier progressive system with interpolation between tiers.
    Trailing tiers are dynamic, based on % of entry price.
    """
    entry_level = float(pos.get("level", 0) or pos.get("open_level", 0) or 0)
    if entry_level <= 0 or current_price <= 0:
        return

    # Profit in points
    if direction == "BUY":
        profit_pts = current_price - entry_level
    elif direction == "SELL":
        profit_pts = entry_level - current_price
    else:
        return

    if profit_pts <= 0:
        return

    # Dynamic trailing tiers based on % of entry price
    ref_price = max(1.0, entry_level)
    trail_tiers = [
        (ref_price * 0.005, 0.0),     # +0.5% -> breakeven
        (ref_price * 0.008, 0.35),    # +0.8% -> lock 35%
        (ref_price * 0.012, 0.45),    # +1.2% -> lock 45%
        (ref_price * 0.018, 0.55),    # +1.8% -> lock 55%
        (ref_price * 0.025, 0.65),    # +2.5% -> lock 65%
        (ref_price * 0.035, 0.70),    # +3.5% -> lock 70%
    ]

    # Find the highest tier reached
    best_lock_pct = -1.0
    best_tier_pts = 0.0
    for tier_pts, tier_pct in trail_tiers:
        if profit_pts >= tier_pts:
            best_lock_pct = tier_pct
            best_tier_pts = tier_pts

    if best_lock_pct < 0:
        return

    # Interpolation between tiers for smooth trailing
    next_tier_pct = best_lock_pct
    next_tier_pts = best_tier_pts
    for tier_pts, tier_pct in trail_tiers:
        if tier_pts > best_tier_pts:
            next_tier_pts = tier_pts
            next_tier_pct = tier_pct
            break

    if next_tier_pts > best_tier_pts and profit_pts > best_tier_pts:
        progress = min(1.0, (profit_pts - best_tier_pts) / (next_tier_pts - best_tier_pts))
        lock_pct = best_lock_pct + (next_tier_pct - best_lock_pct) * progress
    else:
        lock_pct = best_lock_pct

    lock_pts = profit_pts * lock_pct

    if direction == "BUY":
        trail_stop = entry_level + lock_pts
        prev_trail = state.trailing_stop_by_deal.get(deal_id)
        if prev_trail is not None:
            trail_stop = max(trail_stop, prev_trail)
        state.trailing_stop_by_deal[deal_id] = trail_stop
    elif direction == "SELL":
        trail_stop = entry_level - lock_pts
        prev_trail = state.trailing_stop_by_deal.get(deal_id)
        if prev_trail is not None:
            trail_stop = min(trail_stop, prev_trail)
        state.trailing_stop_by_deal[deal_id] = trail_stop


# =========================================================================
# 4b. TRAILING EXIT CHECK
# =========================================================================

def _check_trailing_exit(
    pos: Dict,
    ig_client,
    current_price: float,
    direction: str,
    deal_id: str,
    pnl: float,
    size: float,
    state: EngineState,
    params: Dict,
    *,
    trade_repo=None,
) -> Optional[str]:
    """
    Software trailing exit: close when price retraces past the trailing stop level.
    IG does not allow tightening SL on ETH CFD, so we close the trade directly.
    """
    trail_best = state.trailing_stop_by_deal.get(deal_id)
    if trail_best is None:
        return None

    entry_level = float(pos.get("level", 0) or pos.get("open_level", 0) or 0)
    if entry_level <= 0:
        return None

    if direction == "BUY":
        trail_pnl_pts = trail_best - entry_level
        current_pnl_pts = current_price - entry_level
    elif direction == "SELL":
        trail_pnl_pts = entry_level - trail_best
        current_pnl_pts = entry_level - current_price
    else:
        return None

    # Price retraced past trailing stop -> EXIT
    if trail_pnl_pts > 0 and current_pnl_pts <= trail_pnl_pts:
        logger.info(
            f"TRAILING EXIT {deal_id}: trail_pts={trail_pnl_pts:.1f} "
            f"current_pts={current_pnl_pts:.1f} pnl={pnl:.1f}EUR -> close"
        )
        close_position(
            ig_client=ig_client, deal_id=deal_id, direction=direction,
            size=size, pnl=pnl, reason="TRAILING_STOP_EXIT",
            state=state, params=params, trade_repo=trade_repo,
        )
        return "TRAILING_STOP_EXIT"

    return None


# =========================================================================
# 5. PROFIT RETRACE
# =========================================================================

def _check_profit_retrace(
    pos: Dict,
    ig_client,
    deal_id: str,
    pnl: float,
    direction: str,
    size: float,
    state: EngineState,
    params: Dict,
    *,
    trade_repo=None,
) -> Optional[str]:
    """
    PROFIT RETRACE -- historically 100% WR.
    Simplified: peak > min_peak_eur, drop > min_drop_eur,
    ratio > force_drop_ratio -> close.
    """
    if not params.get("profit_retrace_enabled", True):
        return None

    if pnl <= 0:
        return None

    peak = state.max_unrealized_by_deal.get(deal_id, 0.0)
    if peak <= 0:
        return None

    # Arm check: peak must be significant
    arm_eur = params.get("profit_retrace_min_peak_eur", 10.0)
    tp_eur = float(
        state.position_risk_targets.get(deal_id, {}).get("tp_eur", 0) or 0
    )
    arm_ratio = params.get("profit_retrace_arm_ratio", 0.4)
    if tp_eur > 0:
        arm_eur = max(arm_eur, tp_eur * arm_ratio)

    if peak < arm_eur:
        return None

    # Drop calculation
    drop_eur = max(0.0, peak - pnl)
    drop_ratio = drop_eur / peak if peak > 0 else 0.0

    min_drop_eur = params.get("profit_retrace_min_drop_eur", 3.0)
    if drop_eur < min_drop_eur:
        return None

    force_drop_ratio = params.get("profit_retrace_force_drop_ratio", 0.45)
    if drop_ratio >= force_drop_ratio:
        logger.info(
            f"PROFIT RETRACE {deal_id}: drop={round(drop_ratio * 100, 1)}% "
            f"({round(drop_eur, 2)}EUR) peak={round(peak, 2)}EUR "
            f"pnl={round(pnl, 2)}EUR -> close"
        )
        close_position(
            ig_client=ig_client, deal_id=deal_id, direction=direction,
            size=size, pnl=pnl, reason="PROFIT_RETRACE",
            state=state, params=params, trade_repo=trade_repo,
        )
        return "PROFIT_RETRACE"

    return None


# =========================================================================
# 6. PARTIAL EXIT -- close portion to secure profits
# =========================================================================

def _maybe_partial_exit(
    pos: Dict,
    ig_client,
    deal_id: str,
    direction: str,
    size: float,
    pnl: float,
    state: EngineState,
    params: Dict,
    *,
    trade_repo=None,
):
    """
    PARTIAL EXIT -- close N ETH to secure profits, keep remainder.
    PnL >= min_profit AND position > threshold -> close step ETH.
    """
    if not params.get("partial_exit_enabled", True):
        return

    # Check minimum profit (with secure profile override)
    min_profit = params.get("partial_exit_min_profit_eur", 8.0)
    secure_profile = state.secure_gain_profile_by_deal.get(deal_id, {})
    if secure_profile:
        min_profit = min(
            min_profit,
            float(secure_profile.get("partial_min_profit_eur", min_profit)),
        )

    if pnl < min_profit:
        return

    # Check minimum position size
    small_full_exit = params.get("partial_exit_small_position_full_exit_eth", 1.0)
    min_close = params.get("partial_exit_min_close_eth", 0.5)
    min_remaining = params.get("partial_exit_min_remaining_eth", 0.5)

    if size <= small_full_exit:
        return
    if size < min_close + min_remaining:
        return

    # Check cooldown
    last_partial = state.partial_exit_state_by_deal.get(deal_id, {})
    if last_partial:
        cooldown_sec = params.get("partial_exit_cooldown_sec", 120)
        elapsed = time.time() - float(last_partial.get("ts", 0) or 0)
        if elapsed < cooldown_sec:
            return
        # Check progress since last partial
        min_progress = params.get("partial_exit_min_progress_eur", 3.0)
        last_pnl = float(last_partial.get("pnl", 0) or 0)
        if pnl - last_pnl < min_progress:
            return

    # Close step ETH
    size_step = params.get("partial_exit_size_step", 1.0)
    close_size = min(size_step, size - min_remaining)
    if close_size < min_close:
        return

    logger.info(
        f"PARTIAL EXIT {deal_id}: pnl={round(pnl, 2)}EUR -> close {close_size} ETH, "
        f"keep {round(size - close_size, 2)} ETH"
    )

    close_position(
        ig_client=ig_client, deal_id=deal_id, direction=direction,
        size=close_size, pnl=pnl, reason="PARTIAL_EXIT",
        state=state, params=params, trade_repo=trade_repo,
        partial=True, full_size=size,
    )


# =========================================================================
# 7. GAIN LOCK -- tighten stop to lock in gains
# =========================================================================

def _maybe_lock_gains(
    ig_client,
    pos: Dict,
    tp_eur_target: float,
    state: EngineState,
    params: Dict,
):
    """
    GAIN LOCK -- tighten the IG stop level to lock in a portion of gains.
    Triggered when PnL reaches a fraction of the TP target.
    """
    if not params.get("preserve_gains_enabled", True) or tp_eur_target <= 0:
        return

    deal_id = str(pos.get("deal_id") or "")
    if not deal_id:
        return
    direction = str(pos.get("direction", "")).upper()
    if direction not in ("BUY", "SELL"):
        return

    pnl = float(pos.get("profit_loss", 0) or 0)
    if pnl <= 0:
        return

    # Secure profile override
    profile = state.secure_gain_profile_by_deal.get(deal_id, {})
    trigger_ratio = float(
        profile.get("gain_trigger_ratio", params.get("preserve_gain_trigger_ratio", 0.4))
    )
    lock_ratio = float(
        profile.get("gain_lock_ratio", params.get("preserve_gain_lock_ratio", 0.5))
    )

    trigger_eur = tp_eur_target * max(0.05, min(1.0, trigger_ratio))
    if pnl < trigger_eur:
        return

    size = float(pos.get("size", 0) or 0)
    if size <= 0:
        return

    lock_eur = max(0.0, pnl * max(0.05, min(1.0, lock_ratio)))
    prev_lock = float(state.last_gain_lock_by_deal.get(deal_id, 0) or 0)
    if lock_eur <= prev_lock + 2.0:
        return

    open_level = float(pos.get("open_level", 0) or 0)
    current_level = float(pos.get("current_level", 0) or 0)
    old_stop = pos.get("stop_level")
    old_stop = float(old_stop) if old_stop is not None else None
    old_limit = pos.get("limit_level")
    old_limit = float(old_limit) if old_limit is not None else None

    if open_level <= 0 or current_level <= 0:
        return

    lock_pts = lock_eur / size if size > 0 else 0
    if lock_pts <= 0:
        return

    if direction == "BUY":
        desired_stop = min(current_level - 0.5, open_level + lock_pts)
        if old_stop is not None:
            desired_stop = max(desired_stop, old_stop)
    else:
        desired_stop = max(current_level + 0.5, open_level - lock_pts)
        if old_stop is not None:
            desired_stop = min(desired_stop, old_stop)

    if old_stop is not None and abs(desired_stop - old_stop) < 0.5:
        return

    result = ig_client.update_position_risk(
        deal_id=deal_id,
        stop_level=round(desired_stop, 2),
        limit_level=round(old_limit, 2) if old_limit is not None else None,
    )
    if result and result.get("success"):
        state.last_gain_lock_by_deal[deal_id] = lock_eur
        logger.info(
            f"Gain lock {deal_id}: pnl={round(pnl, 2)}EUR -> "
            f"lock~{round(lock_eur, 2)}EUR (stop {round(desired_stop, 2)})"
        )


# =========================================================================
# FLATTEN FOR PRE-CLOSE
# =========================================================================

def flatten_for_pre_close(
    ig_client,
    positions: List[Dict],
    state: EngineState,
    params: Dict,
    *,
    trade_repo=None,
):
    """Close all positions before IG weekly close."""
    logger.info("Pre-close buffer active -> flattening positions")
    for pos in positions:
        deal_id = str(pos.get("deal_id") or "")
        direction = str(pos.get("direction", "")).upper()
        size = float(pos.get("size", 0) or 0)
        pnl = float(pos.get("profit_loss", 0) or 0)
        if not deal_id or direction not in ("BUY", "SELL") or size <= 0:
            continue
        close_position(
            ig_client=ig_client, deal_id=deal_id, direction=direction,
            size=size, pnl=pnl, reason="PRE_WEEKLY_CLOSE",
            state=state, params=params, trade_repo=trade_repo,
        )


# =========================================================================
# UNIFIED CLOSE POSITION
# =========================================================================

def close_position(
    ig_client,
    deal_id: str,
    direction: str,
    size: float,
    pnl: float,
    reason: str,
    state: EngineState,
    params: Dict,
    *,
    trade_repo=None,
    partial: bool = False,
    full_size: float = 0.0,
) -> bool:
    """
    Unified close -- full or partial.
    Calls ig_client.close_position(), logs to trade_repo (MongoDB),
    prepares WebSocket event data (actual emit done by engine).
    Returns True on success, False on failure.
    """
    close_res = ig_client.close_position(
        deal_id=deal_id, size=size, direction=direction,
    )
    if not _ig_result_success(close_res):
        err = str(
            close_res.get("error", "unknown") if isinstance(close_res, dict) else "unknown"
        )
        logger.warning(f"Close failed {deal_id}: {reason}, err={err}")
        return False

    event_type = "PARTIAL_CLOSE" if partial else "CLOSE"
    reason_logged = f"{reason}_PARTIAL" if partial else reason

    logger.info(
        f"{event_type} {deal_id}: "
        f"pnl={round(pnl, 2)}EUR reason={reason_logged} size={size}"
    )

    # -- MongoDB: Log trade close --
    if event_type == "CLOSE" and trade_repo is not None:
        try:
            peak = state.max_unrealized_by_deal.get(deal_id, 0.0)
            trough = state.min_unrealized_by_deal.get(deal_id, 0.0)
            trade_repo.log_trade_close(
                trade_id=deal_id,
                exit_price=0,  # Updated by position manager
                pnl_eur=pnl,
                exit_reason=reason_logged,
                exit_context={
                    "peak_pnl": peak,
                    "trough_pnl": trough,
                    "exit_thinking": state.last_claude_thinking[:200] if hasattr(state, 'last_claude_thinking') else "",
                    "direction": direction,
                    "size": size,
                },
            )
        except Exception as e:
            logger.warning(f"MongoDB trade_close FAILED: {e}")

    # -- Partial exit bookkeeping --
    if partial:
        state.partial_exit_state_by_deal[deal_id] = {
            "ts": time.time(),
            "pnl": pnl,
            "size": size,
            "remaining": max(0.0, (full_size or size) - size),
        }
        # Scale down tracking for remaining position
        remain_ratio = max(
            0.0, min(1.0, ((full_size or size) - size) / (full_size or size))
        )
        prev_peak = state.max_unrealized_by_deal.get(deal_id, 0.0)
        state.max_unrealized_by_deal[deal_id] = max(0.0, round(prev_peak * remain_ratio, 2))
        prev_lock = state.last_gain_lock_by_deal.get(deal_id, 0.0)
        state.last_gain_lock_by_deal[deal_id] = max(0.0, round(prev_lock * remain_ratio, 2))
        # Scale risk targets
        tgt = state.position_risk_targets.get(deal_id)
        if isinstance(tgt, dict):
            for key in ("sl_eur", "tp_eur"):
                if key in tgt:
                    tgt[key] = round(
                        max(0.0, float(tgt.get(key, 0) or 0) * remain_ratio), 2
                    )

    # -- Full close: post-exit bookkeeping --
    if not partial:
        _register_exit(
            direction=direction, pnl=pnl, reason=reason,
            deal_id=deal_id, state=state, params=params,
        )
        # Cleanup all tracking dicts for this deal
        for d in (
            state.max_unrealized_by_deal,
            state.min_unrealized_by_deal,
            state.trailing_stop_by_deal,
            state.last_gain_lock_by_deal,
            state.position_risk_targets,
            state.partial_exit_state_by_deal,
            state.secure_gain_profile_by_deal,
            state.open_timestamp_by_deal,
        ):
            d.pop(deal_id, None)

    return True


# =========================================================================
# POST-EXIT BOOKKEEPING
# =========================================================================

def _register_exit(
    direction: str,
    pnl: float,
    reason: str,
    deal_id: str,
    state: EngineState,
    params: Dict,
):
    """Post-exit bookkeeping: daily PnL, loss streak, cooldowns."""
    # Daily PnL tracking
    state.daily_pnl_eur += pnl
    daily_loss_limit = params.get("daily_loss_limit_eur", 100.0)
    if daily_loss_limit > 0 and state.daily_pnl_eur <= -daily_loss_limit:
        state.daily_loss_limit_hit = True
        logger.warning(
            f"DAILY LOSS LIMIT: {round(state.daily_pnl_eur, 2)}EUR "
            f"<= -{daily_loss_limit}EUR -> NO MORE TRADES"
        )

    # Win/loss tracking
    if pnl < 0:
        state.daily_losses += 1
        state.loss_streak_count += 1
        # Apply direction cooldown after loss
        loss_cooldown_min = params.get("loss_cooldown_min", 0)
        if loss_cooldown_min > 0:
            cooldown_until = time.time() + (loss_cooldown_min * 60)
            state.direction_cooldown_until["BUY"] = max(
                state.direction_cooldown_until.get("BUY", 0), cooldown_until,
            )
            state.direction_cooldown_until["SELL"] = max(
                state.direction_cooldown_until.get("SELL", 0), cooldown_until,
            )
            logger.info(
                f"Loss cooldown {loss_cooldown_min}min "
                f"(streak={state.loss_streak_count})"
            )

        # Next trade secure: arm after big loss
        nts_enabled = params.get("next_trade_secure_after_loss_enabled", False)
        nts_trigger = params.get("next_trade_secure_loss_trigger_eur", 30.0)
        if nts_enabled and abs(pnl) >= nts_trigger:
            state.next_trade_secure_armed = True
            state.next_trade_secure_reason = f"loss_{round(abs(pnl), 2)}eur"
            logger.info(
                f"Next-trade secure ARMED: loss={round(pnl, 2)}EUR "
                f">= -{nts_trigger}EUR"
            )
    elif pnl > 0:
        state.daily_wins += 1
        state.loss_streak_count = 0


# =========================================================================
# HELPERS
# =========================================================================

def _ig_result_success(result) -> bool:
    """Check if IG API result indicates success (dict or OrderResult dataclass)."""
    try:
        if result is None:
            return False
        # Handle OrderResult dataclass (has .success attribute)
        if hasattr(result, "success"):
            return bool(result.success)
        if isinstance(result, dict):
            if result.get("success"):
                return True
            return str(result.get("dealStatus", "")).upper() == "ACCEPTED"
        return bool(result)
    except Exception:
        return False
