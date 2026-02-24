"""
OpenCenterAI — Market Data Endpoints (FastAPI)
================================================
Real-time ticker, OHLC candles, technical indicators.
"""

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.middleware import verify_auth
from config.constants import ETH_EPIC, RESOLUTION_MAP

logger = logging.getLogger(__name__)

# Mapping from user-facing resolution to ig_client.get_candles() format
_API_TO_IG_CLIENT_RES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}
router = APIRouter()


# ═════════════════════════════════════════════════════════════════
# PYDANTIC RESPONSE MODELS
# ═════════════════════════════════════════════════════════════════
class TickerResponse(BaseModel):
    epic: str
    name: str = ""
    bid: float = 0.0
    offer: float = 0.0
    mid: float = 0.0
    spread: float = 0.0
    high: float = 0.0
    low: float = 0.0
    change_pct: float = 0.0
    market_status: str = "CLOSED"


class CandleOut(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class CandlesResponse(BaseModel):
    epic: str
    resolution: str
    candles: List[CandleOut]
    count: int


class IndicatorValue(BaseModel):
    name: str
    value: Any
    signal: Optional[str] = None  # "BULLISH", "BEARISH", "NEUTRAL"


class IndicatorsResponse(BaseModel):
    epic: str
    timestamp: Optional[str] = None
    indicators: List[IndicatorValue]


class SentimentResponse(BaseModel):
    market_id: str
    long_pct: float
    short_pct: float
    bid: float = 0.0
    offer: float = 0.0
    spread: float = 0.0


# ═════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═════════════════════════════════════════════════════════════════

@router.get("/ticker", response_model=TickerResponse)
async def get_ticker(request: Request, user: str = Depends(verify_auth)):
    """
    Current ETH/USD price snapshot: bid, offer, spread, change%.
    Fetches live data from the IG broker client.
    """
    try:
        ig_client = request.app.state.ig_client
        ticker = ig_client.get_ticker(ETH_EPIC)
        if ticker is None:
            raise HTTPException(status_code=503, detail="Market data unavailable")

        return TickerResponse(
            epic=ticker.epic,
            name=ticker.name,
            bid=ticker.bid,
            offer=ticker.offer,
            mid=round((ticker.bid + ticker.offer) / 2, 2),
            spread=round(ticker.offer - ticker.bid, 2),
            high=ticker.high,
            low=ticker.low,
            change_pct=ticker.change_pct,
            market_status=ticker.market_status,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching ticker")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candles", response_model=CandlesResponse)
async def get_candles(
    request: Request,
    resolution: str = Query("5m", description="Candle resolution: 1m, 5m, 15m, 30m, 1h, 4h, 1d"),
    count: int = Query(100, ge=1, le=10080, description="Number of candles (max 10080 = 1 week of 1m)"),
    user: str = Depends(verify_auth),
):
    """
    OHLC candle data for ETH/USD.
    Supported resolutions: 1m, 5m, 15m, 30m, 1h, 4h, 1d.
    """
    ig_client_res = _API_TO_IG_CLIENT_RES.get(resolution)
    if ig_client_res is None:
        valid = ", ".join(sorted(_API_TO_IG_CLIENT_RES.keys()))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resolution '{resolution}'. Valid: {valid}",
        )

    try:
        ig_client = request.app.state.ig_client
        candles = ig_client.get_candles(ETH_EPIC, ig_client_res, count)
        if candles is None:
            candles = []

        # If IG returned volume=0, supplement with tick counts from MongoDB
        has_zero_vol = any(c.volume == 0 for c in candles)
        tick_counts: dict = {}
        if has_zero_vol and candles:
            try:
                from db.mongo import get_db
                from db.collections import CANDLE_CACHE
                db = get_db()
                # Map API resolution to TickCollector resolution format
                res_to_tick = {
                    "1min": "1Min", "5min": "5Min", "15min": "15Min",
                    "30min": "30Min", "1h": "1H", "4h": "4H", "1D": "1D",
                }
                tick_res = res_to_tick.get(ig_client_res, ig_client_res)
                timestamps = [c.timestamp for c in candles if c.volume == 0]
                docs = db[CANDLE_CACHE].find(
                    {"epic": ETH_EPIC, "resolution": tick_res, "timestamp": {"$in": timestamps}},
                    {"_id": 0, "timestamp": 1, "volume": 1},
                )
                for d in docs:
                    vol = d.get("volume", 0)
                    if vol > 0:
                        tick_counts[d["timestamp"]] = vol
            except Exception as exc:
                logger.debug("Tick count merge failed: %s", exc)

        candle_list = [
            CandleOut(
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume if c.volume > 0 else tick_counts.get(c.timestamp, 0),
            )
            for c in candles
        ]

        return CandlesResponse(
            epic=ETH_EPIC,
            resolution=resolution,
            candles=candle_list,
            count=len(candle_list),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching candles")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/indicators", response_model=IndicatorsResponse)
