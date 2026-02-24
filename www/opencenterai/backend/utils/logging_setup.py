"""
OpenCenterAI — Logging Setup
==============================
Configuration centralisée du logging structuré.
"""

import logging
import os
import sys
from datetime import datetime


def setup_logging(level: str = "INFO", log_file: str = "logs/trading.log"):
    """Configure le logging pour toute l'application."""

    # Créer le répertoire de logs si nécessaire
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Format
    fmt = "%(asctime)s | %(levelname)-7s | %(name)-25s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    # Root logger
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
    root.addHandler(console)

    # File handler (avec rotation quotidienne)
    try:
        from logging.handlers import TimedRotatingFileHandler

        file_handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
        root.addHandler(file_handler)
    except Exception as e:
        logging.warning("Impossible de créer le file handler: %s", e)

    # Réduire le bruit des bibliothèques tierces
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logging.info("Logging configuré: level=%s, file=%s", level, log_file)
