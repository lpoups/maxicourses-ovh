#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
import html
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

try:
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover - optional dependency when --image n/a
    Image = None  # type: ignore

try:
    import zxingcpp  # type: ignore
except ImportError:  # pragma: no cover - optional dependency when --image n/a
    zxingcpp = None  # type: ignore

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "pipeline" / "assets"

SIZE_TOKEN_SUFFIXES = ("ml", "cl", "dl", "l", "g", "kg")


def _looks_like_size_token(raw: str) -> bool:
    if not raw:
        return False
    token = raw.strip().lower().replace(" ", "")
    if not token:
        return False
    token = token.replace(",", "").replace(".", "")
    if token.isdigit():
        return True
    for suffix in SIZE_TOKEN_SUFFIXES:
        if token.endswith(suffix):
            prefix = token[: -len(suffix)]
            if prefix and prefix.isdigit():
                return True
    return False


GENERIC_BRAND_TERMS = {
    "yaourt",
    "yaourts",
    "dessert",
    "desserts",
    "boisson",
    "boissons",
    "proteine",
    "protéine",
    "protéiné",
    "proteiné",
    "protein",
    "original",
    "gel",
    "savon",
    "creme",
    "crème",
    "lait",
    "jus",
    "produit",
    "produits",
    "shampooing",
    "huile",
    "gout",
    "goût",
    "lessive",
    "lessives",
}

STOPWORDS = {
    "a",
    "au",
    "aux",
    "avec",
    "base",
    "de",
    "des",
    "du",
    "et",
    "la",
    "le",
    "les",
    "pour",
    "sur",
    "dans",
    "par",
    "l",
    "d",
}

SEED_MAX_LENGTH = 60
LECLERC_MAX_LENGTH = 40
LECLERC_MAX_TOKENS = 5
EAN_REQUIRED_LENGTH = 13


def _normalize_seed_token(token: str) -> str:
    token = token.strip()
    if not token:
        return ""
    normalized = unicodedata.normalize("NFKD", token.lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch) and not ch.isspace())