async def get_indicators(request: Request, user: str = Depends(verify_auth)):
    """
    Technical indicators snapshot: RSI, MACD, Bollinger Bands, ATR, EMAs, etc.
    Computed from the latest 5m candles.
    """
    try:
        # Get candles from IG client, then compute indicators
        ig_client = request.app.state.ig_client
        candles = ig_client.get_candles(ETH_EPIC, "5min", 200)

        if not candles:
            raise HTTPException(status_code=503, detail="Indicators unavailable (no candle data)")

        # Build OHLCV arrays for TechnicalAnalysis
        import numpy as np
        opens = np.array([c.open for c in candles], dtype=float)
        highs = np.array([c.high for c in candles], dtype=float)
        lows = np.array([c.low for c in candles], dtype=float)
        closes = np.array([c.close for c in candles], dtype=float)
        volumes = np.array([c.volume for c in candles], dtype=float)

        from indicators.technical import rsi, macd, bollinger_bands, atr, stochastic, adx_dmi, vwap, obv, cci, mfi

        # Compute key indicators
        result = {}

        # RSI
        rsi_val = rsi(closes)
        if len(rsi_val) > 0:
            v = float(rsi_val[-1])
            result["rsi_14"] = {"value": round(v, 2), "signal": "OVERBOUGHT" if v > 70 else "OVERSOLD" if v < 30 else "NEUTRAL"}

        # MACD
        macd_line, signal_line, histogram = macd(closes)
        if len(macd_line) > 0:
            result["macd"] = {"value": round(float(macd_line[-1]), 4), "signal": "BULLISH" if float(histogram[-1]) > 0 else "BEARISH"}

        # Bollinger Bands
        upper, middle, lower = bollinger_bands(closes)
        if len(upper) > 0:
            last_close = float(closes[-1])
            bb_pos = "UPPER" if last_close > float(upper[-1]) else "LOWER" if last_close < float(lower[-1]) else "MIDDLE"
            result["bollinger"] = {"value": {"upper": round(float(upper[-1]), 2), "middle": round(float(middle[-1]), 2), "lower": round(float(lower[-1]), 2)}, "signal": bb_pos}

        # ATR
        atr_val = atr(highs, lows, closes)
        if len(atr_val) > 0:
            result["atr_14"] = {"value": round(float(atr_val[-1]), 2)}

        # Stochastic
        k, d = stochastic(highs, lows, closes)
        if len(k) > 0:
            kv = float(k[-1])
            result["stochastic"] = {"value": {"k": round(kv, 2), "d": round(float(d[-1]), 2)}, "signal": "OVERBOUGHT" if kv > 80 else "OVERSOLD" if kv < 20 else "NEUTRAL"}

        # ADX
        adx_val, plus_di, minus_di = adx_dmi(highs, lows, closes)
        if len(adx_val) > 0:
            av = float(adx_val[-1])
            trend = "STRONG_TREND" if av > 25 else "WEAK_TREND"
            result["adx"] = {"value": round(av, 2), "signal": trend}

        # EMAs
        from indicators.technical import ema
        for period in [9, 21, 50, 200]:
            ema_val = ema(closes, period)
            if len(ema_val) > 0:
                result[f"ema_{period}"] = {"value": round(float(ema_val[-1]), 2)}

        indicators = []
        for name, info in result.items():
            if isinstance(info, dict):
                indicators.append(
                    IndicatorValue(
                        name=name,
                        value=info.get("value"),
                        signal=info.get("signal"),
                    )
                )
            else:
                indicators.append(IndicatorValue(name=name, value=info))

        return IndicatorsResponse(
            epic=ETH_EPIC,
            indicators=indicators,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error computing indicators")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sentiment", response_model=SentimentResponse)
async def get_sentiment(request: Request, user: str = Depends(verify_auth)):
    """
    Client sentiment: % of IG clients long vs short on ETH/USD.
    Also returns current bid/offer for the order book display.
    """
    try:
        ig_client = request.app.state.ig_client
        sentiment = ig_client.get_sentiment("ETHUSD")
        if sentiment is None:
            raise HTTPException(status_code=503, detail="Sentiment data unavailable")

        # Also get current bid/offer for spread display
        ticker = ig_client.get_ticker(ETH_EPIC)
        bid = ticker.bid if ticker else 0.0
        offer = ticker.offer if ticker else 0.0

        return SentimentResponse(
            market_id=sentiment.get("market_id", "ETHUSD"),
            long_pct=sentiment.get("long_pct", 50),
            short_pct=sentiment.get("short_pct", 50),
            bid=bid,
            offer=offer,
            spread=round(offer - bid, 2) if bid > 0 else 0,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching sentiment")
        raise HTTPException(status_code=500, detail=str(e))
