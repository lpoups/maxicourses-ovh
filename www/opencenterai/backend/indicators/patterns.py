"""
OpenCenterAI Trading - Pattern Detection
=========================================
Candlestick patterns, chart patterns (Double Top/Bottom, H&S, Triangles, etc.),
divergence detection, support/resistance, and market structure analysis.
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple

from .technical import (
    sma, ema, rsi, macd, atr, pivot_points, linreg_slope, _clamp,
)


# =============================================================================
# CANDLESTICK HELPERS
# =============================================================================

def _candle_body(o: float, c: float) -> float:
    """Taille absolue du corps de la bougie"""
    return abs(c - o)


def _candle_range(h: float, l: float) -> float:
    """Range total de la bougie (high - low)"""
    return h - l


def _upper_shadow(o: float, h: float, c: float) -> float:
    """Meche haute"""
    return h - max(o, c)


def _lower_shadow(o: float, l: float, c: float) -> float:
    """Meche basse"""
    return min(o, c) - l


def _is_bullish(o: float, c: float) -> bool:
    return c > o


def _is_bearish(o: float, c: float) -> bool:
    return c < o


def _avg_body(opens: List[float], closes: List[float], period: int = 10) -> float:
    """Corps moyen des N dernieres bougies"""
    if len(opens) < period:
        period = len(opens)
    bodies = [_candle_body(opens[i], closes[i]) for i in range(-period, 0)]
    return np.mean(bodies) if bodies else 0.0


# =============================================================================
# CANDLESTICK PATTERN DETECTION
# =============================================================================

def detect_candlestick_patterns(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback: int = 10
) -> List[Dict[str, Any]]:
    """
    Detection de 20+ patterns de bougies japonaises.

    Retourne une liste de patterns detectes sur les `lookback` dernieres bougies.
    Chaque pattern : {name, type, direction, reliability, index}
    - type : "reversal" | "continuation"
    - direction : "bull" | "bear"
    - reliability : 1-5 (5 = tres fiable)
    """
    n = len(closes)
    if n < 5:
        return []

    patterns: List[Dict[str, Any]] = []
    start = max(0, n - lookback)
    avg_b = _avg_body(opens, closes, 20) if n >= 20 else _avg_body(opens, closes, n)
    if avg_b == 0:
        avg_b = 1e-8  # eviter division par zero

    for i in range(start, n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        body = _candle_body(o, c)
        rng = _candle_range(h, l)
        upper = _upper_shadow(o, h, c)
        lower = _lower_shadow(o, l, c)

        if rng == 0:
            continue

        body_ratio = body / rng  # corps / range total

        # ===== SINGLE CANDLE PATTERNS =====

        # --- Doji ---
        if body < avg_b * 0.1 and rng > avg_b * 0.5:
            patterns.append({
                "name": "Doji",
                "type": "reversal",
                "direction": "bear" if i > 0 and _is_bullish(opens[i-1], closes[i-1]) else "bull",
                "reliability": 2,
                "index": i
            })

        # --- Dragonfly Doji ---
        if body < avg_b * 0.1 and lower > rng * 0.65 and upper < rng * 0.1:
            patterns.append({
                "name": "Dragonfly Doji",
                "type": "reversal",
                "direction": "bull",
                "reliability": 3,
                "index": i
            })

        # --- Gravestone Doji ---
        if body < avg_b * 0.1 and upper > rng * 0.65 and lower < rng * 0.1:
            patterns.append({
                "name": "Gravestone Doji",
                "type": "reversal",
                "direction": "bear",
                "reliability": 3,
                "index": i
            })

        # --- Spinning Top ---
        if body_ratio < 0.35 and upper > body * 0.8 and lower > body * 0.8:
            patterns.append({
                "name": "Spinning Top",
                "type": "continuation",
                "direction": "bull" if _is_bullish(o, c) else "bear",
                "reliability": 1,
                "index": i
            })

        # --- Marubozu (full body, no shadows) ---
        if body_ratio > 0.90:
            direction = "bull" if _is_bullish(o, c) else "bear"
            patterns.append({
                "name": "Marubozu",
                "type": "continuation",
                "direction": direction,
                "reliability": 3,
                "index": i
            })

        # --- Hammer (bullish reversal at bottom) ---
        if lower > body * 2 and upper < body * 0.3 and body > avg_b * 0.3:
            if i >= 3:
                prior_trend = closes[i] - closes[i-3]
                if prior_trend < 0:
                    patterns.append({
                        "name": "Hammer",
                        "type": "reversal",
                        "direction": "bull",
                        "reliability": 4,
                        "index": i
                    })

        # --- Inverted Hammer (bullish reversal at bottom) ---
        if upper > body * 2 and lower < body * 0.3 and body > avg_b * 0.3:
            if i >= 3:
                prior_trend = closes[i] - closes[i-3]
                if prior_trend < 0:
                    patterns.append({
                        "name": "Inverted Hammer",
                        "type": "reversal",
                        "direction": "bull",
                        "reliability": 3,
                        "index": i
                    })

        # --- Hanging Man (bearish reversal at top) ---
        if lower > body * 2 and upper < body * 0.3 and body > avg_b * 0.3:
            if i >= 3:
                prior_trend = closes[i] - closes[i-3]
                if prior_trend > 0:
                    patterns.append({
                        "name": "Hanging Man",
                        "type": "reversal",
                        "direction": "bear",
                        "reliability": 3,
                        "index": i
                    })

        # --- Shooting Star (bearish reversal at top) ---
        if upper > body * 2 and lower < body * 0.3 and body > avg_b * 0.3:
            if i >= 3:
                prior_trend = closes[i] - closes[i-3]
                if prior_trend > 0:
                    patterns.append({
                        "name": "Shooting Star",
                        "type": "reversal",
                        "direction": "bear",
                        "reliability": 4,
                        "index": i
                    })

        # --- High Wave Candle ---
        if upper > body * 1.5 and lower > body * 1.5 and body < avg_b * 0.5:
            patterns.append({
                "name": "High Wave",
                "type": "reversal",
                "direction": "bear" if i > 0 and _is_bullish(opens[i-1], closes[i-1]) else "bull",
                "reliability": 2,
                "index": i
            })

        # ===== TWO-CANDLE PATTERNS =====
        if i < 1:
            continue

        o1, h1, l1, c1 = opens[i-1], highs[i-1], lows[i-1], closes[i-1]
        body1 = _candle_body(o1, c1)

        # --- Bullish Engulfing ---
        if _is_bearish(o1, c1) and _is_bullish(o, c) and o <= c1 and c >= o1 and body > body1:
            patterns.append({
                "name": "Bullish Engulfing",
                "type": "reversal",
                "direction": "bull",
                "reliability": 4,
                "index": i
            })

        # --- Bearish Engulfing ---
        if _is_bullish(o1, c1) and _is_bearish(o, c) and o >= c1 and c <= o1 and body > body1:
            patterns.append({
                "name": "Bearish Engulfing",
                "type": "reversal",
                "direction": "bear",
                "reliability": 4,
                "index": i
            })

        # --- Bullish Harami ---
        if _is_bearish(o1, c1) and _is_bullish(o, c) and o >= c1 and c <= o1 and body < body1 * 0.6:
            patterns.append({
                "name": "Bullish Harami",
                "type": "reversal",
                "direction": "bull",
                "reliability": 3,
                "index": i
            })

        # --- Bearish Harami ---
        if _is_bullish(o1, c1) and _is_bearish(o, c) and o <= c1 and c >= o1 and body < body1 * 0.6:
            patterns.append({
                "name": "Bearish Harami",
                "type": "reversal",
                "direction": "bear",
                "reliability": 3,
                "index": i
            })

        # --- Piercing Line ---
        if (_is_bearish(o1, c1) and _is_bullish(o, c) and
            o < l1 and c > (o1 + c1) / 2 and c < o1):
            patterns.append({
                "name": "Piercing Line",
                "type": "reversal",
                "direction": "bull",
                "reliability": 4,
                "index": i
            })

        # --- Dark Cloud Cover ---
        if (_is_bullish(o1, c1) and _is_bearish(o, c) and
            o > h1 and c < (o1 + c1) / 2 and c > o1):
            patterns.append({
                "name": "Dark Cloud Cover",
                "type": "reversal",
                "direction": "bear",
                "reliability": 4,
                "index": i
            })

        # --- Tweezer Bottom ---
        if (abs(l - l1) < avg_b * 0.1 and
            _is_bearish(o1, c1) and _is_bullish(o, c) and
            body > avg_b * 0.3 and body1 > avg_b * 0.3):
            patterns.append({
                "name": "Tweezer Bottom",
                "type": "reversal",
                "direction": "bull",
                "reliability": 4,
                "index": i
            })

        # --- Tweezer Top ---
        if (abs(h - h1) < avg_b * 0.1 and
            _is_bullish(o1, c1) and _is_bearish(o, c) and
            body > avg_b * 0.3 and body1 > avg_b * 0.3):
            patterns.append({
                "name": "Tweezer Top",
                "type": "reversal",
                "direction": "bear",
                "reliability": 4,
                "index": i
            })

        # ===== THREE-CANDLE PATTERNS =====
        if i < 2:
            continue

        o2, h2, l2, c2 = opens[i-2], highs[i-2], lows[i-2], closes[i-2]
        body2 = _candle_body(o2, c2)

        # --- Morning Star ---
        if (_is_bearish(o2, c2) and body2 > avg_b * 0.6 and
            body1 < avg_b * 0.4 and  # petite bougie du milieu
            _is_bullish(o, c) and body > avg_b * 0.6 and
            c > (o2 + c2) / 2):
            patterns.append({
                "name": "Morning Star",
                "type": "reversal",
                "direction": "bull",
                "reliability": 5,
                "index": i
            })

        # --- Evening Star ---
        if (_is_bullish(o2, c2) and body2 > avg_b * 0.6 and
            body1 < avg_b * 0.4 and  # petite bougie du milieu
            _is_bearish(o, c) and body > avg_b * 0.6 and
            c < (o2 + c2) / 2):
            patterns.append({
                "name": "Evening Star",
                "type": "reversal",
                "direction": "bear",
                "reliability": 5,
                "index": i
            })

        # --- Three White Soldiers ---
        if (all(_is_bullish(opens[i-j], closes[i-j]) for j in range(3)) and
            all(_candle_body(opens[i-j], closes[i-j]) > avg_b * 0.5 for j in range(3)) and
            closes[i] > closes[i-1] > closes[i-2] and
            opens[i] > opens[i-1] > opens[i-2]):
            patterns.append({
                "name": "Three White Soldiers",
                "type": "reversal",
                "direction": "bull",
                "reliability": 5,
                "index": i
            })

        # --- Three Black Crows ---
        if (all(_is_bearish(opens[i-j], closes[i-j]) for j in range(3)) and
            all(_candle_body(opens[i-j], closes[i-j]) > avg_b * 0.5 for j in range(3)) and
            closes[i] < closes[i-1] < closes[i-2] and
            opens[i] < opens[i-1] < opens[i-2]):
            patterns.append({
                "name": "Three Black Crows",
                "type": "reversal",
                "direction": "bear",
                "reliability": 5,
                "index": i
            })

        # --- Abandoned Baby Bullish ---
        if (_is_bearish(o2, c2) and body2 > avg_b * 0.5 and
            body1 < avg_b * 0.15 and h1 < l2 and  # gap down doji
            _is_bullish(o, c) and body > avg_b * 0.5 and l > h1):  # gap up
            patterns.append({
                "name": "Abandoned Baby Bullish",
                "type": "reversal",
                "direction": "bull",
                "reliability": 5,
                "index": i
            })

        # --- Abandoned Baby Bearish ---
        if (_is_bullish(o2, c2) and body2 > avg_b * 0.5 and
            body1 < avg_b * 0.15 and l1 > h2 and  # gap up doji
            _is_bearish(o, c) and body > avg_b * 0.5 and h < l1):  # gap down
            patterns.append({
                "name": "Abandoned Baby Bearish",
                "type": "reversal",
                "direction": "bear",
                "reliability": 5,
                "index": i
            })

        # ===== FIVE-CANDLE PATTERNS =====
        if i < 4:
            continue

        # --- Rising Three Methods (bullish continuation) ---
        o4 = opens[i-4]; c4 = closes[i-4]; h4 = highs[i-4]; l4 = lows[i-4]
        if (_is_bullish(o4, c4) and _candle_body(o4, c4) > avg_b * 0.8 and
            all(_is_bearish(opens[i-j], closes[i-j]) for j in range(1, 4)) and
            all(lows[i-j] > l4 for j in range(1, 4)) and  # contenu dans la 1ere
            all(highs[i-j] < h4 for j in range(1, 4)) and
            _is_bullish(o, c) and c > c4):
            patterns.append({
                "name": "Rising Three Methods",
                "type": "continuation",
                "direction": "bull",
                "reliability": 4,
                "index": i
            })

        # --- Falling Three Methods (bearish continuation) ---
        if (_is_bearish(o4, c4) and _candle_body(o4, c4) > avg_b * 0.8 and
            all(_is_bullish(opens[i-j], closes[i-j]) for j in range(1, 4)) and
            all(highs[i-j] < h4 for j in range(1, 4)) and
            all(lows[i-j] > l4 for j in range(1, 4)) and
            _is_bearish(o, c) and c < c4):
            patterns.append({
                "name": "Falling Three Methods",
                "type": "continuation",
                "direction": "bear",
                "reliability": 4,
                "index": i
            })

    return patterns


# =============================================================================
# CHART PATTERN DETECTION
# =============================================================================

def detect_chart_patterns(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback: int = 50
) -> List[Dict[str, Any]]:
    """
    Detection de structures chartistes : Double Top/Bottom, Head & Shoulders,
    Triangles, Channels, Wedges.

    Retourne une liste de patterns : {name, type, direction, reliability,
                                       target (prix cible si applicable)}
    """
    n = len(closes)
    if n < 20:
        return []

    start = max(0, n - lookback)
    patterns: List[Dict[str, Any]] = []

    # Trouver les pivots dans la fenetre
    pvt_highs, pvt_lows = pivot_points(highs, lows, closes, lookback=3)

    # Collecter les pivots recents
    recent_highs = [(i, pvt_highs[i]) for i in range(start, n) if pvt_highs[i] is not None]
    recent_lows = [(i, pvt_lows[i]) for i in range(start, n) if pvt_lows[i] is not None]

    price = closes[-1] if closes else 0.0
    avg_range = np.mean([highs[i] - lows[i] for i in range(start, n)]) if n > start else 1.0
    tolerance = avg_range * 0.5  # tolerance pour les niveaux similaires

    # --- Double Top ---
    if len(recent_highs) >= 2:
        for j in range(len(recent_highs) - 1):
            idx1, val1 = recent_highs[j]
            idx2, val2 = recent_highs[j + 1]
            if (abs(val1 - val2) < tolerance and
                idx2 - idx1 >= 5 and
                price < min(val1, val2)):
                # Trouver le creux entre les deux sommets
                trough = min(lows[idx1:idx2+1]) if idx2 > idx1 else val1
                target = trough - (val1 - trough)  # projection baissiere
                patterns.append({
                    "name": "Double Top",
                    "type": "reversal",
                    "direction": "bear",
                    "reliability": 4,
                    "target": round(target, 2),
                    "neckline": round(trough, 2)
                })
                break  # une seule detection suffit

    # --- Double Bottom ---
    if len(recent_lows) >= 2:
        for j in range(len(recent_lows) - 1):
            idx1, val1 = recent_lows[j]
            idx2, val2 = recent_lows[j + 1]
            if (abs(val1 - val2) < tolerance and
                idx2 - idx1 >= 5 and
                price > max(val1, val2)):
                peak = max(highs[idx1:idx2+1]) if idx2 > idx1 else val1
                target = peak + (peak - val1)
                patterns.append({
                    "name": "Double Bottom",
                    "type": "reversal",
                    "direction": "bull",
                    "reliability": 4,
                    "target": round(target, 2),
                    "neckline": round(peak, 2)
                })
                break

    # --- Head & Shoulders ---
    if len(recent_highs) >= 3:
        for j in range(len(recent_highs) - 2):
            idx1, left = recent_highs[j]
            idx2, head = recent_highs[j + 1]
            idx3, right = recent_highs[j + 2]

            if (head > left and head > right and  # tete plus haute
                abs(left - right) < tolerance and  # epaules similaires
                idx3 - idx1 >= 10):
                # Neckline = moyenne des creux entre epaules
                trough1 = min(lows[idx1:idx2+1]) if idx2 > idx1 else left
                trough2 = min(lows[idx2:idx3+1]) if idx3 > idx2 else right
                neckline = (trough1 + trough2) / 2.0
                target = neckline - (head - neckline)

                if price < neckline * 1.02:  # prix proche ou sous neckline
                    patterns.append({
                        "name": "Head & Shoulders",
                        "type": "reversal",
                        "direction": "bear",
                        "reliability": 5,
                        "target": round(target, 2),
                        "neckline": round(neckline, 2)
                    })
                    break

    # --- Inverse Head & Shoulders ---
    if len(recent_lows) >= 3:
        for j in range(len(recent_lows) - 2):
            idx1, left = recent_lows[j]
            idx2, head = recent_lows[j + 1]
            idx3, right = recent_lows[j + 2]

            if (head < left and head < right and
                abs(left - right) < tolerance and
                idx3 - idx1 >= 10):
                peak1 = max(highs[idx1:idx2+1]) if idx2 > idx1 else left
                peak2 = max(highs[idx2:idx3+1]) if idx3 > idx2 else right
                neckline = (peak1 + peak2) / 2.0
                target = neckline + (neckline - head)

                if price > neckline * 0.98:
                    patterns.append({
                        "name": "Inverse Head & Shoulders",
                        "type": "reversal",
                        "direction": "bull",
                        "reliability": 5,
                        "target": round(target, 2),
                        "neckline": round(neckline, 2)
                    })
                    break

    # --- Triangle Detection (via trendlines on pivots) ---
    if len(recent_highs) >= 2 and len(recent_lows) >= 2:
        # Pente des sommets
        h_idx1, h_val1 = recent_highs[-2]
        h_idx2, h_val2 = recent_highs[-1]
        h_slope = (h_val2 - h_val1) / max(h_idx2 - h_idx1, 1)

        # Pente des creux
        l_idx1, l_val1 = recent_lows[-2]
        l_idx2, l_val2 = recent_lows[-1]
        l_slope = (l_val2 - l_val1) / max(l_idx2 - l_idx1, 1)

        slope_threshold = avg_range * 0.02

        # Ascending Triangle: flat top, rising bottoms
        if abs(h_slope) < slope_threshold and l_slope > slope_threshold:
            patterns.append({
                "name": "Ascending Triangle",
                "type": "continuation",
                "direction": "bull",
                "reliability": 3,
                "target": round(h_val2 + (h_val2 - l_val2), 2)
            })

        # Descending Triangle: flat bottom, falling tops
        elif abs(l_slope) < slope_threshold and h_slope < -slope_threshold:
            patterns.append({
                "name": "Descending Triangle",
                "type": "continuation",
                "direction": "bear",
                "reliability": 3,
                "target": round(l_val2 - (h_val2 - l_val2), 2)
            })

        # Symmetrical Triangle: converging trendlines
        elif h_slope < -slope_threshold and l_slope > slope_threshold:
            # Direction = selon tendance anterieure
            prior_trend = closes[start + 5] - closes[start] if n > start + 5 else 0
            direction = "bull" if prior_trend > 0 else "bear"
            patterns.append({
                "name": "Symmetrical Triangle",
                "type": "continuation",
                "direction": direction,
                "reliability": 2,
                "target": None
            })

        # Rising Wedge (bearish): both trendlines rising, converging
        elif h_slope > 0 and l_slope > 0 and l_slope > h_slope:
            patterns.append({
                "name": "Rising Wedge",
                "type": "reversal",
                "direction": "bear",
                "reliability": 3,
                "target": round(l_val2, 2)
            })

        # Falling Wedge (bullish): both trendlines falling, converging
        elif h_slope < 0 and l_slope < 0 and h_slope < l_slope:
            patterns.append({
                "name": "Falling Wedge",
                "type": "reversal",
                "direction": "bull",
                "reliability": 3,
                "target": round(h_val2, 2)
            })

    # --- Channel Detection ---
    if n > start + 10:
        segment_closes = closes[start:]
        segment_highs = highs[start:]
        segment_lows = lows[start:]
        seg_n = len(segment_closes)
        x = np.arange(seg_n, dtype=float)

        # Regression lineaire sur les highs et lows
        x_mean = np.mean(x)

        h_arr = np.array(segment_highs, dtype=float)
        l_arr = np.array(segment_lows, dtype=float)

        h_mean = np.mean(h_arr)
        l_mean = np.mean(l_arr)

        x_var = np.sum((x - x_mean) ** 2)
        if x_var > 0:
            h_slope_lr = np.sum((x - x_mean) * (h_arr - h_mean)) / x_var
            l_slope_lr = np.sum((x - x_mean) * (l_arr - l_mean)) / x_var

            # Channel si pentes paralleles
            if abs(h_slope_lr - l_slope_lr) < avg_range * 0.01:
                if h_slope_lr > avg_range * 0.005:
                    patterns.append({
                        "name": "Ascending Channel",
                        "type": "continuation",
                        "direction": "bull",
                        "reliability": 3,
                        "target": None
                    })
                elif h_slope_lr < -avg_range * 0.005:
                    patterns.append({
                        "name": "Descending Channel",
                        "type": "continuation",
                        "direction": "bear",
                        "reliability": 3,
                        "target": None
                    })

    return patterns


# =============================================================================
# DIVERGENCE DETECTION
# =============================================================================

def detect_divergences(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    rsi_period: int = 14,
    lookback: int = 50,
    pivot_lookback: int = 5,
) -> List[Dict[str, Any]]:
    """
    Detect RSI and MACD divergences (bullish and bearish).

    A bullish divergence occurs when price makes a lower low but the
    oscillator makes a higher low.  A bearish divergence occurs when price
    makes a higher high but the oscillator makes a lower high.

    Returns a list of dicts:
        {indicator, type ("bullish"/"bearish"), reliability (1-5),
         price_level, oscillator_level}
    """
    n = len(closes)
    if n < max(lookback, 30):
        return []

    divergences: List[Dict[str, Any]] = []
    start = max(0, n - lookback)

    # RSI series
    rsi_vals = rsi(closes, rsi_period)

    # MACD histogram series
    _, _, macd_hist = macd(closes)

    # Pivot lows/highs on price
    pvt_highs, pvt_lows = pivot_points(highs, lows, closes, lookback=pivot_lookback)

    # Collect recent pivot lows for bullish divergence
    price_lows = [(i, lows[i]) for i in range(start, n) if pvt_lows[i] is not None]
    price_highs = [(i, highs[i]) for i in range(start, n) if pvt_highs[i] is not None]

    # --- RSI Bullish Divergence: lower low in price, higher low in RSI ---
    for j in range(len(price_lows) - 1):
        idx1, pval1 = price_lows[j]
        idx2, pval2 = price_lows[j + 1]
        if pval2 < pval1:  # price lower low
            rsi1 = rsi_vals[idx1] if idx1 < len(rsi_vals) and not np.isnan(rsi_vals[idx1]) else None
            rsi2 = rsi_vals[idx2] if idx2 < len(rsi_vals) and not np.isnan(rsi_vals[idx2]) else None
            if rsi1 is not None and rsi2 is not None and rsi2 > rsi1:
                divergences.append({
                    "indicator": "RSI",
                    "type": "bullish",
                    "reliability": 4,
                    "price_level": round(pval2, 4),
                    "oscillator_level": round(rsi2, 2),
                })

    # --- RSI Bearish Divergence: higher high in price, lower high in RSI ---
    for j in range(len(price_highs) - 1):
        idx1, pval1 = price_highs[j]
        idx2, pval2 = price_highs[j + 1]
        if pval2 > pval1:  # price higher high
            rsi1 = rsi_vals[idx1] if idx1 < len(rsi_vals) and not np.isnan(rsi_vals[idx1]) else None
            rsi2 = rsi_vals[idx2] if idx2 < len(rsi_vals) and not np.isnan(rsi_vals[idx2]) else None
            if rsi1 is not None and rsi2 is not None and rsi2 < rsi1:
                divergences.append({
                    "indicator": "RSI",
                    "type": "bearish",
                    "reliability": 4,
                    "price_level": round(pval2, 4),
                    "oscillator_level": round(rsi2, 2),
                })

    # --- MACD Bullish Divergence ---
    for j in range(len(price_lows) - 1):
        idx1, pval1 = price_lows[j]
        idx2, pval2 = price_lows[j + 1]
        if pval2 < pval1:
            m1 = macd_hist[idx1] if idx1 < len(macd_hist) and not np.isnan(macd_hist[idx1]) else None
            m2 = macd_hist[idx2] if idx2 < len(macd_hist) and not np.isnan(macd_hist[idx2]) else None
            if m1 is not None and m2 is not None and m2 > m1:
                divergences.append({
                    "indicator": "MACD",
                    "type": "bullish",
                    "reliability": 3,
                    "price_level": round(pval2, 4),
                    "oscillator_level": round(m2, 4),
                })

    # --- MACD Bearish Divergence ---
    for j in range(len(price_highs) - 1):
        idx1, pval1 = price_highs[j]
        idx2, pval2 = price_highs[j + 1]
        if pval2 > pval1:
            m1 = macd_hist[idx1] if idx1 < len(macd_hist) and not np.isnan(macd_hist[idx1]) else None
            m2 = macd_hist[idx2] if idx2 < len(macd_hist) and not np.isnan(macd_hist[idx2]) else None
            if m1 is not None and m2 is not None and m2 < m1:
                divergences.append({
                    "indicator": "MACD",
                    "type": "bearish",
                    "reliability": 3,
                    "price_level": round(pval2, 4),
                    "oscillator_level": round(m2, 4),
                })

    return divergences


# =============================================================================
# SUPPORT / RESISTANCE (auto-detection)
# =============================================================================

def auto_support_resistance(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback: int = 5,
    threshold: float = 0.02
) -> Tuple[List[float], List[float]]:
    """
    Automatic Support and Resistance levels detection.
    Returns (support_levels, resistance_levels)
    """
    pivot_h, pivot_l = pivot_points(highs, lows, closes, lookback)

    # Collect valid pivots
    resistances = [p for p in pivot_h if p is not None]
    supports = [p for p in pivot_l if p is not None]

    # Cluster similar levels
    def cluster_levels(levels: List[float], threshold_pct: float) -> List[float]:
        if not levels:
            return []

        sorted_levels = sorted(levels)
        clusters: List[List[float]] = []
        current_cluster = [sorted_levels[0]]

        for level in sorted_levels[1:]:
            if abs(level - current_cluster[-1]) / current_cluster[-1] < threshold_pct:
                current_cluster.append(level)
            else:
                clusters.append(current_cluster)
                current_cluster = [level]

        clusters.append(current_cluster)
        return [float(np.mean(c)) for c in clusters]

    support_levels = cluster_levels(supports, threshold)
    resistance_levels = cluster_levels(resistances, threshold)

    return (support_levels, resistance_levels)


def detect_support_resistance(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback: int = 5,
    threshold: float = 0.02,
) -> Dict[str, Any]:
    """
    Convenience wrapper returning a dict with support and resistance arrays
    plus nearest levels relative to the current price.
    """
    supports, resistances = auto_support_resistance(
        highs, lows, closes, lookback, threshold
    )
    price = closes[-1] if closes else 0.0

    nearest_support = max((s for s in supports if s <= price), default=None)
    nearest_resistance = min((r for r in resistances if r >= price), default=None)

    return {
        "supports": supports,
        "resistances": resistances,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
    }


# =============================================================================
# MARKET STRUCTURE ANALYSIS
# =============================================================================

def analyze_market_structure(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    lookback: int = 120,
    swing_lookback: int = 3,
) -> Dict[str, Any]:
    """
    Analyse de structure de marche orientee execution:
    - BOS / CHOCH (break of structure / change of character)
    - breakout confirme par volume
    - retest/rejet de niveaux
    - invalidation chartiste
    """
    out: Dict[str, Any] = {
        "state": "RANGE",
        "bias": "NEUTRAL",
        "strength": 0,
        "breakout_long": False,
        "breakout_short": False,
        "breakout_volume_ratio": 0.0,
        "retest_support_long": False,
        "retest_resistance_short": False,
        "wick_rejection_long": False,
        "wick_rejection_short": False,
        "last_swing_high": None,
        "last_swing_low": None,
        "prev_swing_high": None,
        "prev_swing_low": None,
        "invalidation_long": None,
        "invalidation_short": None,
        "invalidation_long_dist_atr": 99.0,
        "invalidation_short_dist_atr": 99.0,
    }

    n = len(closes)
    if n < max(30, swing_lookback * 8):
        return out

    start = max(0, n - lookback)
    c = closes[start:]
    o = opens[start:]
    h = highs[start:]
    l = lows[start:]
    v = volumes[start:] if volumes else [0.0] * len(c)

    current = float(c[-1])
    current_open = float(o[-1])
    current_high = float(h[-1])
    current_low = float(l[-1])

    # ATR reference for scale-aware thresholds
    atr_values = atr(highs, lows, closes, period=14)
    atr_value = float(atr_values[-1]) if atr_values else 0.0
    if np.isnan(atr_value) or atr_value <= 0:
        atr_value = max((max(h) - min(l)) / 60.0, 1e-6)

    # Swing points from full series (keep original indexes then filter window)
    pvt_highs, pvt_lows = pivot_points(highs, lows, closes, lookback=swing_lookback)
    recent_highs = [(i, float(val)) for i, val in enumerate(pvt_highs) if val is not None and i >= start]
    recent_lows = [(i, float(val)) for i, val in enumerate(pvt_lows) if val is not None and i >= start]

    if len(recent_highs) >= 2:
        out["prev_swing_high"] = round(float(recent_highs[-2][1]), 4)
        out["last_swing_high"] = round(float(recent_highs[-1][1]), 4)
    elif len(recent_highs) == 1:
        out["last_swing_high"] = round(float(recent_highs[-1][1]), 4)

    if len(recent_lows) >= 2:
        out["prev_swing_low"] = round(float(recent_lows[-2][1]), 4)
        out["last_swing_low"] = round(float(recent_lows[-1][1]), 4)
    elif len(recent_lows) == 1:
        out["last_swing_low"] = round(float(recent_lows[-1][1]), 4)

    last_high = float(out["last_swing_high"] if out["last_swing_high"] is not None else max(h[-8:]))
    last_low = float(out["last_swing_low"] if out["last_swing_low"] is not None else min(l[-8:]))
    prev_high = float(out["prev_swing_high"] if out["prev_swing_high"] is not None else last_high)
    prev_low = float(out["prev_swing_low"] if out["prev_swing_low"] is not None else last_low)

    hh = last_high > (prev_high + atr_value * 0.08)
    hl = last_low > (prev_low + atr_value * 0.08)
    lh = last_high < (prev_high - atr_value * 0.08)
    ll = last_low < (prev_low - atr_value * 0.08)

    structure_bias = "NEUTRAL"
    if hh and hl:
        structure_bias = "BULL"
    elif lh and ll:
        structure_bias = "BEAR"

    breakout_long = current > (last_high + atr_value * 0.12)
    breakout_short = current < (last_low - atr_value * 0.12)

    vol_tail = [float(x) for x in v[-20:] if float(x) > 0]
    avg_vol = float(np.mean(vol_tail)) if vol_tail else 0.0
    last_vol = float(v[-1]) if v else 0.0
    vol_ratio = (last_vol / avg_vol) if avg_vol > 0 else 1.0
    breakout_vol_ok = vol_ratio >= 1.05

    body = abs(current - current_open)
    upper_wick = current_high - max(current, current_open)
    lower_wick = min(current, current_open) - current_low

    wick_rejection_long = (
        lower_wick > max(body * 1.8, atr_value * 0.08)
        and current > current_open
        and current_low <= (last_low + atr_value * 0.20)
    )
    wick_rejection_short = (
        upper_wick > max(body * 1.8, atr_value * 0.08)
        and current < current_open
        and current_high >= (last_high - atr_value * 0.20)
    )

    retest_support_long = (
        abs(current - last_low) <= atr_value * 0.35
        and current >= last_low
        and (current > current_open or wick_rejection_long)
    )
    retest_resistance_short = (
        abs(current - last_high) <= atr_value * 0.35
        and current <= last_high
        and (current < current_open or wick_rejection_short)
    )

    # BOS / CHOCH interpretation
    state = "RANGE"
    if breakout_long and breakout_vol_ok:
        state = "BOS_UP" if structure_bias == "BULL" else "CHOCH_UP"
    elif breakout_short and breakout_vol_ok:
        state = "BOS_DOWN" if structure_bias == "BEAR" else "CHOCH_DOWN"
    elif structure_bias == "BULL":
        state = "TREND_UP"
    elif structure_bias == "BEAR":
        state = "TREND_DOWN"

    # Trend slope participation
    lr_vals = linreg_slope(c, period=min(20, len(c)))
    lr_last = 0.0
    if lr_vals:
        for x in reversed(lr_vals):
            if not np.isnan(x):
                lr_last = float(x)
                break

    strength = 34.0
    if structure_bias != "NEUTRAL":
        strength = 46.0
    strength += min(12.0, abs(lr_last) * 180.0)
    if breakout_long and breakout_vol_ok:
        strength += 14.0
    if breakout_short and breakout_vol_ok:
        strength += 14.0
    if retest_support_long and structure_bias != "BEAR":
        strength += 7.0
    if retest_resistance_short and structure_bias != "BULL":
        strength += 7.0
    if wick_rejection_long and structure_bias == "BULL":
        strength += 5.0
    if wick_rejection_short and structure_bias == "BEAR":
        strength += 5.0
    if vol_ratio >= 1.15:
        strength += 6.0
    elif vol_ratio < 0.85:
        strength -= 8.0
    if wick_rejection_long and wick_rejection_short:
        strength -= 6.0
    if structure_bias == "NEUTRAL" and not (breakout_long or breakout_short):
        strength -= 6.0

    invalidation_long = min(last_low, current_low) - (atr_value * 0.15)
    invalidation_short = max(last_high, current_high) + (atr_value * 0.15)
    long_dist = abs(current - invalidation_long) / max(atr_value, 1e-6)
    short_dist = abs(invalidation_short - current) / max(atr_value, 1e-6)

    out.update(
        {
            "state": state,
            "bias": structure_bias,
            "strength": int(_clamp(float(strength), 0.0, 100.0)),
            "breakout_long": bool(breakout_long and breakout_vol_ok),
            "breakout_short": bool(breakout_short and breakout_vol_ok),
            "breakout_volume_ratio": round(float(vol_ratio), 4),
            "retest_support_long": bool(retest_support_long),
            "retest_resistance_short": bool(retest_resistance_short),
            "wick_rejection_long": bool(wick_rejection_long),
            "wick_rejection_short": bool(wick_rejection_short),
            "invalidation_long": round(float(invalidation_long), 4),
            "invalidation_short": round(float(invalidation_short), 4),
            "invalidation_long_dist_atr": round(float(long_dist), 3),
            "invalidation_short_dist_atr": round(float(short_dist), 3),
        }
    )
    return out
