"""
OpenCenterAI Trading - Advanced Indicators
===========================================
Ichimoku Cloud, Supertrend, QT Fusion oscillator, Keltner Channels.
"""

import numpy as np
from typing import List, Dict, Any, Tuple

from .technical import sma, ema, wma, atr, mfi


# =============================================================================
# ICHIMOKU CLOUD
# =============================================================================

def ichimoku(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52
) -> Dict[str, List[float]]:
    """
    Ichimoku Cloud (Kinko Hyo).
    Retourne: tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b, chikou_span.
    Les Senkou sont projetes 26 periodes en avant (padded avec NaN).
    """
    n = len(closes)

    def mid_channel(data_h: List[float], data_l: List[float], period: int, idx: int) -> float:
        if idx < period - 1:
            return np.nan
        segment_h = data_h[idx - period + 1:idx + 1]
        segment_l = data_l[idx - period + 1:idx + 1]
        return (max(segment_h) + min(segment_l)) / 2.0

    tenkan = [mid_channel(highs, lows, tenkan_period, i) for i in range(n)]
    kijun = [mid_channel(highs, lows, kijun_period, i) for i in range(n)]

    # Senkou Span A = (Tenkan + Kijun) / 2, projete 26 periodes en avant
    senkou_a_raw = []
    for i in range(n):
        if not np.isnan(tenkan[i]) and not np.isnan(kijun[i]):
            senkou_a_raw.append((tenkan[i] + kijun[i]) / 2.0)
        else:
            senkou_a_raw.append(np.nan)

    # Senkou Span B = midpoint(52 periods), projete 26 periodes en avant
    senkou_b_raw = [mid_channel(highs, lows, senkou_b_period, i) for i in range(n)]

    # Projection de 26 periodes : on decale les valeurs
    shift = kijun_period
    senkou_a = [np.nan] * shift + senkou_a_raw[:n - shift] if n > shift else senkou_a_raw
    senkou_b = [np.nan] * shift + senkou_b_raw[:n - shift] if n > shift else senkou_b_raw

    # Chikou Span = close projete 26 periodes en arriere
    chikou = closes[shift:] + [np.nan] * shift if n > shift else closes

    return {
        "tenkan_sen": tenkan,
        "kijun_sen": kijun,
        "senkou_span_a": senkou_a,
        "senkou_span_b": senkou_b,
        "chikou_span": chikou,
    }


def ichimoku_signal(
    closes: List[float],
    tenkan: List[float],
    kijun: List[float],
    senkou_a: List[float],
    senkou_b: List[float]
) -> Dict[str, Any]:
    """
    Interpreter les signaux Ichimoku pour la derniere bougie.
    """
    if not closes:
        return {"signal": "NEUTRAL", "cloud": "NEUTRAL", "tk_cross": "NONE"}

    idx = len(closes) - 1
    price = closes[idx]

    # Position par rapport au cloud
    sa = senkou_a[idx] if idx < len(senkou_a) and not np.isnan(senkou_a[idx]) else None
    sb = senkou_b[idx] if idx < len(senkou_b) and not np.isnan(senkou_b[idx]) else None

    cloud = "NEUTRAL"
    if sa is not None and sb is not None:
        cloud_top = max(sa, sb)
        cloud_bottom = min(sa, sb)
        if price > cloud_top:
            cloud = "ABOVE_CLOUD"  # bullish
        elif price < cloud_bottom:
            cloud = "BELOW_CLOUD"  # bearish
        else:
            cloud = "IN_CLOUD"  # indecision

    # TK Cross
    tk_cross = "NONE"
    tk = tenkan[idx] if idx < len(tenkan) and not np.isnan(tenkan[idx]) else None
    kj = kijun[idx] if idx < len(kijun) and not np.isnan(kijun[idx]) else None
    if tk is not None and kj is not None and idx > 0:
        tk_prev = tenkan[idx-1] if not np.isnan(tenkan[idx-1]) else None
        kj_prev = kijun[idx-1] if not np.isnan(kijun[idx-1]) else None
        if tk_prev is not None and kj_prev is not None:
            if tk_prev <= kj_prev and tk > kj:
                tk_cross = "BULL_CROSS"
            elif tk_prev >= kj_prev and tk < kj:
                tk_cross = "BEAR_CROSS"

    # Signal global
    signal = "NEUTRAL"
    if cloud == "ABOVE_CLOUD" and tk_cross == "BULL_CROSS":
        signal = "STRONG_BULL"
    elif cloud == "ABOVE_CLOUD":
        signal = "BULL"
    elif cloud == "BELOW_CLOUD" and tk_cross == "BEAR_CROSS":
        signal = "STRONG_BEAR"
    elif cloud == "BELOW_CLOUD":
        signal = "BEAR"

    return {"signal": signal, "cloud": cloud, "tk_cross": tk_cross}


# =============================================================================
# SUPERTREND
# =============================================================================

