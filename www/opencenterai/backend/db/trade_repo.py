"""
OpenCenterAI — Trade Repository (MongoDB)
===========================================
Remplace trade_history.json. CRUD complet pour les trades.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db.mongo import get_db
from db.collections import TRADES

logger = logging.getLogger(__name__)


def log_trade_open(
    trade_id: str,
    deal_id: str,
    direction: str,
    size: float,
    entry_price: float,
    sl_price: Optional[float] = None,
    tp_price: Optional[float] = None,
    sl_pts: Optional[float] = None,
    tp_pts: Optional[float] = None,
    rr_ratio: Optional[float] = None,
    ai_entry: Optional[Dict] = None,
    market_at_entry: Optional[Dict] = None,
) -> bool:
    """Enregistre l'ouverture d'un trade."""
    db = get_db()
    now = datetime.now(timezone.utc)

    doc = {
        "trade_id": trade_id,
        "deal_id": deal_id,
        "direction": direction,
        "size": size,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "sl_pts": sl_pts,
        "tp_pts": tp_pts,
        "rr_ratio": rr_ratio,
        "open_timestamp": now,
        "close_timestamp": None,
        "exit_price": None,
        "pnl_eur": None,
        "status": "OPEN",
        "exit_reason": None,
        "duration_sec": None,
        "ai_entry": ai_entry or {},
        "exit_context": {
            "peak_pnl": 0.0,
            "trough_pnl": 0.0,
            "trailing_activated": False,
            "ai_exits_count": 0,
            "partial_closes": [],
        },
        "market_at_entry": market_at_entry or {},
        "created_at": now,
    }

    try:
        db[TRADES].insert_one(doc)
        logger.info(
            "Trade OPEN logged: %s %s %.2f ETH @ %.2f",
            trade_id, direction, size, entry_price,
        )
        return True
    except Exception as e:
        logger.error("Erreur log trade open: %s", e)
        return False


def log_trade_close(
    trade_id: str,
    exit_price: float,
    pnl_eur: float,
    exit_reason: str,
    exit_context: Optional[Dict] = None,
) -> bool:
    """Enregistre la fermeture d'un trade."""
    db = get_db()
    now = datetime.now(timezone.utc)

    # Récupérer le trade pour calculer la durée
    trade = db[TRADES].find_one({"trade_id": trade_id})
    duration_sec = None
    if trade and trade.get("open_timestamp"):
        duration_sec = (now - trade["open_timestamp"]).total_seconds()

    status = "WIN" if pnl_eur > 0 else "LOSS"

    update = {
        "$set": {
            "close_timestamp": now,
            "exit_price": exit_price,
            "pnl_eur": round(pnl_eur, 2),
            "status": status,
            "exit_reason": exit_reason,
            "duration_sec": round(duration_sec, 1) if duration_sec else None,
        }
    }

    if exit_context:
        update["$set"]["exit_context"] = exit_context

    try:
        result = db[TRADES].update_one({"trade_id": trade_id}, update)
        if result.modified_count == 0:
            logger.warning("Trade %s non trouvé pour close", trade_id)
            return False

        logger.info(
            "Trade CLOSE logged: %s %s PnL=%.2f€ reason=%s",
            trade_id, status, pnl_eur, exit_reason,
        )
        return True
    except Exception as e:
        logger.error("Erreur log trade close: %s", e)
        return False


def update_trade_context(trade_id: str, updates: Dict[str, Any]) -> bool:
    """Met à jour le contexte d'un trade ouvert (peak_pnl, trailing, etc.)."""
    db = get_db()
    try:
        set_fields = {f"exit_context.{k}": v for k, v in updates.items()}
        db[TRADES].update_one({"trade_id": trade_id}, {"$set": set_fields})
        return True
    except Exception as e:
        logger.error("Erreur update trade context: %s", e)
        return False


def get_open_trades() -> List[Dict]:
    """Retourne tous les trades ouverts."""
    db = get_db()
    return list(db[TRADES].find({"status": "OPEN"}).sort("open_timestamp", -1))


def get_trade_history(
    limit: int = 50,
    skip: int = 0,
    status: Optional[str] = None,
    direction: Optional[str] = None,
) -> List[Dict]:
    """Retourne l'historique des trades avec filtres optionnels."""
    db = get_db()
    query: Dict[str, Any] = {}

    if status:
        query["status"] = status
    if direction:
        query["direction"] = direction

    cursor = (
        db[TRADES]
        .find(query)
        .sort("open_timestamp", -1)
        .skip(skip)
        .limit(limit)
    )
    return list(cursor)


def get_trade_by_id(trade_id: str) -> Optional[Dict]:
    """Récupère un trade par son ID."""
    db = get_db()
    return db[TRADES].find_one({"trade_id": trade_id})


def get_daily_stats(date_str: str) -> Dict:
    """Calcule les stats pour une journée donnée."""
    db = get_db()
    from datetime import datetime

    day_start = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
    day_end = datetime.fromisoformat(f"{date_str}T23:59:59+00:00")

    pipeline = [
        {
            "$match": {
                "close_timestamp": {"$gte": day_start, "$lte": day_end},
                "status": {"$in": ["WIN", "LOSS"]},
            }
        },
        {
            "$group": {
                "_id": None,
                "total_trades": {"$sum": 1},
                "wins": {"$sum": {"$cond": [{"$eq": ["$status", "WIN"]}, 1, 0]}},
                "total_pnl": {"$sum": "$pnl_eur"},
                "avg_pnl": {"$avg": "$pnl_eur"},
                "max_pnl": {"$max": "$pnl_eur"},
                "min_pnl": {"$min": "$pnl_eur"},
            }
        },
    ]

    results = list(db[TRADES].aggregate(pipeline))
    if not results:
        return {"total_trades": 0, "wins": 0, "win_rate": 0.0, "total_pnl": 0.0}

    stats = results[0]
    stats.pop("_id", None)
    stats["win_rate"] = round(
        (stats["wins"] / stats["total_trades"] * 100) if stats["total_trades"] > 0 else 0, 1
    )
    return stats


def count_trades(status: Optional[str] = None) -> int:
    """Compte le nombre de trades."""
    db = get_db()
    query = {"status": status} if status else {}
    return db[TRADES].count_documents(query)
