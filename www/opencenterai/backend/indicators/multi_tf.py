"""
OpenCenterAI Trading - Multi-Timeframe Analysis
================================================
Confluence scoring across 5m, 15m, 1h, 4h timeframes.
Trend alignment, momentum alignment, and composite scoring.
"""

import numpy as np
from typing import List, Dict, Any, Optional

from .technical import (
    TechnicalAnalysis,
    ema,
    rsi,
    sma,
)


# =============================================================================
# MULTI-TIMEFRAME CONFLUENCE
# =============================================================================

def compute_multi_tf_confluence(
    candles_by_tf: Dict[str, List[Dict[str, Any]]],
    timeframes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Score confluence across multiple timeframes.

    Parameters
    ----------
    candles_by_tf : dict
        Mapping of timeframe label to candle list, e.g.
        {"5m": [...], "15m": [...], "1h": [...], "4h": [...]}.
        Each candle is a dict with keys: open, high, low, close, volume.
    timeframes : list[str] or None
        Ordered list of timeframe keys to consider (shortest to longest).
        Defaults to ["5m", "15m", "1h", "4h"].

    Returns
    -------
    dict with:
        score          : int 0-100  (higher = stronger confluence)
        direction      : "BULL" / "BEAR" / "NEUTRAL"
        trend_alignment: result from get_trend_alignment()
        momentum_alignment: result from get_momentum_alignment()
        details        : per-TF breakdown
    """
    if timeframes is None:
        timeframes = ["5m", "15m", "1h", "4h"]

    # Weights: longer timeframes carry more weight
    tf_weights = _compute_tf_weights(timeframes)

    details: Dict[str, Dict[str, Any]] = {}
    ta_map: Dict[str, TechnicalAnalysis] = {}

    for tf in timeframes:
        candles = candles_by_tf.get(tf, [])
        if len(candles) < 20:
            details[tf] = {"available": False}
            continue
        ta = TechnicalAnalysis(candles)
        ta_map[tf] = ta
        details[tf] = {
            "available": True,
            "trend": ta.get_trend(),
            "rsi": round(ta.get_rsi(), 2),
            "ema9": round(ta.get_ema(9), 4),
            "ema21": round(ta.get_ema(21), 4),
            "price": ta.current_price,
        }

    trend_alignment = get_trend_alignment(ta_map, timeframes, tf_weights)
    momentum_alignment = get_momentum_alignment(ta_map, timeframes, tf_weights)

    # Composite score
    score = _composite_score(trend_alignment, momentum_alignment)

    # Direction consensus
    bull_count = sum(1 for tf in timeframes if details.get(tf, {}).get("trend") == "BULLISH")
    bear_count = sum(1 for tf in timeframes if details.get(tf, {}).get("trend") == "BEARISH")
    available_count = sum(1 for tf in timeframes if details.get(tf, {}).get("available", False))

    if available_count == 0:
        direction = "NEUTRAL"
    elif bull_count > bear_count and bull_count >= available_count * 0.6:
        direction = "BULL"
    elif bear_count > bull_count and bear_count >= available_count * 0.6:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"

    return {
        "score": score,
        "direction": direction,
        "trend_alignment": trend_alignment,
        "momentum_alignment": momentum_alignment,
        "details": details,
    }


# =============================================================================
# TREND ALIGNMENT
# =============================================================================

def get_trend_alignment(
    ta_map: Dict[str, TechnicalAnalysis],
    timeframes: List[str],
    tf_weights: Dict[str, float],
) -> Dict[str, Any]:
    """
    Alignment des tendances multi-TF.

    Measures whether the EMA-based trend direction agrees across timeframes.
    Returns a score (0-100) and per-TF trend labels.

    Score logic:
        - Each TF contributes its weight if its trend matches the majority.
        - 100 = perfect alignment, 0 = complete disagreement.
    """
    trends: Dict[str, str] = {}
    for tf in timeframes:
        ta = ta_map.get(tf)
        if ta is None:
            continue
        trends[tf] = ta.get_trend()

    if not trends:
        return {"score": 0, "direction": "NEUTRAL", "trends": {}}

    # Count directions
    bull = sum(1 for v in trends.values() if v == "BULLISH")
    bear = sum(1 for v in trends.values() if v == "BEARISH")
    total = len(trends)

    if bull > bear:
        majority = "BULLISH"
    elif bear > bull:
        majority = "BEARISH"
    else:
        majority = "NEUTRAL"

    # Weighted agreement
    weight_sum = 0.0
    aligned_weight = 0.0
    for tf, trend in trends.items():
        w = tf_weights.get(tf, 1.0)
        weight_sum += w
        if trend == majority:
            aligned_weight += w
        elif trend == "NEUTRAL":
            aligned_weight += w * 0.3  # partial credit

    score = int(round((aligned_weight / weight_sum) * 100)) if weight_sum > 0 else 0

    return {
        "score": score,
        "direction": majority,
        "trends": trends,
    }


# =============================================================================
# MOMENTUM ALIGNMENT
# =============================================================================

def get_momentum_alignment(
    ta_map: Dict[str, TechnicalAnalysis],
    timeframes: List[str],
    tf_weights: Dict[str, float],
) -> Dict[str, Any]:
    """
    Alignment du momentum multi-TF.

    Uses RSI to determine if momentum agrees across timeframes.
    RSI > 55 = bullish momentum, RSI < 45 = bearish, else neutral.
    Returns a score (0-100) and per-TF RSI values.
    """
    rsi_values: Dict[str, float] = {}
    for tf in timeframes:
        ta = ta_map.get(tf)
        if ta is None:
            continue
        rsi_values[tf] = ta.get_rsi()

    if not rsi_values:
        return {"score": 0, "direction": "NEUTRAL", "rsi": {}}

    # Classify momentum per TF
    bull = 0
    bear = 0
    for v in rsi_values.values():
        if v > 55:
            bull += 1
        elif v < 45:
            bear += 1

    total = len(rsi_values)
    if bull > bear:
        majority = "BULL"
    elif bear > bull:
        majority = "BEAR"
    else:
        majority = "NEUTRAL"

    # Weighted alignment
    weight_sum = 0.0
    aligned_weight = 0.0
    for tf, rv in rsi_values.items():
        w = tf_weights.get(tf, 1.0)
        weight_sum += w
        if majority == "BULL" and rv > 55:
            aligned_weight += w
        elif majority == "BEAR" and rv < 45:
            aligned_weight += w
        elif majority == "NEUTRAL":
            aligned_weight += w * 0.5

    score = int(round((aligned_weight / weight_sum) * 100)) if weight_sum > 0 else 0

    return {
        "score": score,
        "direction": majority,
        "rsi": {k: round(v, 2) for k, v in rsi_values.items()},
    }


# =============================================================================
# HELPERS
# =============================================================================

def _compute_tf_weights(timeframes: List[str]) -> Dict[str, float]:
    """
    Assign increasing weights to longer timeframes.
    The last (longest) TF gets weight 4, the first gets weight 1,
    with linear interpolation in between.
    """
    n = len(timeframes)
    if n == 0:
        return {}
    if n == 1:
        return {timeframes[0]: 1.0}
    weights: Dict[str, float] = {}
    for idx, tf in enumerate(timeframes):
        # Linear from 1.0 to 4.0
        weights[tf] = 1.0 + 3.0 * (idx / (n - 1))
    return weights


def _composite_score(
    trend_alignment: Dict[str, Any],
    momentum_alignment: Dict[str, Any],
) -> int:
    """
    Combine trend and momentum alignment into a single 0-100 score.
    Trend carries 60 % weight, momentum 40 %.
    Bonus if both agree on direction.
    """
    t_score = trend_alignment.get("score", 0)
    m_score = momentum_alignment.get("score", 0)

    raw = t_score * 0.6 + m_score * 0.4

    # Direction agreement bonus
    t_dir = trend_alignment.get("direction", "NEUTRAL")
    m_dir = momentum_alignment.get("direction", "NEUTRAL")

    if t_dir != "NEUTRAL" and m_dir != "NEUTRAL":
        if (t_dir == "BULLISH" and m_dir == "BULL") or (t_dir == "BEARISH" and m_dir == "BEAR"):
            raw = min(100, raw + 10)
        else:
            # Conflicting directions -- penalise
            raw = max(0, raw - 15)

    return int(round(raw))