def supertrend(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 10,
    multiplier: float = 3.0
) -> Tuple[List[float], List[str]]:
    """
    Supertrend indicator.
    Retourne (supertrend_values, directions) ou direction = "UP"/"DOWN".
    UP = prix au-dessus du supertrend (bullish), DOWN = bearish.
    """
    n = len(closes)
    if n < period + 1:
        return ([0.0] * n, ["UP"] * n)

    atr_vals = atr(highs, lows, closes, period)

    upper_band = [0.0] * n
    lower_band = [0.0] * n
    supertrend_vals = [0.0] * n
    direction = ["UP"] * n

    for i in range(n):
        hl2 = (highs[i] + lows[i]) / 2.0
        atr_v = atr_vals[i] if not np.isnan(atr_vals[i]) else 0.0

        upper_band[i] = hl2 + multiplier * atr_v
        lower_band[i] = hl2 - multiplier * atr_v

        if i == 0:
            supertrend_vals[i] = lower_band[i]
            direction[i] = "UP"
            continue

        # Ajuster les bandes
        if lower_band[i] > lower_band[i-1] or closes[i-1] < lower_band[i-1]:
            pass  # garder la valeur calculee
        else:
            lower_band[i] = lower_band[i-1]

        if upper_band[i] < upper_band[i-1] or closes[i-1] > upper_band[i-1]:
            pass
        else:
            upper_band[i] = upper_band[i-1]

        # Direction
        if direction[i-1] == "UP":
            if closes[i] < lower_band[i]:
                direction[i] = "DOWN"
                supertrend_vals[i] = upper_band[i]
            else:
                direction[i] = "UP"
                supertrend_vals[i] = lower_band[i]
        else:
            if closes[i] > upper_band[i]:
                direction[i] = "UP"
                supertrend_vals[i] = lower_band[i]
            else:
                direction[i] = "DOWN"
                supertrend_vals[i] = upper_band[i]

    return (supertrend_vals, direction)


# =============================================================================
# QT FUSION OSCILLATOR  (BUG FIX: standard orientation)
# =============================================================================

def qt_fusion(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    lookback: int = 20,
    smooth: int = 5,
) -> Dict[str, Any]:
    """
    QT Fusion oscillator (standard orientation):
        high values (>75) = overbought / sell opportunity,
        low  values (<25) = oversold  / buy opportunity.
    Combines normalised price (60 %) + MFI (40 %).
    Returns dict with fast/signal lines, signal flags, and state.

    NOTE: The original code had an inversion bug where the raw value
    was computed as ``(1 - composite) * 100``, making 100 = low price
    and 0 = high price.  This version uses ``composite * 100`` so the
    scale is standard: 100 = high, 0 = low.
    """
    n = len(closes)
    empty: Dict[str, Any] = {
        "fast": 50.0, "signal": 50.0, "buy_signal": False,
        "sell_signal": False, "zone": "NEUTRAL", "cross": "NONE",
    }
    if n < max(lookback, 14) + smooth * 2 + 2:
        return empty

    # 1. MFI series (0-100)
    mfi_series = mfi(highs, lows, closes, volumes, 14)

    # 2. Build raw fusion series
    fusion_raw: List[float] = []
    for i in range(n):
        # Highest high / lowest low over lookback
        start = max(0, i - lookback + 1)
        ph = max(highs[start: i + 1])
        pl = min(lows[start: i + 1])
        rng = ph - pl
        norm_price = 0.5 if rng == 0 else (closes[i] - pl) / rng
        mfi_val = (mfi_series[i] / 100.0) if not np.isnan(mfi_series[i]) else 0.5
        # FIXED: standard orientation -- high value = high price/momentum
        raw = (norm_price * 0.6 + mfi_val * 0.4) * 100.0
        fusion_raw.append(raw)

    # 3. Smooth: WMA fast + WMA signal
    fast_line = wma(fusion_raw, smooth)
    signal_line = wma(fast_line, smooth * 2)

    # 4. Current values
    fast = fast_line[-1] if not np.isnan(fast_line[-1]) else 50.0
    sig = signal_line[-1] if not np.isnan(signal_line[-1]) else 50.0

    # 5. Cross detection (need at least 2 bars)
    cross = "NONE"
    buy_signal = False
    sell_signal = False
    if len(fast_line) >= 2 and len(signal_line) >= 2:
        f_now, f_prev = fast_line[-1], fast_line[-2]
        s_now, s_prev = signal_line[-1], signal_line[-2]
        if not any(np.isnan(x) for x in [f_now, f_prev, s_now, s_prev]):
            crossed_up = f_prev <= s_prev and f_now > s_now
            crossed_down = f_prev >= s_prev and f_now < s_now
            if crossed_up or crossed_down:
                cross = "UP" if crossed_up else "DOWN"
                # Standard orientation: low values (<25) = buy zone
                if (crossed_up or crossed_down) and fast < 25:
                    buy_signal = True
                # Standard orientation: high values (>75) = sell zone
                if (crossed_up or crossed_down) and fast > 75:
                    sell_signal = True

    # 6. Zone (standard orientation)
    zone = "SELL_ZONE" if fast > 75 else "BUY_ZONE" if fast < 25 else "NEUTRAL"

    return {
        "fast": round(fast, 2),
        "signal": round(sig, 2),
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
        "zone": zone,
        "cross": cross,
    }


# =============================================================================
# KELTNER CHANNELS
# =============================================================================

def keltner_channels(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    ema_period: int = 20,
    atr_period: int = 14,
    atr_mult: float = 1.5
) -> Tuple[List[float], List[float], List[float]]:
    """
    Keltner Channels
    Returns (upper, middle, lower)
    """
    middle = ema(closes, ema_period)
    atr_vals = atr(highs, lows, closes, atr_period)

    upper = []
    lower = []
    for i in range(len(closes)):
        if np.isnan(middle[i]) or np.isnan(atr_vals[i]):
            upper.append(np.nan)
            lower.append(np.nan)
        else:
            upper.append(middle[i] + atr_mult * atr_vals[i])
            lower.append(middle[i] - atr_mult * atr_vals[i])

    return (upper, middle, lower)
