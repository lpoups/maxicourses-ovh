"""
OpenCenterAI — AI Analysis Repository (MongoDB)
==================================================
Log toutes les analyses Claude pour audit et apprentissage.
TTL 90 jours automatique via index MongoDB.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db.mongo import get_db
from db.collections import AI_ANALYSES

logger = logging.getLogger(__name__)


def log_analysis(
    action: str,
    confidence: int,
    direction: Optional[str] = None,
    regime: Optional[str] = None,
    entry_mode: Optional[str] = None,
    thinking: Optional[str] = None,
    reason: Optional[str] = None,
    score_long: Optional[int] = None,
    score_short: Optional[int] = None,
    horizon_15m: Optional[str] = None,
    horizon_30m: Optional[str] = None,
    horizon_1h: Optional[str] = None,
    horizon_4h: Optional[str] = None,
    wait_reason_code: Optional[str] = None,
    model_used: Optional[str] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    latency_ms: Optional[int] = None,
    raw_response: Optional[Dict] = None,
) -> bool:
    """Enregistre une analyse IA dans MongoDB."""
    db = get_db()
    now = datetime.now(timezone.utc)

    doc = {
        "timestamp": now,
        "created_at": now,  # Pour le TTL index
        "action": action,
        "confidence": confidence,
        "direction": direction,
        "regime": regime,
        "entry_mode": entry_mode,
        "thinking": thinking,
        "reason": reason,
        "score_long": score_long,
        "score_short": score_short,
        "horizons": {
            "15m": horizon_15m,
            "30m": horizon_30m,
            "1h": horizon_1h,
            "4h": horizon_4h,
        },
        "wait_reason_code": wait_reason_code,
        "model_used": model_used,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
    }

    # Ne pas stocker le raw_response (trop volumineux)
    # Sauf si debug activé
    if raw_response and logger.isEnabledFor(logging.DEBUG):
        doc["raw_response"] = raw_response

    try:
        db[AI_ANALYSES].insert_one(doc)
        logger.debug("Analyse logged: %s conf=%d", action, confidence)
        return True
    except Exception as e:
        logger.error("Erreur log analyse: %s", e)
        return False


def get_latest_analysis() -> Optional[Dict]:
    """Retourne la dernière analyse."""
    db = get_db()
    doc = db[AI_ANALYSES].find_one(sort=[("timestamp", -1)])
    if doc:
        doc.pop("_id", None)
    return doc


def get_analyses(
    limit: int = 20,
    action_filter: Optional[str] = None,
) -> List[Dict]:
    """Retourne les analyses récentes avec filtre optionnel."""
    db = get_db()
    query: Dict[str, Any] = {}

    if action_filter:
        query["action"] = action_filter

    cursor = (
        db[AI_ANALYSES]
        .find(query)
        .sort("timestamp", -1)
        .limit(limit)
    )

    results = []
    for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


def get_analysis_stats(hours: int = 24) -> Dict:
    """Statistiques des analyses sur les N dernières heures."""
    db = get_db()
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    pipeline = [
        {"$match": {"timestamp": {"$gte": since}}},
        {
            "$group": {
                "_id": "$action",
                "count": {"$sum": 1},
                "avg_confidence": {"$avg": "$confidence"},
                "total_tokens_in": {"$sum": {"$ifNull": ["$tokens_in", 0]}},
                "total_tokens_out": {"$sum": {"$ifNull": ["$tokens_out", 0]}},
                "avg_latency_ms": {"$avg": {"$ifNull": ["$latency_ms", 0]}},
            }
        },
    ]

    results = list(db[AI_ANALYSES].aggregate(pipeline))
    stats = {}
    for r in results:
        action = r.pop("_id")
        stats[action] = r

    return {
        "period_hours": hours,
        "by_action": stats,
        "total_analyses": sum(s["count"] for s in stats.values()),
    }
