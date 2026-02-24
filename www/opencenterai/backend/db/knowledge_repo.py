"""
OpenCenterAI — Knowledge Base Repository (MongoDB)
====================================================
Remplace knowledge_base.json. Persistance des patterns
d'apprentissage et statistiques agrégées.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db.mongo import get_db
from db.collections import KNOWLEDGE

logger = logging.getLogger(__name__)


def get_aggregates() -> Optional[Dict]:
    """Récupère les agrégats globaux."""
    db = get_db()
    doc = db[KNOWLEDGE].find_one({"type": "aggregates"})
    if doc:
        doc.pop("_id", None)
    return doc


def save_aggregates(aggregates: Dict) -> bool:
    """Sauvegarde les agrégats globaux."""
    db = get_db()
    now = datetime.now(timezone.utc)

    doc = {
        "type": "aggregates",
        **aggregates,
        "last_updated": now,
    }

    try:
        db[KNOWLEDGE].replace_one(
            {"type": "aggregates"},
            doc,
            upsert=True,
        )
        logger.info("Agrégats knowledge base sauvegardés")
        return True
    except Exception as e:
        logger.error("Erreur sauvegarde agrégats: %s", e)
        return False


def get_patterns() -> List[Dict]:
    """Récupère les patterns détectés."""
    db = get_db()
    cursor = db[KNOWLEDGE].find({"type": "pattern"}).sort("score", -1)
    results = []
    for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


def save_pattern(pattern: Dict) -> bool:
    """Sauvegarde un pattern."""
    db = get_db()
    now = datetime.now(timezone.utc)

    doc = {
        "type": "pattern",
        **pattern,
        "created_at": now,
    }

    try:
        db[KNOWLEDGE].insert_one(doc)
        return True
    except Exception as e:
        logger.error("Erreur sauvegarde pattern: %s", e)
        return False


def get_insights() -> List[Dict]:
    """Récupère les insights (top leçons apprises)."""
    db = get_db()
    cursor = db[KNOWLEDGE].find({"type": "insight"}).sort("priority", -1).limit(10)
    results = []
    for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


def save_insight(insight: Dict) -> bool:
    """Sauvegarde un insight."""
    db = get_db()
    now = datetime.now(timezone.utc)

    doc = {
        "type": "insight",
        **insight,
        "created_at": now,
    }

    try:
        db[KNOWLEDGE].insert_one(doc)
        return True
    except Exception as e:
        logger.error("Erreur sauvegarde insight: %s", e)
        return False


def get_hourly_stats() -> Dict[str, Dict]:
    """Récupère les stats par heure."""
    aggregates = get_aggregates()
    if aggregates:
        return aggregates.get("by_hour", {})
    return {}


def get_regime_stats() -> Dict[str, Dict]:
    """Récupère les stats par régime de marché."""
    aggregates = get_aggregates()
    if aggregates:
        return aggregates.get("by_regime", {})
    return {}


def get_avoid_hours() -> List[int]:
    """Retourne les heures à éviter (WR < seuil)."""
    aggregates = get_aggregates()
    if aggregates:
        return aggregates.get("avoid_hours", [])
    return []


def get_best_hours() -> List[int]:
    """Retourne les meilleures heures de trading."""
    aggregates = get_aggregates()
    if aggregates:
        return aggregates.get("best_hours", [])
    return []
