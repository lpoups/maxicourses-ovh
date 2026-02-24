"""
OpenCenterAI Trading — Constantes immuables
=============================================
Valeurs fixes qui ne changent JAMAIS au runtime.
"""

from zoneinfo import ZoneInfo

# ═══════════════════════════════════════════════════════════════
# INSTRUMENTS IG
# ═══════════════════════════════════════════════════════════════
ETH_EPIC = "CS.D.ETHUSD.CFD.IP"
BTC_EPIC = "CS.D.BITCOIN.CFD.IP"
ETH_CURRENCY = "USD"

# ═══════════════════════════════════════════════════════════════
# TIMEZONE
# ═══════════════════════════════════════════════════════════════
PARIS_TZ = ZoneInfo("Europe/Paris")
UTC_TZ = ZoneInfo("UTC")

# ═══════════════════════════════════════════════════════════════
# IG API URLS
# ═══════════════════════════════════════════════════════════════
IG_DEMO_URL = "https://demo-api.ig.com/gateway/deal"
IG_LIVE_URL = "https://api.ig.com/gateway/deal"

# ═══════════════════════════════════════════════════════════════
# TIMEFRAMES
# ═══════════════════════════════════════════════════════════════
PRIMARY_TIMEFRAME = "MINUTE_5"
TREND_TIMEFRAME = "HOUR"
SWING_TIMEFRAME = "HOUR_4"

# Mapping résolutions pour l'API IG
RESOLUTION_MAP = {
    "1m": "MINUTE",
    "5m": "MINUTE_5",
    "15m": "MINUTE_15",
    "30m": "MINUTE_30",
    "1h": "HOUR",
    "4h": "HOUR_4",
    "1d": "DAY",
}

# ═══════════════════════════════════════════════════════════════
# SIGNAL MAPPING — UN SEUL ENDROIT, JAMAIS D'INVERSION
# ═══════════════════════════════════════════════════════════════
SIGNAL_TO_DIRECTION = {
    "LONG": "BUY",
    "SHORT": "SELL",
}

DIRECTION_TO_CLOSE = {
    "BUY": "SELL",
    "SELL": "BUY",
}

# ═══════════════════════════════════════════════════════════════
# VALID ACTIONS (from Claude AI)
# ═══════════════════════════════════════════════════════════════
VALID_ENTRY_ACTIONS = {"LONG", "SHORT"}
VALID_WAIT_ACTIONS = {"WAIT", "HOLD"}
VALID_EXIT_ACTIONS = {"EXIT_LONG", "EXIT_SHORT", "QUITTER"}
VALID_ALL_ACTIONS = VALID_ENTRY_ACTIONS | VALID_WAIT_ACTIONS | VALID_EXIT_ACTIONS

# ═══════════════════════════════════════════════════════════════
# MARKET REGIMES
# ═══════════════════════════════════════════════════════════════
VALID_REGIMES = {
    "TREND_UP", "TREND_DOWN",
    "RANGE", "RANGE_TIGHT",
    "BREAKOUT_UP", "BREAKOUT_DOWN",
    "TRANSITION", "CHOPPY",
    "VOLATILE",
}

# ═══════════════════════════════════════════════════════════════
# TRAILING STOP TIERS (software-based, IG rejects SL modification on ETH)
# ═══════════════════════════════════════════════════════════════
TRAILING_TIERS = [
    # (profit_pct, lock_pct) — lock_pct of entry price as new floor
    (0.005, 0.000),   # +0.5% profit → lock breakeven
    (0.010, 0.003),   # +1.0% → lock +0.3%
    (0.015, 0.007),   # +1.5% → lock +0.7%
    (0.020, 0.012),   # +2.0% → lock +1.2%
    (0.025, 0.018),   # +2.5% → lock +1.8%
    (0.035, 0.025),   # +3.5% → lock +2.5%
]

# ═══════════════════════════════════════════════════════════════
# DRAWDOWN CONFIDENCE BOOST TIERS
# ═══════════════════════════════════════════════════════════════
DRAWDOWN_CONF_BOOST_TIERS = [
    (-20.0, 3),    # -20 EUR daily → +3% min confidence
    (-35.0, 5),    # -35 EUR → +5%
    (-45.0, 10),   # -45 EUR → +10% (approaching daily limit)
]

# ═══════════════════════════════════════════════════════════════
# APP VERSION
# ═══════════════════════════════════════════════════════════════
APP_NAME = "OpenCenterAI"
APP_VERSION = "2.0.0"
ENGINE_VERSION = "v2.0"