def _tokenize_phrase(value: str) -> List[str]:
    if not isinstance(value, str):
        return []
    parts = re.split(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ']+", value)
    return [part.strip() for part in parts if part.strip()]


def build_seed_query_from_descriptor(descriptor: Dict[str, Any]) -> str:
    brand = (descriptor.get("brand") or "").strip()
    name = (descriptor.get("name") or descriptor.get("description") or "").strip()
    quantity = (descriptor.get("quantity") or "").strip()

    tokens: List[str] = []
    seen: set[str] = set()

    def add_token(token: str) -> None:
        token = token.strip().strip(",.;:()[]{}'\"/+-%")
        normalized = _normalize_seed_token(token)
        if not normalized:
            return
        if normalized in STOPWORDS:
            return
        if normalized in seen:
            return
        seen.add(normalized)
        tokens.append(token.strip())

    if brand:
        add_token(brand)

    def extract_tokens(source: Optional[str]) -> None:
        if not isinstance(source, str):
            return
        for token in _tokenize_phrase(source):
            normalized = _normalize_seed_token(token)
            if not normalized or normalized in STOPWORDS:
                continue
            if _looks_like_size_token(token):
                continue
            if token.isdigit() and quantity and token in quantity:
                continue
            if token.lower() == brand.lower():
                continue
            add_token(token)

    extract_tokens(name)
    extract_tokens(descriptor.get("description"))

    if quantity:
        has_alpha_qty = any(ch.isalpha() for ch in quantity)
        for token in _tokenize_phrase(quantity):
            normalized = _normalize_seed_token(token)
            if normalized in STOPWORDS:
                continue
            if normalized in {"g", "kg", "l", "ml", "cl", "gr", "grammes", "litre", "litres"}:
                continue
            if has_alpha_qty and token.isdigit():
                continue
            add_token(token)
        cleaned_quantity = re.sub(r"\s+", " ", quantity).strip()
        if cleaned_quantity and has_alpha_qty:
            normalized_quantity = _normalize_seed_token(cleaned_quantity)
            if normalized_quantity not in seen:
                trial = " ".join(tokens + [cleaned_quantity])
                if len(trial) <= SEED_MAX_LENGTH:
                    seen.add(normalized_quantity)
                    tokens.append(cleaned_quantity)

    if not tokens:
        return (descriptor.get("ean") or "").strip()

    seed = " ".join(tokens)
    if len(seed) > SEED_MAX_LENGTH:
        trimmed: List[str] = []
        for token in tokens:
            trial = " ".join(trimmed + [token]) if trimmed else token
            if len(trial) <= SEED_MAX_LENGTH or not trimmed:
                trimmed.append(token)
            else:
                break
        seed = " ".join(trimmed)

    return seed


_UNIT_TOKENS = {"ml", "l", "cl", "g", "kg"}


def _normalize_quantity_token(quantity: Optional[str]) -> Optional[str]:
    if not isinstance(quantity, str):
        return None
    cleaned = quantity.strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace(",", ".")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    upper_cleaned = cleaned.upper()
    match = re.match(r"(\d+(?:\.\d+)?)(?:\s*[xX]\s*\d+)?\s*(ML|L|CL|KG|G)\b", upper_cleaned)
    if match:
        number = match.group(1).rstrip(".")
        unit = match.group(2)
        return f"{number} {unit}"
    return upper_cleaned


def _resolve_brand_token(descriptor: Dict[str, Any]) -> Optional[str]:
    candidate = normalize_brand_candidate(descriptor.get("brand"))
    if candidate and not is_generic_brand(candidate):
        return candidate
    for key in ("seed_primary_name", "name", "description", "seed_query"):
        value = descriptor.get(key)
        if not value:
            continue
        candidate = infer_brand_from_title(value)
        if candidate and not is_generic_brand(candidate):
            return candidate
    return None


def _extract_product_tokens_for_leclerc(
    descriptor: Dict[str, Any],
    brand_token: Optional[str],
) -> List[str]:
    sources = [
        descriptor.get("seed_primary_name"),
        descriptor.get("name"),
        descriptor.get("description"),
        descriptor.get("seed_query"),
    ]
    tokens: List[str] = []
    seen: set[str] = set()
    brand_norm = _normalize_seed_token(brand_token) if brand_token else None
    for source in sources:
        if not isinstance(source, str):
            continue
        for raw in re.split(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]+", source):
            token = raw.strip()
            if not token:
                continue
            normalized = _normalize_seed_token(token)
            if not normalized or normalized in STOPWORDS:
                continue
            if _looks_like_size_token(token):
                continue
            if brand_norm and normalized == brand_norm:
                continue
            if normalized in _UNIT_TOKENS:
                continue
            if re.fullmatch(r"\d+", normalized):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            tokens.append(token)
    return tokens


def _compose_query_from_tokens(tokens: List[str], max_length: int = LECLERC_MAX_LENGTH) -> Optional[str]:
    prepared = [tok for tok in tokens if isinstance(tok, str) and tok.strip()]
    if not prepared:
        return None
    phrase = " ".join(prepared).strip()
    if not phrase:
        return None
    if len(phrase) <= max_length:
        return phrase
    trimmed: List[str] = []
    for token in prepared:
        tentative = " ".join(trimmed + [token]) if trimmed else token
        if len(tentative) > max_length:
            break
        trimmed.append(token)
    phrase = " ".join(trimmed).strip()
    return phrase or None


def _qualify_query(value: Optional[str]) -> bool:
    if not value:
        return False
    words = [word for word in value.split() if word]
    return len(words) >= 3


def _trim_for_store(query: str, max_length: int = 30) -> str:
    if len(query) <= max_length:
        return query
    pieces: List[str] = []
    for token in query.split():
        tentative = " ".join(pieces + [token]) if pieces else token
        if len(tentative) > max_length:
            break
        pieces.append(token)
    return " ".join(pieces) if pieces else query[:max_length].rstrip()


def build_leclerc_search_profile(descriptor: Dict[str, Any]) -> Dict[str, List[str]]:
    brand_token = _resolve_brand_token(descriptor)
    quantity_token = _normalize_quantity_token(
        descriptor.get("seed_primary_quantity") or descriptor.get("quantity")
    )
    product_tokens = _extract_product_tokens_for_leclerc(descriptor, brand_token)
    function_token = product_tokens[0] if product_tokens else None
    variant_token = product_tokens[1] if len(product_tokens) > 1 else None

    queries: List[str] = []
    primary_query: Optional[str] = None

    def add_query(value: Optional[str], *, enforce_words: bool = True) -> Optional[str]:
        if not isinstance(value, str):
            return None
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned:
            return None
        if enforce_words and not _qualify_query(cleaned):
            return None
        if cleaned in queries:
            return cleaned
        queries.append(cleaned)
        return cleaned

    candidate_sequences: List[List[str]] = []
    if brand_token and quantity_token:
        candidate_sequences.append([brand_token, quantity_token])
    if brand_token and function_token and quantity_token:
        candidate_sequences.append([brand_token, function_token, quantity_token])
        if variant_token:
            candidate_sequences.append([brand_token, function_token, variant_token, quantity_token])
    if brand_token and function_token:
        candidate_sequences.append([brand_token, function_token])
    if function_token and quantity_token:
        seq = [function_token]
        if variant_token:
            seq.append(variant_token)
        seq.append(quantity_token)
        candidate_sequences.append(seq)
    if brand_token and variant_token and quantity_token:
        candidate_sequences.append([brand_token, variant_token, quantity_token])

    for sequence in candidate_sequences:
        query = _compose_query_from_tokens(sequence)
        if query:
            added = add_query(query)
            if primary_query is None and added:
                primary_query = added

    # fallback using broader descriptor information
    for source in (
        descriptor.get("seed_query"),
        descriptor.get("seed_primary_name"),
        descriptor.get("name"),
        descriptor.get("description"),
    ):
        if isinstance(source, str):
            add_query(source)

    fallback = descriptor.get("ean")
    if fallback:
        fallback_value = str(fallback).strip()
        if fallback_value:
            add_query(fallback_value, enforce_words=False)

    if not queries:
        fallback_value = str(descriptor.get("ean") or "").strip()
        if fallback_value:
            queries.append(fallback_value)

    # Primary keywords: ensure at least one trimmed query respecting store length
    if primary_query is None:
        primary_query = next((q for q in queries if _qualify_query(q)), queries[0])
    trimmed_primary = _trim_for_store(primary_query)
    primary_keywords = [trimmed_primary] if trimmed_primary else []

    secondary_keywords: List[str] = []
    for token in product_tokens[1:]:
        normalized = _normalize_seed_token(token)
        if not normalized or normalized in STOPWORDS:
            continue
        if token not in secondary_keywords:
            secondary_keywords.append(token)
    if variant_token and variant_token not in secondary_keywords:
        secondary_keywords.append(variant_token)
    if quantity_token and quantity_token not in secondary_keywords:
        secondary_keywords.append(quantity_token)

    return {
        "queries": queries,
        "primary_keywords": primary_keywords,
        "secondary_keywords": secondary_keywords,
    }

if __package__ in (None, ""):
    sys.path.append(str(ROOT_DIR))
    from decode_ean import decode_image_to_ean  # type: ignore
    from pipeline.models import PipelineRun, RawAdapterResult  # type: ignore
else:  # pragma: no cover - executed when package imports are available
    from ..decode_ean import decode_image_to_ean  # type: ignore
    from .models import PipelineRun, RawAdapterResult
DEFAULT_RESULTS_DIR = ROOT_DIR / "results"
MANUAL_DESCRIPTOR_PATH = ROOT_DIR / "manual_descriptors.json"

ADAPTER_SCRIPTS: Dict[str, Dict[str, Any]] = {
    "carrefour_city": {
        "script": ROOT_DIR / "fetch_carrefour_price_city.py",
        "env": lambda: {
            "CARREFOUR_STATE_VARIANT": os.getenv("CARREFOUR_CITY_STATE", "carrefour_city"),
        },
    },
    "carrefour_market": {
        "script": ROOT_DIR / "fetch_carrefour_price_market.py",
        "env": lambda: {
            "CARREFOUR_STATE_VARIANT": os.getenv("CARREFOUR_MARKET_STATE", "carrefour_market"),
        },
    },
    "leclerc": {
        "script": ROOT_DIR / "fetch_leclerc_drive_price.py",
        "env": lambda: {
            "STORE_URL": os.getenv(
                "LECLERC_DRIVE_URL",
                "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx",
            ),
        },
    },
    "intermarche": {
        "script": ROOT_DIR / "fetch_intermarche_price.py",
        "env": lambda: {
            "HOME_URL": os.getenv("INTERMARCHE_HOME_URL", "https://www.intermarche.com/accueil"),
        },
    },
    "auchan": {
        "script": ROOT_DIR / "fetch_auchan_price.py",
        "env": lambda: {
            "HOME_URL": os.getenv("AUCHAN_HOME_URL", "https://www.auchan.fr"),
        },
    },
    "chronodrive": {
        "script": ROOT_DIR / "fetch_chronodrive_price.py",
        "env": lambda: {
            "STORE_URL": os.getenv(
                "CHRONODRIVE_STORE_URL",
                "https://www.chronodrive.com/magasin/le-haillan-422",
            ),
        },
    },
    "monoprix": {
        "script": ROOT_DIR / "fetch_monoprix_price.py",
        "env": lambda: {
            "HOME_URL": os.getenv("MONOPRIX_HOME_URL", "https://courses.monoprix.fr/"),
        },
    },
    "courseu": {
        "script": ROOT_DIR / "fetch_courseu_price.py",
        "env": lambda: {
            "STORE_URL": os.getenv(
                "COURSEU_STORE_URL",
                "https://www.coursesu.com/drive-superu-eysines",
            ),
            "STORE_NAME": os.getenv("COURSEU_STORE_NAME", "Super U Eysines"),
        },
    },
}

EAN_ONLY_ADAPTERS = {
    "carrefour_city",
    "carrefour_market",
    "auchan",
    "chronodrive",
    "courseu",
}

DEFAULT_ADAPTER_ORDER = [
    "carrefour_city",
    "carrefour_market",
    "auchan",
    "chronodrive",
    "courseu",
    "intermarche",
    "leclerc",
    "monoprix",
]


def decode_ean(image_path: Path) -> str:
    if Image is None or zxingcpp is None:
        raise RuntimeError("Lecture d'image indisponible (Pillow/zxingcpp manquants)")
    value = decode_image_to_ean(image_path)
    if not value:
        raise RuntimeError(f"Impossible d'extraire un EAN depuis {image_path}")
    return value


def load_manual_descriptor(ean: str) -> Optional[Dict[str, str]]:
    manual = fetch_manual_descriptor(ean)
    if not manual:
        return None
    descriptor = dict(manual)
    descriptor.setdefault("source", "manual")
    descriptor.setdefault("ean", ean)
    return descriptor


def fetch_manual_descriptor(ean: str) -> Optional[Dict[str, str]]:
    if not MANUAL_DESCRIPTOR_PATH.exists():
        return None
    try:
        data = json.loads(MANUAL_DESCRIPTOR_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    entry = data.get(ean)
    if isinstance(entry, dict):
        return entry
    return None


def load_all_descriptors() -> Dict[str, Dict[str, Any]]:
    if not MANUAL_DESCRIPTOR_PATH.exists():
        return {}
    try:
        data = json.loads(MANUAL_DESCRIPTOR_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data


def save_manual_descriptor_entry(ean: str, entry: Dict[str, Any]) -> None:
    data = load_all_descriptors()
    data[ean] = entry
    try:
        MANUAL_DESCRIPTOR_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def merge_descriptor(base: Optional[Dict[str, Any]], updates: Dict[str, Any]) -> Dict[str, Any]:
    descriptor = dict(base or {})
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if key == "brand":
            existing = descriptor.get("brand")
            if existing and not is_generic_brand(existing) and is_generic_brand(value):
                continue
            if (not existing or is_generic_brand(existing)) and is_generic_brand(value):
                continue
        descriptor[key] = value
    descriptor.setdefault("ean", updates.get("ean"))
    return descriptor


def normalize_brand_candidate(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    cleaned = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ+&'\- ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    if cleaned.isupper():
        cleaned = cleaned.title()
    return cleaned


def is_generic_brand(value: Any) -> bool:
    candidate = normalize_brand_candidate(value)
    if not candidate:
        return True
    lowered = candidate.lower()
    return lowered in GENERIC_BRAND_TERMS


def infer_brand_from_title(title: Any) -> Optional[str]:
    if not isinstance(title, str):
        return None
    tokens = re.split(r"[\s\-·•()\[\]/\\,'\"]+", title)
    # Prefer uppercase distinctive tokens from the end of the string (e.g. HIPRO)
    for token in reversed(tokens):
        if _looks_like_size_token(token):
            continue
        candidate = normalize_brand_candidate(token)
        if not candidate:
            continue
        if candidate.isupper() or token.isupper():
            if not is_generic_brand(candidate):
                return candidate
    for token in tokens:
        if _looks_like_size_token(token):
            continue
        candidate = normalize_brand_candidate(token)
        if not candidate or is_generic_brand(candidate):
            continue
        if token[:1].isupper():
            return candidate
    return None


def infer_brand_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    explicit = normalize_brand_candidate(payload.get("brand"))
    if explicit and not is_generic_brand(explicit):
        return explicit
    for key in ("title", "name", "description"):
        candidate = infer_brand_from_title(payload.get(key))
        if candidate and not is_generic_brand(candidate):
            return candidate
    url = payload.get("url")
    if isinstance(url, str):
        parts = [p for p in re.split(r"[^0-9A-Za-z]+", url) if p]
        for part in reversed(parts):
            candidate = normalize_brand_candidate(part)
            if candidate and not is_generic_brand(candidate):
                return candidate
    return None


def ensure_brand_from_results(
    ean: str,
    descriptor: Optional[Dict[str, Any]],
    adapter_results: List[RawAdapterResult],
) -> Optional[Dict[str, Any]]:
    if not descriptor:
        return descriptor

    current_brand = descriptor.get("brand")
    if current_brand and not is_generic_brand(current_brand):
        desired_query = build_search_query(ean, descriptor)
        if descriptor.get("seed_query") != desired_query:
            updated = dict(descriptor)
            updated["seed_query"] = desired_query
            save_manual_descriptor_entry(ean, updated)
            return updated
        return descriptor

    candidate: Optional[str] = None
    for res in adapter_results:
        if not isinstance(res, RawAdapterResult):
            continue
        payload = res.payload or {}
        candidate = infer_brand_from_payload(payload)
        if candidate and not is_generic_brand(candidate):
            break

    if not candidate:
        candidate = infer_brand_from_title(descriptor.get("name"))
    if not candidate or is_generic_brand(candidate):
        return descriptor

    updated = dict(descriptor)
    updated["brand"] = candidate
    updated["seed_query"] = build_search_query(ean, updated)
    save_manual_descriptor_entry(ean, updated)
    return updated


def ensure_nutriscore_from_results(
    ean: str,
    descriptor: Optional[Dict[str, Any]],
    adapter_results: List[RawAdapterResult],
) -> Optional[Dict[str, Any]]:
    if not descriptor:
        return descriptor

    def local_asset_for(grade: str) -> str:
        return f"../assets/nutriscore/nutriscore-{grade.lower()}.svg"

    current_grade = (descriptor.get("nutriscore_grade") or "").strip().lower()
    if current_grade and current_grade not in {"unknown", "na", "n/a"}:
        if current_grade in {"a", "b", "c", "d", "e"}:
            expected = local_asset_for(current_grade)
            if descriptor.get("nutriscore_image") != expected:
                updated = dict(descriptor)
                updated["nutriscore_image"] = expected
                save_manual_descriptor_entry(ean, updated)
                return updated
        return descriptor

    for res in adapter_results:
        payload = res.payload or {}
        candidate_grade = payload.get("nutriscore_grade")
        if isinstance(candidate_grade, str) and candidate_grade.strip():
            grade_value = candidate_grade.strip().lower()
            updated = dict(descriptor)
            updated["nutriscore_grade"] = grade_value
            if grade_value in {"a", "b", "c", "d", "e"}:
                updated["nutriscore_image"] = local_asset_for(grade_value)
            else:
                image_candidate = payload.get("nutriscore_image")
                if isinstance(image_candidate, str) and image_candidate.strip():
                    updated["nutriscore_image"] = image_candidate.strip()
                else:
                    updated.pop("nutriscore_image", None)
            save_manual_descriptor_entry(ean, updated)
            return updated
    # Fallback for unknown / missing grades
    if not descriptor.get("nutriscore_image") or str(descriptor.get("nutriscore_image")).startswith("http"):
        updated = dict(descriptor)
        updated.setdefault("nutriscore_grade", descriptor.get("nutriscore_grade") or "unknown")
        updated["nutriscore_image"] = local_asset_for("unknown")
        save_manual_descriptor_entry(ean, updated)
        return updated
    return descriptor


def extract_remote_image(descriptor: Optional[Dict[str, Any]], adapter_results: List[RawAdapterResult]) -> Optional[str]:
    if descriptor:
        image = descriptor.get("image") if isinstance(descriptor, dict) else None
        if isinstance(image, str) and image.strip().lower().startswith("http"):
            return image.strip()
    for res in adapter_results:
        payload = res.payload or {}
        for key in ("image", "image_path"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip().lower().startswith("http"):
                return candidate.strip()
    return None


def ensure_local_image_asset(ean: str, descriptor: Optional[Dict[str, Any]], adapter_results: List[RawAdapterResult]) -> Optional[Dict[str, Any]]:
    if not descriptor:
        return descriptor

    image_value = descriptor.get("image")
    remote_url: Optional[str] = None

    if isinstance(image_value, str) and image_value.startswith("./assets/"):
        asset_path = ASSETS_DIR / Path(image_value).name
        if asset_path.exists():
            return descriptor
    elif isinstance(image_value, str) and image_value.strip().lower().startswith("http"):
        remote_url = html.unescape(image_value.strip())

    if not remote_url:
        remote_url = extract_remote_image(descriptor, adapter_results)

    if not remote_url:
        return descriptor

    try:
        remote_url = html.unescape(remote_url).strip()
        remote_url = re.sub(r"\s+", "", remote_url)
        parsed = urlparse(remote_url)
    except Exception:
        return descriptor

    ext = os.path.splitext(parsed.path)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"

    dest_name = f"{ean}{ext}"
    dest_path = ASSETS_DIR / dest_name
    try:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        with urlopen(remote_url, timeout=15) as response:
            data = response.read()
        if not data:
            return descriptor
        dest_path.write_bytes(data)
    except Exception:
        return descriptor

    updated = dict(descriptor)
    updated["image"] = f"./assets/{dest_path.name}"
    save_manual_descriptor_entry(ean, updated)
    return updated


def descriptor_from_payload(ean: str, adapter: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not payload:
        return {}
    raw_title = payload.get("title") or payload.get("name")
    name = raw_title.strip() if isinstance(raw_title, str) else None
    quantity = payload.get("quantity") or ""
    image = payload.get("image") or payload.get("image_path")
    if isinstance(image, str):
        image = html.unescape(image.strip())
    descriptor = {
        "ean": ean,
        "name": name,
        "quantity": quantity,
        "categories": "",
        "image": image,
        "source": adapter,
        "description": payload.get("description") or name or "",
        "note": payload.get("note") or f"Collecte seed via {adapter}",
    }
    # attempt to guess brand from payload/title if not provided
    brand_candidate = infer_brand_from_payload(payload)
    if brand_candidate:
        descriptor["brand"] = brand_candidate
    elif not descriptor.get("brand"):
        inferred_from_title = infer_brand_from_title(name) if isinstance(name, str) else None
        if inferred_from_title and not is_generic_brand(inferred_from_title):
            descriptor["brand"] = inferred_from_title
    if payload.get("nutriscore_grade"):
        descriptor["nutriscore_grade"] = payload.get("nutriscore_grade")
    if payload.get("nutriscore_image"):
        descriptor["nutriscore_image"] = payload.get("nutriscore_image")
    if payload.get("ecoscore_grade"):
        descriptor["ecoscore_grade"] = payload.get("ecoscore_grade")
    if payload.get("ecoscore_image"):
        descriptor["ecoscore_image"] = payload.get("ecoscore_image")
    if payload.get("nova_group"):
        descriptor["nova_group"] = payload.get("nova_group")
    descriptor["seed_query"] = build_seed_query_from_descriptor(descriptor)
    leclerc_profile = build_leclerc_search_profile(descriptor)
    leclerc_queries = leclerc_profile.get("queries") or []
    if not leclerc_queries:
        fallback_ean = descriptor.get("ean")
        if fallback_ean:
            leclerc_queries = [str(fallback_ean).strip()]
    if leclerc_queries:
        descriptor["leclerc_query"] = leclerc_queries[0]
        descriptor["leclerc_queries"] = leclerc_queries
    if leclerc_profile.get("primary_keywords"):
        descriptor["primary_keywords"] = leclerc_profile["primary_keywords"]
    if leclerc_profile.get("secondary_keywords"):
        descriptor["secondary_keywords"] = leclerc_profile["secondary_keywords"]
    return descriptor


def _needs_enrichment(descriptor: Dict[str, Any]) -> bool:
    if not isinstance(descriptor, dict):
        return True
    if not (descriptor.get("name") and descriptor.get("quantity")):
        return True
    if is_generic_brand(descriptor.get("brand")):
        return True
    if not descriptor.get("image"):
        return True
    grade = (descriptor.get("nutriscore_grade") or "").strip().lower()
    if grade in ("", "unknown", "na", "n/a"):
        return True
    return False


def ensure_descriptor_via_seed(
    *,
    ean: str,
    descriptor: Optional[Dict[str, Any]],
    query: str,
    adapters: List[str],
    headed: bool,
    proxy: Optional[str],
) -> tuple[Dict[str, Any], Dict[str, RawAdapterResult], str]:
    seed_results: Dict[str, RawAdapterResult] = {}
    descriptor_current = dict(descriptor or {"ean": ean})

    seed_order = ["carrefour_city", "carrefour_market", "auchan", "chronodrive", "courseu"]

    for adapter in seed_order:
        if adapter not in adapters:
            continue
        if adapter in seed_results:
            continue
        print(f"[SEED] Tentative via {adapter}")
        res = run_adapter(
            adapter,
            ean,
            ean,
            headless=not headed,
            proxy=proxy,
            descriptor=descriptor_current,
        )
        seed_results[adapter] = res
        if res.status == "OK" and isinstance(res.payload, dict):
            updates = descriptor_from_payload(ean, adapter, res.payload)
            descriptor_current = merge_descriptor(descriptor_current, updates)
            if adapter in {"carrefour_city", "carrefour_market"}:
                if updates.get("name") and not descriptor_current.get("seed_primary_name"):
                    descriptor_current["seed_primary_name"] = updates.get("name")
                if updates.get("quantity") and not descriptor_current.get("seed_primary_quantity"):
                    descriptor_current["seed_primary_quantity"] = updates.get("quantity")
            save_manual_descriptor_entry(ean, descriptor_current)

    new_query = build_search_query(ean, descriptor_current)
    descriptor_current["seed_query"] = new_query
    leclerc_profile = build_leclerc_search_profile(descriptor_current)
    leclerc_queries = leclerc_profile.get("queries") or []
    if not leclerc_queries:
        fallback_ean = descriptor_current.get("ean")
        if fallback_ean:
            leclerc_queries = [str(fallback_ean).strip()]
    if leclerc_queries:
        descriptor_current["leclerc_query"] = leclerc_queries[0]
        descriptor_current["leclerc_queries"] = leclerc_queries
    if leclerc_profile.get("primary_keywords"):
        descriptor_current["primary_keywords"] = leclerc_profile["primary_keywords"]
    if leclerc_profile.get("secondary_keywords"):
        descriptor_current["secondary_keywords"] = leclerc_profile["secondary_keywords"]
    save_manual_descriptor_entry(ean, descriptor_current)
    return descriptor_current, seed_results, new_query


def build_search_query(ean: str, descriptor: Optional[Dict[str, str]]) -> str:
    if not descriptor:
        return ean
    seed = build_seed_query_from_descriptor(descriptor)
    descriptor["seed_query"] = seed
    return seed or ean


def run_adapter(
    adapter: str,
    ean: str,
    query: Optional[str],
    *,
    headless: bool,
    proxy: Optional[str],
    extra_env: Optional[Dict[str, str]] = None,
    descriptor: Optional[Dict[str, Any]] = None,
) -> RawAdapterResult:
    if adapter not in ADAPTER_SCRIPTS:
        raise ValueError(f"Adaptateur inconnu: {adapter}")
    entry = ADAPTER_SCRIPTS[adapter]
    script_path = entry["script"]
    if not script_path.exists():
        raise FileNotFoundError(f"Script introuvable pour {adapter}: {script_path}")

    env = os.environ.copy()
    configured_env = entry.get("env", {})
    if callable(configured_env):
        configured_env = configured_env()
    env.update(configured_env or {})
    if extra_env:
        env.update(extra_env)
    env["EAN"] = ean
    env["HEADLESS"] = "1" if headless else "0"
    env.setdefault("USE_CDP", "1")
    if "CDP_URL" not in env and os.getenv("CDP_URL"):
        env["CDP_URL"] = os.environ["CDP_URL"]
    if proxy:
        env["PROXY"] = proxy
    def severity(status: str) -> int:
        status = (status or "").upper()
        if status == "OK":
            return 4
        if status == "NO_PRICE":
            return 3
        if status == "NO_RESULTS":
            return 2
        if status == "NO_MATCH":
            return 1
        return 0

    query_candidates: List[str]
    if adapter in EAN_ONLY_ADAPTERS:
        query_candidates = [ean]
    else:
        candidates: List[str] = []
        if query and query.strip():
            candidates.append(query.strip())
        if adapter == "leclerc" and descriptor:
            for value in descriptor.get("leclerc_queries", []) or []:
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
            extra = descriptor.get("leclerc_query")
            if isinstance(extra, str) and extra.strip():
                candidates.append(extra.strip())
            seed_q = descriptor.get("seed_query")
            if isinstance(seed_q, str) and seed_q.strip():
                candidates.append(seed_q.strip())
        if ean and ean.strip():
            candidates.append(ean.strip())
        if not candidates:
            candidates = [(query or ean or "").strip()]
        seen_queries = set()
        query_candidates = []
        for cand in candidates:
            if not cand:
                continue
            if cand in seen_queries:
                continue
            seen_queries.add(cand)
            query_candidates.append(cand)

    best_result: Optional[RawAdapterResult] = None
    for candidate_query in query_candidates:
        local_env = env.copy()
        if adapter in EAN_ONLY_ADAPTERS:
            local_env["QUERY"] = ean
        else:
            local_env["QUERY"] = candidate_query

        command = [sys.executable, str(script_path)]
        started_at = datetime.utcnow()
        proc = subprocess.run(
            command,
            env=local_env,
            capture_output=True,
            text=True,
            cwd=str(ROOT_DIR),
        )
        finished_at = datetime.utcnow()
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip() if proc.stderr else None

        payload: Dict[str, Any]
        status = "ERROR"
        error = None
        if stdout:
            brace_start = stdout.find('{')
            brace_end = stdout.rfind('}')
            if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
                json_candidate = stdout[brace_start:brace_end + 1]
            else:
                json_candidate = ""
            try:
                payload = json.loads(json_candidate)
                status = payload.get("status", "UNKNOWN")
            except json.JSONDecodeError:
                sanitized = json_candidate.replace("\r", " ").replace("\n", " ")
                try:
                    payload = json.loads(sanitized)
                    status = payload.get("status", "UNKNOWN")
                except json.JSONDecodeError as exc:
                    payload = {
                        "raw_stdout": stdout,
                        "last_line": json_candidate,
                    }
                    error = f"JSONDecodeError: {exc}"
        else:
            payload = {}
            error = "EMPTY_STDOUT"

        if proc.returncode != 0 and not error:
            error = f"exit_code={proc.returncode}"

        result = RawAdapterResult(
            adapter=adapter,
            status=status,
            payload=payload,
            started_at=started_at,
            finished_at=finished_at,
            script_path=str(script_path),
            command=command,
            env={
                k: local_env.get(k, "")
                for k in [
                    "EAN",
                    "QUERY",
                    "STORE_QUERY",
                    "STORE_URL",
                    "HOME_URL",
                    "CARREFOUR_STATE_VARIANT",
                    "HEADLESS",
                    "PROXY",
                ]
                if local_env.get(k) is not None
            },
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            error=error,
            metadata={
                "attempt_query": candidate_query,
            },
        )

        if best_result is None or severity(result.status) > severity(best_result.status):
            best_result = result

        if severity(result.status) >= severity("NO_PRICE"):
            return result

    if best_result is not None:
        return best_result

    # Fallback: return last attempt result even if none succeeded
    return RawAdapterResult(
        adapter=adapter,
        status="ERROR",
        payload={},
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        script_path=str(script_path),
        command=[sys.executable, str(script_path)],
        env={
            "EAN": env.get("EAN", ""),
            "QUERY": env.get("QUERY", ""),
        },
        exit_code=1,
        stdout="",
        stderr="",
        error="Aucune tentative de collecte leclerc n'a abouti",
        metadata={},
    )


def ensure_results_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_run(run: PipelineRun, *, results_dir: Path) -> Path:
    ensure_results_dir(results_dir)
    timestamp = run.finished_at.strftime("%Y%m%d-%H%M%S")
    fname = f"run-{run.ean}-{timestamp}.json"
    full_path = results_dir / fname
    with full_path.open("w", encoding="utf-8") as fh:
        json.dump(run.as_dict(), fh, ensure_ascii=False, indent=2)
    latest_path = results_dir / "latest.json"
    with latest_path.open("w", encoding="utf-8") as fh:
        json.dump(run.as_dict(), fh, ensure_ascii=False, indent=2)
    return full_path


def update_summary(run: PipelineRun, *, results_dir: Path) -> None:
    summary_path = results_dir / "summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            summary = {}
    else:
        summary = {}

    ean_entry = summary.setdefault(run.ean, {})
    for res in run.adapter_results:
        ean_entry[res.adapter] = {
            "status": res.status,
            "payload": res.payload,
            "updated_at": run.finished_at.isoformat(),
            "duration_seconds": (res.finished_at - res.started_at).total_seconds(),
            "error": res.error,
            "store_query": res.env.get("STORE_QUERY"),
        }

    summary[run.ean] = ean_entry
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline MaxiCourses (proof of concept)")
    parser.add_argument("--ean", help="EAN à traiter")
    parser.add_argument("--image", help="Chemin vers l'image contenant le code-barres")
    parser.add_argument("--proxy", help="Proxy Playwright (ex: socks5://user:pass@host:port)")
    parser.add_argument("--headed", action="store_true", help="Affiche les navigateurs (HEADLESS=0)")
    parser.add_argument("--adapters", nargs="*", choices=list(ADAPTER_SCRIPTS.keys()), help="Liste d'adaptateurs à exécuter")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Répertoire de sortie pour les JSON")
    parser.add_argument("--human", action="store_true", help="Active un mode debug humain (screenshots, timings)" )
    parser.add_argument("--human-debug-root", help="Répertoire parent pour stocker les captures du mode humain")
    return parser.parse_args(argv)


def sanitize_ean(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\D", "", str(value))


def ensure_valid_ean(ean: str) -> str:
    digits = sanitize_ean(ean)
    if len(digits) != EAN_REQUIRED_LENGTH:
        raise ValueError(f"EAN invalide : {ean} (attendu {EAN_REQUIRED_LENGTH} chiffres)")
    return digits


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if not args.ean and not args.image:
        print("[ERREUR] Fournir --ean ou --image")
        return 2

    image_path = None
    ean = sanitize_ean(args.ean)
    if args.image:
        image_path = Path(args.image)
        if not image_path.exists():
            print(f"[ERREUR] Image introuvable: {image_path}")
            return 2
        ean = decode_ean(image_path)
        print(f"EAN détecté depuis l'image: {ean}")
        ean = sanitize_ean(ean)

    if not ean:
        print("[ERREUR] Aucun EAN disponible")
        return 2

    try:
        ean = ensure_valid_ean(ean)
    except ValueError as exc:
        print(f"[ERREUR] {exc}")
        return 2

    descriptor = load_manual_descriptor(ean)
    if descriptor:
        print("Descriptor (manuel):", json.dumps(descriptor, ensure_ascii=False))
    else:
        print("[WARN] Aucun descriptif manuel pour", ean)

    query = build_search_query(ean, descriptor)

    started_at = datetime.utcnow()
    adapters = args.adapters or DEFAULT_ADAPTER_ORDER

    human_mode = args.human or args.headed
    debug_root: Optional[Path] = None
    if human_mode:
        base_debug = Path(args.human_debug_root) if args.human_debug_root else (Path(args.results_dir) / "debug")
        ensure_results_dir(base_debug)
        debug_root = base_debug / f"run-{ean}-{started_at.strftime('%Y%m%d-%H%M%S')}"
        debug_root.mkdir(parents=True, exist_ok=True)
    results: List[RawAdapterResult] = []

    descriptor, seed_results, query = ensure_descriptor_via_seed(
        ean=ean,
        descriptor=descriptor,
        query=query,
        adapters=adapters,
        headed=args.headed,
        proxy=args.proxy,
    )
    descriptor = ensure_brand_from_results(ean, descriptor, list(seed_results.values()))
    descriptor = ensure_nutriscore_from_results(ean, descriptor, list(seed_results.values()))
    query = build_search_query(ean, descriptor)

    for adapter in adapters:
        print(f"\n=== Adaptateur {adapter} ===")
        if adapter in seed_results:
            res = seed_results[adapter]
            results.append(res)
            print(json.dumps(res.payload, ensure_ascii=False))
            if res.error:
                print(f"[WARN] {adapter} -> {res.error}")
            continue
        adapter_debug = None
        if debug_root:
            adapter_debug = debug_root / f"{len(results)+1:02d}-{adapter}"
            adapter_debug.mkdir(parents=True, exist_ok=True)

        adapter_query = query
        if adapter == "leclerc":
            candidate = descriptor.get("leclerc_query") if descriptor else None
            if isinstance(candidate, str) and candidate.strip():
                adapter_query = candidate.strip()
        elif adapter == "monoprix" and descriptor:
            monoprix_queries = descriptor.get("queries", {}).get("monoprix") if isinstance(descriptor.get("queries"), dict) else None
            if isinstance(monoprix_queries, list) and monoprix_queries:
                candidate = monoprix_queries[0]
                if isinstance(candidate, str) and candidate.strip():
                    adapter_query = candidate.strip()

        res = run_adapter(
            adapter,
            ean,
            adapter_query,
            headless=not args.headed,
            proxy=args.proxy,
            extra_env={"HUMAN_DEBUG_DIR": str(adapter_debug)} if adapter_debug else None,
            descriptor=descriptor,
        )
        results.append(res)
        print(json.dumps(res.payload, ensure_ascii=False))
        if res.error:
            print(f"[WARN] {adapter} -> {res.error}")
        if adapter_debug:
            res.metadata["debug_dir"] = str(adapter_debug)

    descriptor = ensure_brand_from_results(ean, descriptor, results)
    descriptor = ensure_nutriscore_from_results(ean, descriptor, results)
    descriptor = ensure_local_image_asset(ean, descriptor, results)
    if descriptor:
        leclerc_profile = build_leclerc_search_profile(descriptor)
        leclerc_queries = leclerc_profile.get("queries") or []
        if not leclerc_queries:
            fallback_ean = descriptor.get("ean")
            if fallback_ean:
                leclerc_queries = [str(fallback_ean).strip()]
        if leclerc_queries:
            descriptor["leclerc_query"] = leclerc_queries[0]
            descriptor["leclerc_queries"] = leclerc_queries
        if leclerc_profile.get("primary_keywords"):
            descriptor["primary_keywords"] = leclerc_profile["primary_keywords"]
        if leclerc_profile.get("secondary_keywords"):
            descriptor["secondary_keywords"] = leclerc_profile["secondary_keywords"]
        save_manual_descriptor_entry(ean, descriptor)

    finished_at = datetime.utcnow()

    nutri_score_value = None
    if descriptor:
        raw_score = descriptor.get("nutriscore_score")
        try:
            nutri_score_value = int(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            nutri_score_value = None

    eco_grade = descriptor.get("ecoscore_grade") if descriptor else None
    eco_image = descriptor.get("ecoscore_image") if descriptor else None
    nova_group = descriptor.get("nova_group") if descriptor else None

    run = PipelineRun(
        ean=ean,
        image_path=str(image_path) if image_path else None,
        started_at=started_at,
        finished_at=finished_at,
        adapter_results=results,
        reference_title=descriptor.get("name") if descriptor else None,
        reference_description=descriptor.get("description") if descriptor else None,
        reference_source=descriptor.get("source") if descriptor else None,
        reference_brand=descriptor.get("brand") if descriptor else None,
        reference_quantity=descriptor.get("quantity") if descriptor else None,
        reference_image=descriptor.get("image") if descriptor else None,
        reference_categories=descriptor.get("categories") if descriptor else None,
        reference_nutriscore_grade=descriptor.get("nutriscore_grade") if descriptor else None,
        reference_nutriscore_image=descriptor.get("nutriscore_image") if descriptor else None,
        reference_nutriscore_score=nutri_score_value,
        reference_ecoscore_grade=eco_grade,
        reference_ecoscore_image=eco_image,
        reference_nova_group=nova_group,
    )

    if human_mode and debug_root:
        run.notes.append(f"Human debug captures dans {debug_root}")

    results_dir = Path(args.results_dir)
    update_summary(run, results_dir=results_dir)
    output_path = save_run(run, results_dir=results_dir)
    print(f"\nRésultats enregistrés dans {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
