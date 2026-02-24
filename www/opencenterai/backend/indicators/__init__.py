"""
OpenCenterAI Trading - Indicators Package
==========================================
Reorganised indicator library split into four modules:

- technical : core indicators (MA, RSI, MACD, ATR, ...) + TechnicalAnalysis class
- advanced  : Ichimoku, Supertrend, QT Fusion, Keltner
- patterns  : candlestick patterns, chart patterns, divergences, S/R
- multi_tf  : multi-timeframe confluence analysis
"""

from .technical import TechnicalAnalysis  # noqa: F401
