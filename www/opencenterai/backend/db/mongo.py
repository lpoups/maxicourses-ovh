"""
OpenCenterAI — MongoDB Connection Singleton
=============================================
Connexion unique à MongoDB, partagée par tous les repos.
"""

import logging
from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database

logger = logging.getLogger(__name__)

_client: Optional[MongoClient] = None
_db: Optional[Database] = None


def init_mongo(uri: str = "mongodb://127.0.0.1:27017", db_name: str = "opencenterai") -> Database:
    """Initialise la connexion MongoDB. Appelé une seule fois au démarrage."""
    global _client, _db

    if _db is not None:
        return _db

    logger.info("Connexion MongoDB → %s / %s", uri, db_name)
    _client = MongoClient(
        uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=30000,
        maxPoolSize=10,
        retryWrites=True,
    )

    # Test connexion
    _client.admin.command("ping")
    logger.info("MongoDB connecté OK")

    _db = _client[db_name]

    # Créer les index
    _ensure_indexes(_db)

    return _db


def get_db() -> Database:
    """Retourne l'instance DB. Lève une erreur si non initialisée."""
    if _db is None:
        raise RuntimeError("MongoDB non initialisé. Appeler init_mongo() d'abord.")
    return _db


def close_mongo():
    """Ferme proprement la connexion."""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB déconnecté")


def _ensure_indexes(db: Database):
    """Crée tous les index nécessaires."""
    from db.collections import INDEXES

    for collection_name, indexes in INDEXES.items():
        coll = db[collection_name]
        for index_spec in indexes:
            try:
                coll.create_index(**index_spec)
            except Exception as e:
                logger.warning("Index %s.%s : %s", collection_name, index_spec, e)

    logger.info("Index MongoDB vérifiés")
