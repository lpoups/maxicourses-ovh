"""
OpenCenterAI — Config Repository (MongoDB)
============================================
Remplace state.json + auto_config.json.
Source unique de vérité pour les paramètres de trading.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from db.mongo import get_db
from db.collections import CONFIG, CONFIG_HISTORY
from config.settings import TradingParams

logger = logging.getLogger(__name__)

CONFIG_KEY = "trading_params"


def load_trading_params() -> TradingParams:
    """
    Charge les TradingParams depuis MongoDB.
    Si aucun document n'existe, crée les défauts et les persiste.
    """
    db = get_db()
    doc = db[CONFIG].find_one({"key": CONFIG_KEY})

    if doc is None:
        logger.info("Aucune config MongoDB trouvée → création des défauts")
        params = TradingParams()
        save_trading_params(params, source="init_defaults")
        return params

    # Retirer les champs MongoDB internes
    doc.pop("_id", None)
    doc.pop("key", None)
    doc.pop("updated_at", None)
    doc.pop("updated_by", None)

    try:
        params = TradingParams.from_dict(doc)
        logger.info("Config chargée depuis MongoDB (mode=%s, enabled=%s)", params.mode, params.enabled)
        return params
    except Exception as e:
        logger.error("Erreur chargement config MongoDB: %s → utilisation défauts", e)
        return TradingParams()


def save_trading_params(params: TradingParams, source: str = "system") -> bool:
    """
    Sauvegarde les TradingParams dans MongoDB.
    Crée également une entrée dans config_history.
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    doc = params.to_dict()
    doc["key"] = CONFIG_KEY
    doc["updated_at"] = now
    doc["updated_by"] = source

    try:
        db[CONFIG].replace_one(
            {"key": CONFIG_KEY},
            doc,
            upsert=True,
        )

        # Historique des changements
        history_doc = {
            "key": CONFIG_KEY,
            "params": params.to_dict(),
            "timestamp": now,
            "created_at": now,
            "source": source,
        }
        db[CONFIG_HISTORY].insert_one(history_doc)

        logger.info("Config sauvegardée → MongoDB (source=%s)", source)
        return True

    except Exception as e:
        logger.error("Erreur sauvegarde config: %s", e)
        return False


def update_runtime_fields(updates: dict, source: str = "dashboard") -> Optional[TradingParams]:
    """
    Met à jour UNIQUEMENT les champs runtime autorisés.
    Refuse les modifications des champs en lecture seule.
    """
    allowed = TradingParams.RUNTIME_FIELDS
    filtered = {k: v for k, v in updates.items() if k in allowed}

    if not filtered:
        logger.warning("Aucun champ runtime valide dans: %s", list(updates.keys()))
        return None

    rejected = set(updates.keys()) - allowed
    if rejected:
        logger.warning("Champs refusés (lecture seule): %s", rejected)

    # Charger, modifier, sauvegarder
    params = load_trading_params()
    for k, v in filtered.items():
        setattr(params, k, v)

    save_trading_params(params, source=source)
    return params
