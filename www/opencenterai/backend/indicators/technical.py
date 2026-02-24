"""
OpenCenterAI Trading - Core Technical Indicators
=================================================
Moving averages, momentum oscillators, volatility, volume,
support/resistance, linear regression, and the main TechnicalAnalysis class.
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple


# =============================================================================
# MOVING AVERAGES
# =============================================================================

def sma(data: List[float], period: int) -> List[float]:
    """Simple Moving Average"""
    if len(data) < period:
        return [np.nan] * len(data)

    result = [np.nan] * (period - 1)
    for i in range(period - 1, len(data)):
        result.append(np.mean(data[i - period + 1:i + 1]))
    return result


def ema(data: List[float], period: int) -> List[float]:
    """Exponential Moving Average"""
    if len(data) < period:
        return [np.nan] * len(data)

    multiplier = 2 / (period + 1)
    result = [np.nan] * (period - 1)

    # Premier EMA = SMA
    first_ema = np.mean(data[:period])
    result.append(first_ema)

    # Calcul EMA
    for i in range(period, len(data)):
        new_ema = (data[i] - result[-1]) * multiplier + result[-1]
        result.append(new_ema)

    return result


def wma(data: List[float], period: int) -> List[float]:
    """Weighted Moving Average -- heavier weight on recent bars."""
    n = len(data)
    if n < period:
        return [np.nan] * n
    weights = list(range(1, period + 1))  # 1,2,...,period
    w_sum = sum(weights)
    result = [np.nan] * (period - 1)
    for i in range(period - 1, n):
        window = data[i - period + 1: i + 1]
        val = sum(w * v for w, v in zip(weights, window)) / w_sum
        result.append(val)
    return result


# =============================================================================
# MOMENTUM OSCILLATORS
# =============================================================================

def rsi(closes: List[float], period: int = 14) -> List[float]:
    """
    Relative Strength Index
    Retourne une liste de valeurs RSI (0-100)
    """
    if len(closes) < period + 1:
        return [50.0] * len(closes)

    result = [np.nan] * period

    # Calcul des deltas
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]

    # Premier calcul
    gains = [max(0, d) for d in deltas[:period]]
    losses = [abs(min(0, d)) for d in deltas[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(100.0 - (100.0 / (1 + rs)))

    # Calcul avec smoothing
    for i in range(period, len(deltas)):
        gain = max(0, deltas[i])
        loss = abs(min(0, deltas[i]))

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100.0 - (100.0 / (1 + rs)))

    return result


def stochastic(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    k_period: int = 14,
    d_period: int = 3,
    smooth: int = 3
) -> Tuple[List[float], List[float]]:
    """
    Stochastic Oscillator
    Retourne (K%, D%)
    """
    if len(closes) < k_period:
        return ([50.0] * len(closes), [50.0] * len(closes))

    raw_k = []
    for i in range(len(closes)):
        if i < k_period - 1:
            raw_k.append(np.nan)
        else:
            highest_high = max(highs[i - k_period + 1:i + 1])
            lowest_low = min(lows[i - k_period + 1:i + 1])

            if highest_high == lowest_low:
                raw_k.append(50.0)
            else:
                k_val = ((closes[i] - lowest_low) / (highest_high - lowest_low)) * 100
                raw_k.append(k_val)

    # Smooth K
    k_values = sma([v if not np.isnan(v) else 50.0 for v in raw_k], smooth)

    # D = SMA of K
    d_values = sma([v if not np.isnan(v) else 50.0 for v in k_values], d_period)

    return (k_values, d_values)


def macd(
    closes: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> Tuple[List[float], List[float], List[float]]:
    """
    MACD (Moving Average Convergence Divergence)
    Retourne (MACD line, Signal line, Histogram)
    """
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    # MACD Line = EMA fast - EMA slow
    macd_line = []
    for i in range(len(closes)):
        if np.isnan(ema_fast[i]) or np.isnan(ema_slow[i]):
            macd_line.append(np.nan)
        else:
            macd_line.append(ema_fast[i] - ema_slow[i])

    # Signal Line = EMA of MACD
    # Filtrer les NaN pour le calcul
    valid_macd = [v for v in macd_line if not np.isnan(v)]
    signal_line_valid = ema(valid_macd, signal)

    # Reconstruire avec les NaN
    signal_line = [np.nan] * (len(macd_line) - len(valid_macd)) + signal_line_valid

    # Histogram = MACD - Signal
    histogram = []
    for i in range(len(closes)):
        if np.isnan(macd_line[i]) or np.isnan(signal_line[i]):
            histogram.append(np.nan)
        else:
            histogram.append(macd_line[i] - signal_line[i])

    return (macd_line, signal_line, histogram)


def williams_r(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> List[float]:
    """
    Williams %R oscillator
    Returns values from -100 to 0
    """
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(-50.0)
        else:
            highest = max(highs[i - period + 1:i + 1])
            lowest = min(lows[i - period + 1:i + 1])
            if highest - lowest > 0:
                wr = -100 * (highest - closes[i]) / (highest - lowest)
            else:
                wr = -50.0
            result.append(wr)
    return result


def cci(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 20
) -> List[float]:
    """
    Commodity Channel Index.
    CCI = (TP - SMA(TP)) / (0.015 * Mean Deviation)
    """
    n = len(closes)
    if n < period:
        return [0.0] * n

    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    tp_sma = sma(tp, period)

    result = [np.nan] * (period - 1)

    for i in range(period - 1, n):
        if np.isnan(tp_sma[i]):
            result.append(0.0)
            continue

        # Mean Deviation
        md = np.mean([abs(tp[j] - tp_sma[i]) for j in range(i - period + 1, i + 1)])

        if md == 0:
            result.append(0.0)
        else:
            result.append((tp[i] - tp_sma[i]) / (0.015 * md))

    return result


# =============================================================================
# VOLATILITY
# =============================================================================

def atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> List[float]:
    """Average True Range"""
    if len(closes) < 2:
        return [0.0] * len(closes)

    true_ranges = [highs[0] - lows[0]]  # Premier TR = range de la premiere bougie

    for i in range(1, len(closes)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        true_ranges.append(max(tr1, tr2, tr3))

    # ATR = SMA des True Ranges
    return sma(true_ranges, period)


def bollinger_bands(
    closes: List[float],
    period: int = 20,
    std_dev: float = 2.0
) -> Tuple[List[float], List[float], List[float]]:
    """
    Bandes de Bollinger
    Retourne (Upper band, Middle band, Lower band)
    """
    middle = sma(closes, period)

    upper = []
    lower = []

    for i in range(len(closes)):
        if i < period - 1:
            upper.append(np.nan)
            lower.append(np.nan)
        else:
            std = np.std(closes[i - period + 1:i + 1])
            upper.append(middle[i] + std_dev * std)
            lower.append(middle[i] - std_dev * std)

    return (upper, middle, lower)


# =============================================================================
# TREND / DIRECTIONAL
# =============================================================================

def adx_dmi(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> Tuple[List[float], List[float], List[float]]:
    """
    Average Directional Index with DMI
    Returns (ADX, +DI, -DI)
    """
    if len(closes) < period + 1:
        return ([0.0] * len(closes), [0.0] * len(closes), [0.0] * len(closes))

    # True Range
    tr_list = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        tr_list.append(max(tr1, tr2, tr3))

    # Directional Movement
    plus_dm = [0.0]
    minus_dm = [0.0]
    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]

        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
        else:
            plus_dm.append(0.0)

        if down_move > up_move and down_move > 0:
            minus_dm.append(down_move)
        else:
            minus_dm.append(0.0)

    # Smoothed values
    atr_smooth = ema(tr_list, period)
    plus_dm_smooth = ema(plus_dm, period)
    minus_dm_smooth = ema(minus_dm, period)

    # DI calculations
    plus_di = []
    minus_di = []
    dx_list = []

    for i in range(len(closes)):
        if atr_smooth[i] and not np.isnan(atr_smooth[i]) and atr_smooth[i] > 0:
            pdi = 100 * plus_dm_smooth[i] / atr_smooth[i] if not np.isnan(plus_dm_smooth[i]) else 0
            mdi = 100 * minus_dm_smooth[i] / atr_smooth[i] if not np.isnan(minus_dm_smooth[i]) else 0
        else:
            pdi = 0.0
            mdi = 0.0

        plus_di.append(pdi)
        minus_di.append(mdi)

        # DX
        if pdi + mdi > 0:
            dx_list.append(100 * abs(pdi - mdi) / (pdi + mdi))
        else:
            dx_list.append(0.0)

    # ADX = EMA of DX
    adx_values = ema(dx_list, period)

    return (adx_values, plus_di, minus_di)


def linreg_slope(closes: List[float], period: int = 20) -> List[float]:
    """
    Pente de la regression lineaire sur `period` bougies.
    Valeur positive = tendance haussiere, negative = baissiere.
    Normalisee par le prix moyen pour comparabilite.
    """
    n = len(closes)
    if n < period:
        return [0.0] * n

    result = [np.nan] * (period - 1)
    x = np.arange(period, dtype=float)
    x_mean = np.mean(x)
    x_var = np.sum((x - x_mean) ** 2)

    for i in range(period - 1, n):
        y = np.array(closes[i - period + 1:i + 1], dtype=float)
        y_mean = np.mean(y)

        if x_var == 0 or y_mean == 0:
            result.append(0.0)
            continue

        slope = np.sum((x - x_mean) * (y - y_mean)) / x_var
        # Normaliser par le prix moyen (en pourcentage par bougie)
        result.append((slope / y_mean) * 100.0)

    return result


# =============================================================================
# VOLUME INDICATORS
# =============================================================================

def vwap(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float]
) -> List[float]:
    """
    Volume Weighted Average Price.
    Calcul cumulatif intraday-style.
    """
    n = len(closes)
    if n == 0 or not any(v > 0 for v in volumes):
        return [0.0] * n

    result = []
    cum_vol = 0.0
    cum_tp_vol = 0.0

    for i in range(n):
        typical_price = (highs[i] + lows[i] + closes[i]) / 3.0
        vol = volumes[i] if volumes[i] > 0 else 1.0
        cum_tp_vol += typical_price * vol
        cum_vol += vol
        result.append(cum_tp_vol / cum_vol if cum_vol > 0 else typical_price)

    return result


def obv(closes: List[float], volumes: List[float]) -> List[float]:
    """
    On-Balance Volume.
    Cumul des volumes ponderes par direction du prix.
    """
    n = len(closes)
    if n == 0:
        return []

    result = [0.0]
    for i in range(1, n):
        vol = volumes[i] if volumes[i] > 0 else 0.0
        if closes[i] > closes[i-1]:
            result.append(result[-1] + vol)
        elif closes[i] < closes[i-1]:
            result.append(result[-1] - vol)
        else:
            result.append(result[-1])

    return result


def accumulation_distribution(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float]
) -> List[float]:
    """
    Accumulation/Distribution Line.
    MFM = ((Close - Low) - (High - Close)) / (High - Low)
    AD = cum(MFM * Volume)
    """
    n = len(closes)
    if n == 0:
        return []

    result = [0.0]
    ad_val = 0.0

    for i in range(n):
        rng = highs[i] - lows[i]
        if rng > 0:
            mfm = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / rng
        else:
            mfm = 0.0

        vol = volumes[i] if volumes[i] > 0 else 0.0
        ad_val += mfm * vol

        if i == 0:
            result[0] = ad_val
        else:
            result.append(ad_val)

    return result


def mfi(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    period: int = 14
) -> List[float]:
    """
    Money Flow Index - RSI pondere par le volume.
    Retourne des valeurs 0-100.
    """
    n = len(closes)
    if n < period + 1:
        return [50.0] * n

    # Typical price
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]

    # Raw money flow
    raw_mf = [tp[i] * (volumes[i] if volumes[i] > 0 else 1.0) for i in range(n)]

    result = [np.nan] * period

    for i in range(period, n):
        pos_flow = 0.0
        neg_flow = 0.0

        for j in range(i - period + 1, i + 1):
            if j > 0 and tp[j] > tp[j-1]:
                pos_flow += raw_mf[j]
            elif j > 0 and tp[j] < tp[j-1]:
                neg_flow += raw_mf[j]

        if neg_flow == 0:
            result.append(100.0)
        else:
            money_ratio = pos_flow / neg_flow
            result.append(100.0 - (100.0 / (1.0 + money_ratio)))

    return result


def chaikin_money_flow(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    period: int = 20
) -> List[float]:
    """
    Chaikin Money Flow. Valeurs de -1 a +1.
    > 0 = pression acheteuse, < 0 = pression vendeuse.
    """
    n = len(closes)
    if n < period:
        return [0.0] * n

    result = [np.nan] * (period - 1)

    for i in range(period - 1, n):
        mfv_sum = 0.0
        vol_sum = 0.0

        for j in range(i - period + 1, i + 1):
            rng = highs[j] - lows[j]
            vol = volumes[j] if volumes[j] > 0 else 0.0

            if rng > 0:
                mfm = ((closes[j] - lows[j]) - (highs[j] - closes[j])) / rng
            else:
                mfm = 0.0

            mfv_sum += mfm * vol
            vol_sum += vol

        result.append(mfv_sum / vol_sum if vol_sum > 0 else 0.0)

    return result


# =============================================================================
# SUPPORT / RESISTANCE
# =============================================================================

def pivot_points(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback: int = 5
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """
    Detection des pivots hauts et bas
    Retourne (pivot_highs, pivot_lows)
    """
    pivot_highs: List[Optional[float]] = [None] * len(closes)
    pivot_lows: List[Optional[float]] = [None] * len(closes)

    for i in range(lookback, len(closes) - lookback):
        # Pivot High
        is_pivot_high = True
        for j in range(-lookback, lookback + 1):
            if j != 0 and highs[i + j] >= highs[i]:
                is_pivot_high = False
                break
        if is_pivot_high:
            pivot_highs[i] = highs[i]

        # Pivot Low
        is_pivot_low = True
        for j in range(-lookback, lookback + 1):
            if j != 0 and lows[i + j] <= lows[i]:
                is_pivot_low = False
                break
        if is_pivot_low:
            pivot_lows[i] = lows[i]

    return (pivot_highs, pivot_lows)


def fibonacci_levels(
    high: float,
    low: float,
    is_uptrend: bool = True
) -> Dict[str, float]:
    """
    Calculate Fibonacci retracement levels
    """
    diff = high - low

    if is_uptrend:
        # Retracement from high
        return {
            "0.0": high,
            "0.236": high - 0.236 * diff,
            "0.382": high - 0.382 * diff,
            "0.5": high - 0.5 * diff,
            "0.618": high - 0.618 * diff,
            "0.786": high - 0.786 * diff,
            "1.0": low,
        }
    else:
        # Retracement from low
        return {
            "0.0": low,
            "0.236": low + 0.236 * diff,
            "0.382": low + 0.382 * diff,
            "0.5": low + 0.5 * diff,
            "0.618": low + 0.618 * diff,
            "0.786": low + 0.786 * diff,
            "1.0": high,
        }


# =============================================================================
# HELPERS
# =============================================================================

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# =============================================================================
# MAIN CLASS - TechnicalAnalysis
# =============================================================================

class TechnicalAnalysis:
    """Classe pour l'analyse technique complete depuis les donnees IG.

    This is the main entry point that uses functions from all 4 indicator
    modules: technical (this file), advanced, patterns, and multi_tf.
    """

    def __init__(self, candles: List[Dict[str, Any]]):
        """
        candles: Liste de chandeliers depuis ig_service.get_historical_prices()
        """
        self.candles = candles

        # Extraire les series
        self.opens = [c['open'] for c in candles]
        self.highs = [c['high'] for c in candles]
        self.lows = [c['low'] for c in candles]
        self.closes = [c['close'] for c in candles]
        self.volumes = [c.get('volume', 0) for c in candles]

        # Cache des indicateurs calcules
        self._cache: Dict[str, Any] = {}

    @property
    def current_price(self) -> float:
        return self.closes[-1] if self.closes else 0.0

    # -----------------------------------------------------------------
    # Core indicators (from this module)
    # -----------------------------------------------------------------

    def get_rsi(self, period: int = 14) -> float:
        """RSI actuel"""
        key = f"rsi_{period}"
        if key not in self._cache:
            self._cache[key] = rsi(self.closes, period)
        values = self._cache[key]
        return values[-1] if values else 50.0

    def get_ema(self, period: int) -> float:
        """EMA actuelle"""
        key = f"ema_{period}"
        if key not in self._cache:
            self._cache[key] = ema(self.closes, period)
        values = self._cache[key]
        return values[-1] if values and not np.isnan(values[-1]) else 0.0

    def get_sma(self, period: int) -> float:
        """SMA actuelle"""
        key = f"sma_{period}"
        if key not in self._cache:
            self._cache[key] = sma(self.closes, period)
        values = self._cache[key]
        return values[-1] if values and not np.isnan(values[-1]) else 0.0

    def get_stochastic(self, k_period: int = 14) -> Tuple[float, float]:
        """Stochastique actuel (K, D)"""
        key = f"stoch_{k_period}"
        if key not in self._cache:
            self._cache[key] = stochastic(self.highs, self.lows, self.closes, k_period)
        k_vals, d_vals = self._cache[key]
        k = k_vals[-1] if k_vals and not np.isnan(k_vals[-1]) else 50.0
        d = d_vals[-1] if d_vals and not np.isnan(d_vals[-1]) else 50.0
        return (k, d)

    def get_macd(self) -> Tuple[float, float, float]:
        """MACD actuel (line, signal, histogram)"""
        if "macd" not in self._cache:
            self._cache["macd"] = macd(self.closes)
        line, signal_l, hist = self._cache["macd"]
        return (
            line[-1] if line and not np.isnan(line[-1]) else 0.0,
            signal_l[-1] if signal_l and not np.isnan(signal_l[-1]) else 0.0,
            hist[-1] if hist and not np.isnan(hist[-1]) else 0.0,
        )

    def get_atr(self, period: int = 14) -> float:
        """ATR actuel"""
        key = f"atr_{period}"
        if key not in self._cache:
            self._cache[key] = atr(self.highs, self.lows, self.closes, period)
        values = self._cache[key]
        return values[-1] if values and not np.isnan(values[-1]) else 0.0

    def get_bollinger(self, period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float]:
        """Bollinger Bands (upper, middle, lower)"""
        key = f"bb_{period}_{std_dev}"
        if key not in self._cache:
            self._cache[key] = bollinger_bands(self.closes, period, std_dev)
        upper, middle, lower = self._cache[key]
        return (
            upper[-1] if upper and not np.isnan(upper[-1]) else 0.0,
            middle[-1] if middle and not np.isnan(middle[-1]) else 0.0,
            lower[-1] if lower and not np.isnan(lower[-1]) else 0.0,
        )

    def get_adx(self, period: int = 14) -> Tuple[float, float, float]:
        """ADX with DMI (adx, +di, -di)"""
        key = f"adx_{period}"
        if key not in self._cache:
            self._cache[key] = adx_dmi(self.highs, self.lows, self.closes, period)
        adx_vals, plus_di, minus_di = self._cache[key]
        return (
            adx_vals[-1] if adx_vals and not np.isnan(adx_vals[-1]) else 0.0,
            plus_di[-1] if plus_di else 0.0,
            minus_di[-1] if minus_di else 0.0,
        )

    def get_williams_r(self, period: int = 14) -> float:
        """Williams %R"""
        key = f"wr_{period}"
        if key not in self._cache:
            self._cache[key] = williams_r(self.highs, self.lows, self.closes, period)
        values = self._cache[key]
        return values[-1] if values else -50.0

    def get_cci(self, period: int = 20) -> float:
        """CCI actuel"""
        key = f"cci_{period}"
        if key not in self._cache:
            self._cache[key] = cci(self.highs, self.lows, self.closes, period)
        values = self._cache[key]
        v = values[-1] if values else 0.0
        return v if not np.isnan(v) else 0.0

    def get_linreg_slope(self, period: int = 20) -> float:
        """Pente de la regression lineaire (% par bougie)"""
        key = f"lrs_{period}"
        if key not in self._cache:
            self._cache[key] = linreg_slope(self.closes, period)
        values = self._cache[key]
        v = values[-1] if values else 0.0
        return v if not np.isnan(v) else 0.0

    # -----------------------------------------------------------------
    # Volume indicators (from this module)
    # -----------------------------------------------------------------

    def get_vwap(self) -> float:
        """VWAP actuel"""
        if "vwap" not in self._cache:
            self._cache["vwap"] = vwap(self.highs, self.lows, self.closes, self.volumes)
        values = self._cache["vwap"]
        return values[-1] if values else 0.0

    def get_obv(self) -> float:
        """OBV actuel"""
        if "obv" not in self._cache:
            self._cache["obv"] = obv(self.closes, self.volumes)
        values = self._cache["obv"]
        return values[-1] if values else 0.0

    def get_obv_trend(self) -> str:
        """Tendance de l'OBV sur 10 dernieres bougies"""
        if "obv" not in self._cache:
            self._cache["obv"] = obv(self.closes, self.volumes)
        values = self._cache["obv"]
        if len(values) < 10:
            return "NEUTRAL"
        recent = values[-10:]
        slope = recent[-1] - recent[0]
        if slope > 0:
            return "RISING"
        elif slope < 0:
            return "FALLING"
        return "FLAT"

    def get_ad_line(self) -> float:
        """Accumulation/Distribution actuel"""
        if "ad" not in self._cache:
            self._cache["ad"] = accumulation_distribution(
                self.highs, self.lows, self.closes, self.volumes
            )
        values = self._cache["ad"]
        return values[-1] if values else 0.0

    def get_mfi(self, period: int = 14) -> float:
        """Money Flow Index actuel (0-100)"""
        key = f"mfi_{period}"
        if key not in self._cache:
            self._cache[key] = mfi(self.highs, self.lows, self.closes, self.volumes, period)
        values = self._cache[key]
        v = values[-1] if values else 50.0
        return v if not np.isnan(v) else 50.0

    def get_cmf(self, period: int = 20) -> float:
        """Chaikin Money Flow actuel (-1 a +1)"""
        key = f"cmf_{period}"
        if key not in self._cache:
            self._cache[key] = chaikin_money_flow(
                self.highs, self.lows, self.closes, self.volumes, period
            )
        values = self._cache[key]
        v = values[-1] if values else 0.0
        return v if not np.isnan(v) else 0.0

    # -----------------------------------------------------------------
    # Trend helpers
    # -----------------------------------------------------------------

    def get_trend(self) -> str:
        """Determine la tendance basee sur les EMAs"""
        ema9 = self.get_ema(9)
        ema21 = self.get_ema(21)
        ema50 = self.get_ema(50)

        if ema9 > ema21 > ema50:
            return "BULLISH"
        elif ema9 < ema21 < ema50:
            return "BEARISH"
        else:
            return "NEUTRAL"

    def get_trend_strength(self) -> str:
        """Trend strength based on ADX"""
        adx_val, _, _ = self.get_adx()
        if adx_val > 40:
            return "STRONG"
        elif adx_val > 25:
            return "MODERATE"
        elif adx_val > 15:
            return "WEAK"
        else:
            return "NO_TREND"

    def get_support_resistance(self) -> Tuple[List[float], List[float]]:
        """Auto-detected support and resistance levels"""
        if "sr" not in self._cache:
            from .patterns import auto_support_resistance
            self._cache["sr"] = auto_support_resistance(self.highs, self.lows, self.closes)
        return self._cache["sr"]

    def get_fibonacci(self, lookback: int = 50) -> Dict[str, float]:
        """Fibonacci retracement levels based on recent high/low"""
        recent_high = max(self.highs[-lookback:]) if len(self.highs) >= lookback else max(self.highs)
        recent_low = min(self.lows[-lookback:]) if len(self.lows) >= lookback else min(self.lows)

        # Determine trend
        is_uptrend = self.closes[-1] > (recent_high + recent_low) / 2

        return fibonacci_levels(recent_high, recent_low, is_uptrend)

    # -----------------------------------------------------------------
    # Advanced indicators (delegates to advanced module)
    # -----------------------------------------------------------------

    def get_ichimoku(self) -> Dict[str, Any]:
        """Signaux Ichimoku complets"""
        if "ichimoku" not in self._cache:
            from .advanced import ichimoku, ichimoku_signal
            ichi = ichimoku(self.highs, self.lows, self.closes)
            sig = ichimoku_signal(
                self.closes,
                ichi["tenkan_sen"], ichi["kijun_sen"],
                ichi["senkou_span_a"], ichi["senkou_span_b"]
            )
            # Valeurs actuelles
            idx = len(self.closes) - 1
            tenkan_val = ichi["tenkan_sen"][idx] if not np.isnan(ichi["tenkan_sen"][idx]) else 0.0
            kijun_val = ichi["kijun_sen"][idx] if not np.isnan(ichi["kijun_sen"][idx]) else 0.0
            sa_val = ichi["senkou_span_a"][idx] if idx < len(ichi["senkou_span_a"]) and not np.isnan(ichi["senkou_span_a"][idx]) else 0.0
            sb_val = ichi["senkou_span_b"][idx] if idx < len(ichi["senkou_span_b"]) and not np.isnan(ichi["senkou_span_b"][idx]) else 0.0

            self._cache["ichimoku"] = {
                "signal": sig["signal"],
                "cloud": sig["cloud"],
                "tk_cross": sig["tk_cross"],
                "tenkan": round(tenkan_val, 2),
                "kijun": round(kijun_val, 2),
                "senkou_a": round(sa_val, 2),
                "senkou_b": round(sb_val, 2),
            }
        return self._cache["ichimoku"]

    def get_keltner(self) -> Tuple[float, float, float]:
        """Keltner Channels (upper, middle, lower)"""
        if "keltner" not in self._cache:
            from .advanced import keltner_channels
            self._cache["keltner"] = keltner_channels(self.highs, self.lows, self.closes)
        upper, middle, lower = self._cache["keltner"]
        return (
            upper[-1] if upper and not np.isnan(upper[-1]) else 0.0,
            middle[-1] if middle and not np.isnan(middle[-1]) else 0.0,
            lower[-1] if lower and not np.isnan(lower[-1]) else 0.0,
        )

    def get_supertrend(self, period: int = 10, multiplier: float = 3.0) -> Dict[str, Any]:
        """Supertrend : valeur et direction"""
        key = f"st_{period}_{multiplier}"
        if key not in self._cache:
            from .advanced import supertrend
            st_vals, st_dirs = supertrend(self.highs, self.lows, self.closes, period, multiplier)
            self._cache[key] = {
                "value": round(st_vals[-1], 2) if st_vals else 0.0,
                "direction": st_dirs[-1] if st_dirs else "UP",
            }
        return self._cache[key]

    def get_qt_fusion(self, lookback: int = 20, smooth: int = 5) -> Dict[str, Any]:
        """QT Fusion oscillator -- standard: high=overbought, low=oversold."""
        key = f"qt_fusion_{lookback}_{smooth}"
        if key not in self._cache:
            from .advanced import qt_fusion
            self._cache[key] = qt_fusion(
                self.highs, self.lows, self.closes, self.volumes,
                lookback=lookback, smooth=smooth,
            )
        return self._cache[key]

    # -----------------------------------------------------------------
    # Pattern detection (delegates to patterns module)
    # -----------------------------------------------------------------

    def get_candlestick_patterns(self, lookback: int = 10) -> List[Dict[str, Any]]:
        """Patterns de bougies japonaises detectes recemment"""
        key = f"candle_patterns_{lookback}"
        if key not in self._cache:
            from .patterns import detect_candlestick_patterns
            self._cache[key] = detect_candlestick_patterns(
                self.opens, self.highs, self.lows, self.closes, lookback
            )
        return self._cache[key]

    def get_chart_patterns(self, lookback: int = 50) -> List[Dict[str, Any]]:
        """Structures chartistes detectees"""
        key = f"chart_patterns_{lookback}"
        if key not in self._cache:
            from .patterns import detect_chart_patterns
            self._cache[key] = detect_chart_patterns(
                self.highs, self.lows, self.closes, lookback
            )
        return self._cache[key]

    def get_market_structure(self, lookback: int = 120) -> Dict[str, Any]:
        """Contexte de structure de marche (BOS/CHOCH/rejets/retests/invalidation)."""
        key = f"market_structure_{lookback}"
        if key not in self._cache:
            from .patterns import analyze_market_structure
            self._cache[key] = analyze_market_structure(
                self.opens,
                self.highs,
                self.lows,
                self.closes,
                self.volumes,
                lookback=lookback,
            )
        return self._cache[key]

    # -----------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------

    def get_summary(self) -> Dict[str, Any]:
        """Resume complet de tous les indicateurs"""
        stoch_k, stoch_d = self.get_stochastic()
        macd_line, macd_signal, macd_hist = self.get_macd()
        bb_upper, bb_middle, bb_lower = self.get_bollinger()
        adx_val, plus_di, minus_di = self.get_adx()
        kelt_upper, kelt_middle, kelt_lower = self.get_keltner()
        supports, resistances = self.get_support_resistance()
        ichimoku_data = self.get_ichimoku()
        st_data = self.get_supertrend()
        market_structure = self.get_market_structure()

        return {
            # Price
            "price": self.current_price,

            # Trend
            "trend": self.get_trend(),
            "trend_strength": self.get_trend_strength(),

            # Momentum
            "rsi": round(self.get_rsi(), 2),
            "stoch_k": round(stoch_k, 2),
            "stoch_d": round(stoch_d, 2),
            "williams_r": round(self.get_williams_r(), 2),
            "cci": round(self.get_cci(), 2),
            "mfi": round(self.get_mfi(), 2),

            # MACD
            "macd_line": round(macd_line, 2),
            "macd_signal": round(macd_signal, 2),
            "macd_histogram": round(macd_hist, 2),

            # Moving Averages
            "ema9": round(self.get_ema(9), 2),
            "ema21": round(self.get_ema(21), 2),
            "ema50": round(self.get_ema(50), 2),
            "ema100": round(self.get_ema(100), 2),
            "ema200": round(self.get_ema(200), 2),

            # Volatility
            "atr": round(self.get_atr(), 2),

            # Bollinger
            "bollinger_upper": round(bb_upper, 2),
            "bollinger_middle": round(bb_middle, 2),
            "bollinger_lower": round(bb_lower, 2),

            # Keltner
            "keltner_upper": round(kelt_upper, 2),
            "keltner_middle": round(kelt_middle, 2),
            "keltner_lower": round(kelt_lower, 2),

            # ADX/DMI
            "adx": round(adx_val, 2),
            "plus_di": round(plus_di, 2),
            "minus_di": round(minus_di, 2),

            # Volume indicators
            "vwap": round(self.get_vwap(), 2),
            "obv": round(self.get_obv(), 2),
            "obv_trend": self.get_obv_trend(),
            "ad_line": round(self.get_ad_line(), 2),
            "cmf": round(self.get_cmf(), 4),

            # Ichimoku
            "ichimoku": ichimoku_data,

            # Supertrend
            "supertrend_value": st_data["value"],
            "supertrend_direction": st_data["direction"],

            # Linear Regression
            "linreg_slope_20": round(self.get_linreg_slope(20), 4),

            # Support/Resistance
            "supports": [round(s, 2) for s in supports[-3:]] if supports else [],
            "resistances": [round(r, 2) for r in resistances[-3:]] if resistances else [],

            # Fibonacci
            "fibonacci": {k: round(v, 2) for k, v in self.get_fibonacci().items()},

            # Candlestick patterns
            "candlestick_patterns": self.get_candlestick_patterns(),

            # Chart patterns
            "chart_patterns": self.get_chart_patterns(),
            "market_structure": market_structure,
        }
