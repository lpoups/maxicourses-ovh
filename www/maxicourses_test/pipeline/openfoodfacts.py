"""Lightweight OpenFoodFacts client with local caching."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT_DIR / "state" / "openfoodfacts_cache.json"
CACHE_TTL = timedelta(days=2)
REQUEST_TIMEOUT = float(os.environ.get("OPENFOODFACTS_TIMEOUT", "15"))
BASE_URL = os.environ.get("OPENFOODFACTS_BASE_URL", "https://fr.openfoodfacts.org")


def _normalize_ean(ean: Any) -> str:
    return "".join(ch for ch in str(ean) if ch.isdigit())


def _load_cache() -> Dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cache_entry_fresh(entry: Dict[str, Any]) -> bool:
    fetched_at = entry.get("fetched_at")
    if not isinstance(fetched_at, str):
        return False
    try:
        timestamp = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - timestamp < CACHE_TTL


def _fetch_remote(ean: str) -> Optional[Dict[str, Any]]:
    url = f"{BASE_URL.rstrip('/')}/api/v3/product/{ean}.json"
    headers = {
        "User-Agent": "MaxiCourses/1.0 (+https://www.maxicourses.fr)",
        "Accept": "application/json",
    }
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None
    status = payload.get("status")
    if status not in (None, 1, "success", "ok"):
        return None
    product = payload.get("product")
    if not isinstance(product, dict):
        return None
    return _extract_fields(product)


def _extract_fields(product: Dict[str, Any]) -> Dict[str, Any]:
    def clean_grade(value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return None
        cleaned = value.strip().lower()
        return cleaned or None

    def clean_nova(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return str(int(value))
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return text
        return None

    nutri_grade = (
        clean_grade(product.get("nutriscore_grade"))
        or clean_grade(product.get("nutrition_grades"))
    )
    ecoscore_grade = clean_grade(product.get("ecoscore_grade"))
    nova_group = clean_nova(product.get("nova_group")) or clean_nova(
        (product.get("nova_groups_tags") or [None])[0]
        if isinstance(product.get("nova_groups_tags"), list)
        else None
    )
    nutri_score = product.get("nutriscore_score") or product.get("nutrition_score_fr")

    return {
        "nutriscore_grade": nutri_grade,
        "nutriscore_score": nutri_score,
        "ecoscore_grade": ecoscore_grade,
        "nova_group": nova_group,
        "source_url": product.get("url"),
    }


def lookup_product(ean: Any) -> Optional[Dict[str, Any]]:
    """Return OFF nutrition info for the given EAN (cached)."""
    normalized = _normalize_ean(ean)
    if not normalized:
        return None
    cache = _load_cache()
    entry = cache.get(normalized)
    if isinstance(entry, dict) and _cache_entry_fresh(entry):
        return entry.get("data")

    try:
        data = _fetch_remote(normalized)
    except requests.RequestException:
        data = None
    if data:
        cache[normalized] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        _save_cache(cache)
    return data
