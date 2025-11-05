# descriptor_store.py
# Source de vérité des descriptifs produits à partir de seed_catalog (code) et
# d’un simple registre texte pour le flag `removed`.
from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Set

from seed_catalog import all_seeds, get_seed

STATE_PATH = Path(__file__).resolve().parent / "state" / "descriptor_removed.txt"
_REMOVED_CACHE: Optional[Set[str]] = None
_LOCK = threading.Lock()


def _normalize_ean(ean: Any) -> str:
    value = "".join(ch for ch in str(ean) if ch.isdigit())
    return value.strip()


def _load_removed_set() -> Set[str]:
    global _REMOVED_CACHE
    if _REMOVED_CACHE is not None:
        return set(_REMOVED_CACHE)
    items: Set[str] = set()
    if STATE_PATH.exists():
        try:
            content = STATE_PATH.read_text(encoding="utf-8")
        except Exception:
            content = ""
        for line in content.splitlines():
            entry = line.strip()
            if entry:
                items.add(entry)
    _REMOVED_CACHE = set(items)
    return set(items)


def _write_removed_set(items: Set[str]) -> None:
    global _REMOVED_CACHE
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    sorted_items = sorted(items)
    text = "\n".join(sorted_items)
    if text:
        text += "\n"
    STATE_PATH.write_text(text, encoding="utf-8")
    _REMOVED_CACHE = set(items)


def descriptor_exists(ean: Any) -> bool:
    key = _normalize_ean(ean)
    return bool(key and get_seed(key))


def get_descriptor(ean: Any) -> Dict[str, Any]:
    key = _normalize_ean(ean)
    base = get_seed(key)
    descriptor: Dict[str, Any] = copy.deepcopy(base) if isinstance(base, dict) else {}
    descriptor.setdefault("ean", key)
    descriptor.setdefault("source", descriptor.get("source") or ("seed" if base else "unknown"))
    descriptor.setdefault("note", descriptor.get("note") or "")
    descriptor.setdefault("removed", False)
    descriptor["removed"] = key in _load_removed_set()
    return descriptor


def set_removed_flag(ean: Any, removed: bool) -> Dict[str, Any]:
    key = _normalize_ean(ean)
    if not key:
        return {"ean": "", "removed": removed, "source": "unknown"}
    with _LOCK:
        current = _load_removed_set()
        if removed:
            current.add(key)
        else:
            current.discard(key)
        _write_removed_set(current)
    descriptor = get_descriptor(key)
    descriptor["removed"] = removed
    return descriptor


def all_descriptors() -> Dict[str, Dict[str, Any]]:
    seeds = all_seeds()
    removed = _load_removed_set()
    descriptors: Dict[str, Dict[str, Any]] = {}
    for ean, payload in seeds.items():
        entry = copy.deepcopy(payload)
        entry.setdefault("ean", ean)
        entry["removed"] = ean in removed
        descriptors[ean] = entry
    return descriptors


def removed_eans() -> Set[str]:
    """Expose l’ensemble des EAN marqués comme retirés."""
    return _load_removed_set()
