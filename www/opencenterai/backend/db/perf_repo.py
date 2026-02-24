"""
OpenCenterAI — Performance Repository (MongoDB)
==================================================
Remplace performance_24h_report.json.
Calcule et persiste les métriques de performance.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from db.mongo import get_db
from db.collections import DAILY_PERF, TRADES

logger = logging.getLogger(__name__)


def compute_daily_perf(date: Optional[str] = None) -> Dict:
    """
    Calcule les performances pour une date donnée.
    Par défaut : aujourd'hui.
    """
    db = get_db()

    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    day_start = datetime.fromisoformat(f"{date}T00:00:00+00:00")
    day_end = day_start + timedelta(days=1)

    pipeline = [
        {
            "$match": {
                "close_timestamp": {"$gte": day_start, "$lt": day_end},
                "status": {"$in": ["WIN", "LOSS"]},
            }
        },
        {
            "$group": {
                "_id": None,
                "total_trades": {"$sum": 1},
                "wins": {"$sum": {"$cond": [{"$eq": ["$status", "WIN"]}, 1, 0]}},
                "losses": {"$sum": {"$cond": [{"$eq": ["$status", "LOSS"]}, 1, 0]}},
                "total_pnl": {"$sum": "$pnl_eur"},
                "gross_profit": {
                    "$sum": {"$cond": [{"$gt": ["$pnl_eur", 0]}, "$pnl_eur", 0]}
                },
                "gross_loss": {
                    "$sum": {"$cond": [{"$lt": ["$pnl_eur", 0]}, "$pnl_eur", 0]}
                },
                "max_win": {"$max": "$pnl_eur"},
                "max_loss": {"$min": "$pnl_eur"},
                "avg_duration": {"$avg": "$duration_sec"},
                "avg_pnl": {"$avg": "$pnl_eur"},
            }
        },
    ]

    results = list(db[TRADES].aggregate(pipeline))

    if not results:
        return {
            "date": date,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_pnl_eur": 0.0,
            "profit_factor": 0.0,
        }

    r = results[0]
    r.pop("_id", None)

    total = r["total_trades"]
    win_rate = round((r["wins"] / total * 100) if total > 0 else 0, 1)
    profit_factor = round(
        abs(r["gross_profit"] / r["gross_loss"]) if r["gross_loss"] != 0 else 0, 2
    )

    perf = {
        "date": date,
        "total_trades": total,
        "wins": r["wins"],
        "losses": r["losses"],
        "win_rate_pct": win_rate,
        "total_pnl_eur": round(r["total_pnl"], 2),
        "gross_profit_eur": round(r["gross_profit"], 2),
        "gross_loss_eur": round(r["gross_loss"], 2),
        "profit_factor": profit_factor,
        "max_win_eur": round(r.get("max_win", 0) or 0, 2),
        "max_loss_eur": round(r.get("max_loss", 0) or 0, 2),
        "avg_pnl_eur": round(r.get("avg_pnl", 0) or 0, 2),
        "avg_duration_sec": round(r.get("avg_duration", 0) or 0, 0),
        "computed_at": datetime.now(timezone.utc),
    }

    # Persister
    _save_daily_perf(perf)

    return perf


def _save_daily_perf(perf: Dict):
    """Sauvegarde le rapport de performance journalière."""
    db = get_db()
    try:
        db[DAILY_PERF].replace_one(
            {"date": perf["date"]},
            perf,
            upsert=True,
        )
    except Exception as e:
        logger.error("Erreur sauvegarde daily perf: %s", e)


def get_performance_summary(days: int = 7) -> Dict:
    """Résumé de performance sur N jours."""
    db = get_db()
    since = datetime.now(timezone.utc) - timedelta(days=days)

    pipeline = [
        {
            "$match": {
                "close_timestamp": {"$gte": since},
                "status": {"$in": ["WIN", "LOSS"]},
            }
        },
        {
            "$group": {
                "_id": None,
                "total_trades": {"$sum": 1},
                "wins": {"$sum": {"$cond": [{"$eq": ["$status", "WIN"]}, 1, 0]}},
                "total_pnl": {"$sum": "$pnl_eur"},
                "gross_profit": {
                    "$sum": {"$cond": [{"$gt": ["$pnl_eur", 0]}, "$pnl_eur", 0]}
                },
                "gross_loss": {
                    "$sum": {"$cond": [{"$lt": ["$pnl_eur", 0]}, "$pnl_eur", 0]}
                },
                "best_trade": {"$max": "$pnl_eur"},
                "worst_trade": {"$min": "$pnl_eur"},
                "avg_duration": {"$avg": "$duration_sec"},
            }
        },
    ]

    results = list(db[TRADES].aggregate(pipeline))

    if not results:
        return {
            "period_days": days,
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "total_pnl_eur": 0.0,
        }

    r = results[0]
    r.pop("_id", None)
    total = r["total_trades"]

    return {
        "period_days": days,
        "total_trades": total,
        "wins": r["wins"],
        "losses": total - r["wins"],
        "win_rate_pct": round((r["wins"] / total * 100) if total > 0 else 0, 1),
        "total_pnl_eur": round(r["total_pnl"], 2),
        "gross_profit_eur": round(r["gross_profit"], 2),
        "gross_loss_eur": round(r["gross_loss"], 2),
        "profit_factor": round(
            abs(r["gross_profit"] / r["gross_loss"]) if r["gross_loss"] != 0 else 0, 2
        ),
        "best_trade_eur": round(r.get("best_trade", 0) or 0, 2),
        "worst_trade_eur": round(r.get("worst_trade", 0) or 0, 2),
        "avg_duration_min": round((r.get("avg_duration", 0) or 0) / 60, 1),
    }


def get_pnl_by_exit_reason(days: int = 30) -> List[Dict]:
    """PnL par raison de sortie."""
    db = get_db()
    since = datetime.now(timezone.utc) - timedelta(days=days)

    pipeline = [
        {
            "$match": {
                "close_timestamp": {"$gte": since},
                "status": {"$in": ["WIN", "LOSS"]},
            }
        },
        {
            "$group": {
                "_id": "$exit_reason",
                "count": {"$sum": 1},
                "total_pnl": {"$sum": "$pnl_eur"},
                "wins": {"$sum": {"$cond": [{"$eq": ["$status", "WIN"]}, 1, 0]}},
            }
        },
        {"$sort": {"total_pnl": -1}},
    ]

    return [
        {
            "exit_reason": r["_id"],
            "count": r["count"],
            "total_pnl_eur": round(r["total_pnl"], 2),
            "win_rate_pct": round((r["wins"] / r["count"] * 100) if r["count"] > 0 else 0, 1),
        }
        for r in db[TRADES].aggregate(pipeline)
    ]
