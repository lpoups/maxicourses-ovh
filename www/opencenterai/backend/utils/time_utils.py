"""
OpenCenterAI — Time Utilities
===============================
Fonctions utilitaires pour le temps, les fuseaux horaires,
et les horaires de marché.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional

PARIS_TZ = ZoneInfo("Europe/Paris")
UTC_TZ = ZoneInfo("UTC")


def now_paris() -> datetime:
    """Retourne l'heure actuelle en timezone Paris."""
    return datetime.now(PARIS_TZ)


def now_utc() -> datetime:
    """Retourne l'heure actuelle en UTC."""
    return datetime.now(UTC_TZ)


def to_paris(dt: datetime) -> datetime:
    """Convertit un datetime en timezone Paris."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(PARIS_TZ)


def is_night_block(hour_paris: Optional[int] = None) -> bool:
    """
    Vérifie si on est en période de blocage nocturne (00h-06h Paris).
    Les marchés crypto sont ouverts 24/7 sur IG mais la volatilité
    est trop faible la nuit pour le trading algorithmique.
    """
    if hour_paris is None:
        hour_paris = now_paris().hour
    return 0 <= hour_paris < 6


def is_ig_weekly_close(buffer_min: int = 15) -> bool:
    """
    Vérifie si on approche de la fermeture hebdomadaire d'IG.
    IG ferme les marchés crypto le vendredi soir et rouvre le dimanche.
    Fermeture : Vendredi 23h00 Paris (avec buffer).
    Réouverture : Dimanche 23h00 Paris.
    """
    now = now_paris()
    weekday = now.weekday()  # 0=Lundi, 4=Vendredi, 5=Samedi, 6=Dimanche

    # Samedi = fermé
    if weekday == 5:
        return True

    # Vendredi soir (avec buffer)
    if weekday == 4:
        close_time = now.replace(hour=23, minute=0, second=0) - timedelta(minutes=buffer_min)
        if now >= close_time:
            return True

    # Dimanche avant réouverture (23h)
    if weekday == 6:
        reopen_time = now.replace(hour=23, minute=0, second=0)
        if now < reopen_time:
            return True

    return False


def is_market_open(block_hours_enabled: bool = False, block_hours: list = None) -> bool:
    """
    Vérifie si le marché est disponible pour le trading.
    Combine : nuit block + fermeture hebdo + heures bloquées manuelles.
    """
    if is_ig_weekly_close():
        return False

    if is_night_block():
        return False

    if block_hours_enabled and block_hours:
        hour = now_paris().hour
        if hour in block_hours:
            return False

    return True


def seconds_since(dt: datetime) -> float:
    """Nombre de secondes depuis un datetime donné."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return (now_utc() - dt).total_seconds()


def format_duration(seconds: float) -> str:
    """Formate une durée en format lisible."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}min"
    else:
        return f"{seconds/3600:.1f}h"


def get_session_name() -> str:
    """Retourne le nom de la session de marché courante."""
    hour = now_paris().hour
    if 0 <= hour < 6:
        return "NIGHT"
    elif 6 <= hour < 8:
        return "ASIA_LATE"
    elif 8 <= hour < 12:
        return "EU_MORNING"
    elif 12 <= hour < 14:
        return "EU_LUNCH"
    elif 14 <= hour < 18:
        return "US_OVERLAP"
    elif 18 <= hour < 22:
        return "US_AFTERNOON"
    else:
        return "LATE_SESSION"
