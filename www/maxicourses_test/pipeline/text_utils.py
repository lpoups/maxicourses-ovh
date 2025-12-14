"""Shared text normalization helpers for pipeline adapters."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

PACK_TOKEN = r"(?:pack|lot)"
MULTI_PAT = r"(?:\b\d{1,2}\s*(?:x|×|\*)\s*\d+(?:[.,]\d+)?\s*(?:ml|cl|dl|l|g|kg|u|pc|pcs)\b)"
PACK_RE = re.compile(rf"\b{PACK_TOKEN}\b", re.IGNORECASE)
MULTI_RE = re.compile(MULTI_PAT, re.IGNORECASE)


def strip_accents(value: str) -> str:
    """Normalize accents away for robust matching."""
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value or "")
        if unicodedata.category(char) != "Mn"
    )

def normalize_text(text: Optional[str]) -> str:
    """Lowercase, strip accents, and collapse spaces."""
    if not text:
        return ""
    norm = strip_accents(text).lower()
    return re.sub(r"\s+", " ", norm).strip()


def is_pack_or_bundle(title: Optional[str], raw_text: Optional[str]) -> bool:
    """Detect packs/lots while avoiding false positives on plain 'x' characters."""
    haystack = strip_accents(f"{title or ''} {raw_text or ''}").lower()
    return bool(PACK_RE.search(haystack) or MULTI_RE.search(haystack))


def norm_brand(value: Optional[str]) -> str:
    """Collapse whitespace and trim for brand strings."""
    return re.sub(r"\s+", " ", (value or "").strip())


def parse_qty(value: Optional[str]) -> Tuple[str, str, bool]:
    """Return (unit_norm, total_norm, is_pack) for a quantity string."""
    if not value:
        return "", "", False
    text = strip_accents(value.lower())
    text = re.sub(r"\s+", " ", text.replace(",", ".")).strip()

    match_pack = re.search(
        r"\b(\d{1,2})\s*(?:x|×|\*)\s*(\d+(?:\.\d+)?)\s*(ml|cl|dl|l|g|kg|u|pc|pcs)\b",
        text,
        re.IGNORECASE,
    )
    if match_pack:
        count = int(match_pack.group(1))
        qty_raw = float(match_pack.group(2))
        unit_raw = match_pack.group(3).lower()
        unit_single, qty_single = _to_base(qty_raw, unit_raw)
        unit_total, qty_total = unit_single, qty_single * count
        return f"{_fmt(qty_single)} {unit_single}", f"{_fmt(qty_total)} {unit_total}", True

    match_single = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(ml|cl|dl|l|g|kg|u|pc|pcs)\b",
        text,
        re.IGNORECASE,
    )
    if match_single:
        qty_raw = float(match_single.group(1))
        unit_raw = match_single.group(2).lower()
        unit_single, qty_single = _to_base(qty_raw, unit_raw)
        return f"{_fmt(qty_single)} {unit_single}", f"{_fmt(qty_single)} {unit_single}", False

    return text, "", False


def norm_qty(value: Optional[str]) -> str:
    """Preserve the original quantity wording (no unit conversion)."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)


def _to_base(qty: float, unit: str) -> Tuple[str, float]:
    if unit == "ml":
        return "l", qty / 1000.0
    if unit == "cl":
        return "l", qty / 100.0
    if unit == "dl":
        return "l", qty / 10.0
    if unit == "l":
        return "l", qty
    if unit == "g":
        return "kg", qty / 1000.0
    if unit == "kg":
        return "kg", qty
    if unit in {"u", "pc", "pcs"}:
        return "u", qty
    return unit, qty


def _fmt(value: float) -> str:
    formatted = f"{value:.3f}".rstrip("0").rstrip(".")
    return formatted or "0"
