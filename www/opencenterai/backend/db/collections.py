"""
OpenCenterAI — MongoDB Collections & Index Definitions
========================================================
Toutes les collections et leurs index en un seul endroit.
"""

from pymongo import ASCENDING, DESCENDING

# ═══════════════════════════════════════════════════════════════
# COLLECTION NAMES
# ═══════════════════════════════════════════════════════════════
TRADES = "trades"
AI_ANALYSES = "ai_analyses"
CONFIG = "config"
CONFIG_HISTORY = "config_history"
DAILY_PERF = "daily_perf"
KNOWLEDGE = "knowledge"
SESSIONS = "sessions"
AUDIT_LOG = "audit_log"
CANDLE_CACHE = "candle_cache"

# ═══════════════════════════════════════════════════════════════
# INDEX DEFINITIONS
# ═══════════════════════════════════════════════════════════════
INDEXES = {
    TRADES: [
        {
            "keys": [("trade_id", ASCENDING)],
            "unique": True,
            "name": "idx_trade_id_unique",
        },
        {
            "keys": [("open_timestamp", DESCENDING)],
            "name": "idx_open_ts",
        },
        {
            "keys": [("status", ASCENDING), ("close_timestamp", DESCENDING)],
            "name": "idx_status_close",
        },
        {
            "keys": [("direction", ASCENDING), ("close_timestamp", DESCENDING)],
            "name": "idx_dir_close",
        },
    ],
    AI_ANALYSES: [
        {
            "keys": [("timestamp", DESCENDING)],
            "name": "idx_analysis_ts",
        },
        {
            "keys": [("action", ASCENDING), ("timestamp", DESCENDING)],
            "name": "idx_action_ts",
        },
        {
            "keys": [("created_at", ASCENDING)],
            "name": "idx_ttl_analyses",
            "expireAfterSeconds": 90 * 86400,  # 90 jours TTL
        },
    ],
    CONFIG: [
        {
            "keys": [("key", ASCENDING)],
            "unique": True,
            "name": "idx_config_key",
        },
    ],
    CONFIG_HISTORY: [
        {
            "keys": [("timestamp", DESCENDING)],
            "name": "idx_config_hist_ts",
        },
        {
            "keys": [("created_at", ASCENDING)],
            "name": "idx_ttl_config_hist",
            "expireAfterSeconds": 180 * 86400,  # 180 jours TTL
        },
    ],
    DAILY_PERF: [
        {
            "keys": [("date", DESCENDING)],
            "unique": True,
            "name": "idx_daily_date",
        },
    ],
    KNOWLEDGE: [
        {
            "keys": [("type", ASCENDING)],
            "name": "idx_knowledge_type",
        },
    ],
    SESSIONS: [
        {
            "keys": [("created_at", ASCENDING)],
            "name": "idx_ttl_sessions",
            "expireAfterSeconds": 86400,  # 24h TTL
        },
        {
            "keys": [("account_id", ASCENDING)],
            "name": "idx_session_account",
        },
    ],
    AUDIT_LOG: [
        {
            "keys": [("timestamp", DESCENDING)],
            "name": "idx_audit_ts",
        },
        {
            "keys": [("created_at", ASCENDING)],
            "name": "idx_ttl_audit",
            "expireAfterSeconds": 30 * 86400,  # 30 jours TTL
        },
    ],
    CANDLE_CACHE: [
        {
            "keys": [("epic", ASCENDING), ("resolution", ASCENDING), ("timestamp", ASCENDING)],
            "unique": True,
            "name": "idx_candle_unique",
        },
        {
            "keys": [("epic", ASCENDING), ("resolution", ASCENDING), ("timestamp", DESCENDING)],
            "name": "idx_candle_query",
        },
    ],
}
