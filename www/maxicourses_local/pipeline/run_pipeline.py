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
import concurrent.futures
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from types import SimpleNamespace
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from zoneinfo import ZoneInfo

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
AI_LOG_ROOT = ROOT_DIR / "logs" / "refonte_v2" / "runs"
QUERY_CACHE_PATH = ROOT_DIR / "pipeline" / "query_cache.json"

SIZE_TOKEN_SUFFIXES = ("ml", "cl", "dl", "l", "g", "kg")
PARIS_TZ = ZoneInfo("Europe/Paris")


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
    "moutarde",
    "specialite",
    "spécialité",
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
    "boire",
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

AI_ASSIST_ENABLED: bool = False
ai_summarize_product_seed = None
ai_suggest_search_queries = None
QUERY_CACHE_ADAPTERS = {"monoprix"}
_QUERY_CACHE: Optional[Dict[str, Any]] = None


def _make_ai_log_dir(ean: str) -> Path:
    timestamp = datetime.now(PARIS_TZ).strftime("%Y%m%d-%H%M%S")
    safe_ean = "".join(ch for ch in str(ean) if ch.isdigit()) or str(ean)
    path = AI_LOG_ROOT / f"{timestamp}-{safe_ean}-{os.getpid()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _log_ai_response(log_dir: Optional[Path], slug: str, response: Any, *, extra: Optional[Dict[str, Any]] = None) -> None:
    if not log_dir or response is None:
        return
    payload = {
        "timestamp": datetime.now(PARIS_TZ).isoformat(),
        "status": getattr(response, "status", None),
        "data": getattr(response, "data", None),
        "error": getattr(response, "error", None),
        "raw_prompt": getattr(response, "raw_prompt", None),
        "raw_response": getattr(response, "raw_response", None),
    }
    if extra:
        payload["extra"] = extra
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _load_query_cache() -> Dict[str, Any]:
    global _QUERY_CACHE
    if _QUERY_CACHE is not None:
        return _QUERY_CACHE
    if QUERY_CACHE_PATH.exists():
        try:
            _QUERY_CACHE = json.loads(QUERY_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _QUERY_CACHE = {}
    else:
        _QUERY_CACHE = {}
    return _QUERY_CACHE


def _cached_query_for(adapter: str, ean: str) -> Optional[str]:
    if adapter not in QUERY_CACHE_ADAPTERS:
        return None
    cache = _load_query_cache()
    entry = cache.get(adapter, {}).get(ean)
    if isinstance(entry, dict):
        value = entry.get("query")
        if isinstance(value, str) and value.strip():
            return value.strip()
    elif isinstance(entry, str):
        return entry.strip()
    return None


def _store_cached_query(adapter: str, ean: str, query: Optional[str]) -> None:
    if adapter not in QUERY_CACHE_ADAPTERS:
        return
    if not isinstance(query, str):
        return
    cleaned = " ".join(query.split())
    if not cleaned:
        return
    cache = _load_query_cache()
    adapter_cache = cache.setdefault(adapter, {})
    adapter_cache[ean] = {
        "query": cleaned,
        "updated_at": datetime.now(PARIS_TZ).isoformat(),
    }
    try:
        QUERY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUERY_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


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
        if len(normalized) <= 2:
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
            if not normalized or len(normalized) <= 2 or normalized in STOPWORDS:
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


def _quantity_rank(value: Optional[str]) -> int:
    if not isinstance(value, str):
        return 3
    cleaned = value.strip().upper()
    if not cleaned:
        return 3
    if re.search(r"\b(ML|L|CL)\b", cleaned):
        return 0
    if re.search(r"\b(KG|G)\b", cleaned):
        return 1
    return 2


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
            if not normalized or len(normalized) <= 2 or normalized in STOPWORDS:
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
        if not normalized or len(normalized) <= 2 or normalized in STOPWORDS:
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
    from pipeline.finder import (  # type: ignore
        ProductDescriptor,
        KeywordGenerator,
        FinderPipeline,
        MatchResult,
        ImageCompareProvider,
        KEYWORD_REGISTRY,
    )
    from pipeline.text_utils import is_pack_or_bundle, norm_brand, norm_qty  # type: ignore
    from descriptor_store import (  # type: ignore
        get_descriptor as get_seed_descriptor,
        descriptor_exists as seed_descriptor_exists,
        add_dynamic_seed_entry,
        all_descriptors as descriptor_catalog_all,
    )
    try:
        from ai_helpers import (  # type: ignore
            USE_AI_ASSIST as AI_ASSIST_ENABLED,  # noqa: N812 - keep legacy casing
            summarize_product_seed as ai_summarize_product_seed,
            suggest_search_queries as ai_suggest_search_queries,
        )
    except Exception:
        AI_ASSIST_ENABLED = False
        ai_summarize_product_seed = None
        ai_suggest_search_queries = None
else:  # pragma: no cover - executed when package imports are available
    from ..decode_ean import decode_image_to_ean  # type: ignore
    from .models import PipelineRun, RawAdapterResult
    from .finder import (
        ProductDescriptor,
        FinderPipeline,
        MatchResult,
        ImageCompareProvider,
        KEYWORD_REGISTRY,
    )
    from .text_utils import is_pack_or_bundle, norm_brand, norm_qty
    from ..descriptor_store import (
        get_descriptor as get_seed_descriptor,
        descriptor_exists as seed_descriptor_exists,
        add_dynamic_seed_entry,
        all_descriptors as descriptor_catalog_all,
    )
    try:
        from ..ai_helpers import (  # type: ignore
            USE_AI_ASSIST as AI_ASSIST_ENABLED,  # noqa: N812 - keep legacy casing
            summarize_product_seed as ai_summarize_product_seed,
            suggest_search_queries as ai_suggest_search_queries,
        )
    except Exception:
        AI_ASSIST_ENABLED = False
        ai_summarize_product_seed = None
        ai_suggest_search_queries = None
DEFAULT_RESULTS_DIR = ROOT_DIR / "results"
MANUAL_DESCRIPTOR_PATH = ROOT_DIR / "manual_descriptors.json"
DESCRIPTOR_CACHE_PATH = ROOT_DIR / "pipeline" / "descriptor_cache.json"
ALLOWED_MANUAL_DESCRIPTOR_FIELDS = {
    "ean",
    "source",
    "courseu_url",
    "courseu_slug",
    "name",
    "description",
    "brand",
    "quantity",
    "image",
    "categories",
    "nutriscore_grade",
    "nutriscore_image",
    "ecoscore_grade",
    "ecoscore_image",
    "nova_group",
    "seed_primary_name",
    "seed_primary_quantity",
    "seed_query",
    "leclerc_query",
    "note",
}

ALWAYS_OVERRIDE_FIELDS = {
    "image",
    "nutriscore_grade",
    "nutriscore_image",
    "ecoscore_grade",
    "ecoscore_image",
    "nova_group",
}


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
    "carrefour_super": {
        "script": ROOT_DIR / "fetch_carrefour_price_super.py",
        "env": lambda: {
            "CARREFOUR_STATE_VARIANT": os.getenv("CARREFOUR_SUPER_STATE", "carrefour_super"),
            "CARREFOUR_SUPER_FRONTAL_STORE": os.getenv("CARREFOUR_SUPER_FRONTAL_STORE", "116"),
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
            "HOME_URL": os.getenv("AUCHAN_HOME_URL", "https://www.auchan.fr/magasins/drive/auchan-drive-supermarche-talence-gallieni/s-6117"),
            
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
    "g20": {
        "script": ROOT_DIR / "fetch_g20_price.py",
        "env": lambda: {
            "G20_SEARCH_TEMPLATE": os.getenv(
                "G20_SEARCH_TEMPLATE",
                "https://www.g20-minute.com/search/{ean}",
            ),
            "G20_BASE_URL": os.getenv("G20_BASE_URL", "https://www.g20-minute.com"),
        },
    },
}

ADAPTER_CDP_PORTS: Dict[str, int] = {
    "carrefour_city": int(os.getenv("CDP_PORT_CARREFOUR_CITY", "9222")),
    "carrefour_market": int(os.getenv("CDP_PORT_CARREFOUR_MARKET", "9223")),
    "carrefour_super": int(os.getenv("CDP_PORT_CARREFOUR_SUPER", "9224")),
    "auchan": int(os.getenv("CDP_PORT_AUCHAN", "9225")),
    "chronodrive": int(os.getenv("CDP_PORT_CHRONODRIVE", "9226")),
    "courseu": int(os.getenv("CDP_PORT_COURSEU", "9227")),
    "g20": int(os.getenv("CDP_PORT_G20", "9228")),
    "intermarche": int(os.getenv("CDP_PORT_INTERMARCHE", "9229")),
    "leclerc": int(os.getenv("CDP_PORT_LECLERC", "9230")),
    "monoprix": int(os.getenv("CDP_PORT_MONOPRIX", "9231")),
}


def _cdp_url_for_adapter(adapter: str) -> Optional[str]:
    port = ADAPTER_CDP_PORTS.get(adapter)
    if not port:
        return None
    return f"http://127.0.0.1:{port}"

EAN_ONLY_ADAPTERS = {
    "carrefour_city",
    "carrefour_market",
    "carrefour_super",
    "auchan",
    "chronodrive",
    "courseu",
    "g20",
}

DEFAULT_ADAPTER_ORDER = [
    "carrefour_city",
    "carrefour_market",
    "carrefour_super",
    "auchan",
    "chronodrive",
    "courseu",
    "g20",
    "intermarche",
    "leclerc",
    "monoprix",
]

NUTRISCORE_ADAPTER_PRIORITY = {
    "carrefour_market": 120,
    "carrefour_super": 115,
    "carrefour_city": 110,
    "chronodrive": 105,
}


def decode_ean(image_path: Path) -> str:
    if Image is None or zxingcpp is None:
        raise RuntimeError("Lecture d'image indisponible (Pillow/zxingcpp manquants)")
    value = decode_image_to_ean(image_path)
    if not value:
        raise RuntimeError(f"Impossible d'extraire un EAN depuis {image_path}")
    return value


def refresh_descriptor_cache() -> None:
    try:
        catalog = descriptor_catalog_all()
    except Exception:
        return
    try:
        DESCRIPTOR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        DESCRIPTOR_CACHE_PATH.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def load_manual_descriptor(ean: str) -> Optional[Dict[str, Any]]:
    return None


def fetch_manual_descriptor(ean: str) -> Optional[Dict[str, Any]]:
    # Historical alias kept for backward compatibility (server/importers)
    return load_manual_descriptor(ean)


def load_all_descriptors() -> Dict[str, Dict[str, Any]]:
    return {}


def save_manual_descriptor_entry(ean: str, entry: Dict[str, Any]) -> None:
    return
    refresh_descriptor_cache()


def merge_descriptor(base: Optional[Dict[str, Any]], updates: Dict[str, Any]) -> Dict[str, Any]:
    descriptor = dict(base or {})
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if key in ALWAYS_OVERRIDE_FIELDS:
            descriptor[key] = value
            continue
        if key not in {"quantity", "brand"}:
            existing = descriptor.get(key)
            if isinstance(existing, str):
                if existing.strip():
                    continue
            elif existing not in (None, False):
                if existing != []:
                    continue
        if key == "quantity":
            existing_quantity = descriptor.get("quantity")
            if existing_quantity:
                current_rank = _quantity_rank(existing_quantity)
                new_rank = _quantity_rank(value)
                if current_rank <= new_rank:
                    continue
        if key == "brand":
            existing = descriptor.get("brand")
            existing_norm = normalize_brand_candidate(existing)
            value_norm = normalize_brand_candidate(value)
            if existing_norm and not is_generic_brand(existing_norm):
                if not value_norm:
                    continue
                if existing_norm.lower() != value_norm.lower():
                    continue
            if (not existing_norm or is_generic_brand(existing_norm)) and is_generic_brand(value):
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

    best_candidate: Optional[Tuple[int, str, Optional[str]]] = None
    for res in adapter_results:
        if res.adapter not in {"carrefour_city", "carrefour_market", "carrefour_super"}:
            continue
        payload = res.payload or {}
        candidate_grade = payload.get("nutriscore_grade")
        if not isinstance(candidate_grade, str) or not candidate_grade.strip():
            continue
        grade_value = candidate_grade.strip().lower()
        priority = NUTRISCORE_ADAPTER_PRIORITY.get(res.adapter, 0)
        image_candidate = payload.get("nutriscore_image")
        if (
            best_candidate is None
            or priority > best_candidate[0]
        ):
            best_candidate = (priority, grade_value, image_candidate if isinstance(image_candidate, str) else None)

    if best_candidate:
        _, grade_value, image_candidate = best_candidate
        updated = dict(descriptor)
        updated["nutriscore_grade"] = grade_value
        if grade_value in {"a", "b", "c", "d", "e"}:
            updated["nutriscore_image"] = local_asset_for(grade_value)
        elif isinstance(image_candidate, str) and image_candidate.strip():
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


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _qualifiers_from_any(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if isinstance(item, (str, int, float)) and str(item).strip()]
    if isinstance(value, str):
        parts = re.split(r"[;,/]", value)
        return [part.strip() for part in parts if part.strip()]
    return []


def _payload_to_product_descriptor(payload: Dict[str, Any], source: str) -> Optional[ProductDescriptor]:
    if not isinstance(payload, dict):
        return None
    status_value = str(payload.get("status") or "").upper()
    if status_value in {"NO_MATCH", "NO_RESULTS", "ERROR", "TIMEOUT", "CF_BLOCK"}:
        return None
    title = payload.get("title") or payload.get("name")
    brand = payload.get("brand") or ""
    kind = payload.get("kind") or payload.get("category") or payload.get("type") or ""
    qty = payload.get("quantity") or payload.get("qty") or payload.get("size") or payload.get("weight") or ""
    qualifiers = payload.get("qualifiers") or payload.get("features") or payload.get("tags")
    ean_value = payload.get("matched_ean") or payload.get("ean")
    image_candidate = payload.get("image_url") or payload.get("image") or payload.get("thumbnail")
    raw_text = payload.get("raw_text") or payload.get("description") or payload.get("long_description") or ""
    product_block = payload.get("product") if isinstance(payload.get("product"), dict) else {}

    if not brand and isinstance(product_block, dict):
        brand = product_block.get("brand") or ""
    if not kind and isinstance(product_block, dict):
        kind = product_block.get("kind") or ""
    if not qty and isinstance(product_block, dict):
        qty = product_block.get("qty") or ""
    if not raw_text and isinstance(product_block, dict):
        raw_text = product_block.get("raw_text") or ""
    if not title and isinstance(product_block, dict):
        title = product_block.get("title") or ""
    if not qualifiers and isinstance(product_block, dict):
        qualifiers = product_block.get("qualifiers") or []

    if not any([title, brand, kind, qty, raw_text]):
        return None

    if isinstance(image_candidate, list):
        image_candidate = next((str(x).strip() for x in image_candidate if isinstance(x, (str, int, float))), None)
    elif isinstance(image_candidate, (str, int, float)):
        image_candidate = _stringify(image_candidate)
    else:
        image_candidate = None

    qualifiers_list = _qualifiers_from_any(qualifiers)

    title_str = _stringify(title)
    brand_str = norm_brand(_stringify(brand))
    kind_str = _stringify(kind)
    qty_str = norm_qty(_stringify(qty))
    raw_text_str = _stringify(raw_text)
    if raw_text_str and len(raw_text_str.split()) > 120:
        raw_text_str = " ".join(raw_text_str.split()[:120])
    if raw_text_str and len(raw_text_str) > 600:
        raw_text_str = raw_text_str[:600].rsplit(" ", 1)[0]
    if not brand_str and title_str:
        candidate_brand = title_str.split()[0]
        if candidate_brand and len(candidate_brand) >= 3:
            brand_str = norm_brand(candidate_brand)
    return ProductDescriptor(
        title=title_str,
        brand=brand_str,
        kind=kind_str,
        qty=qty_str,
        qualifiers=qualifiers_list,
        ean=_stringify(ean_value) or None,
        image_url=image_candidate,
        source=source,
        raw_text=raw_text_str,
    )


def _normalized_candidate(adapter: str, url: Optional[str], product_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pd = _payload_to_product_descriptor(product_data, adapter)
    if not pd:
        return None
    if adapter == "intermarche" and url:
        match = re.search(r"\b(\d{8,14})\b", url)
        if match:
            pd.ean = match.group(1)
    if is_pack_or_bundle(pd.title, pd.raw_text):
        return None
    return {
        "url": url or "",
        "product": asdict(pd),
    }


def annotate_adapter_payload(adapter: str, payload: Dict[str, Any], *, ean: str) -> None:
    if not isinstance(payload, dict):
        return

    if adapter in EAN_ONLY_ADAPTERS:
        meta = payload.setdefault("_meta", {})
        meta["supports_ean"] = True
        product = _payload_to_product_descriptor(payload, adapter)
        if product:
            if not product.ean:
                product.ean = ean
            payload["product"] = asdict(product)
        return

    meta = payload.setdefault("_meta", {})
    meta["supports_keywords"] = True

    base_candidates: List[Dict[str, Any]] = []
    existing_candidates = payload.get("candidates")
    if isinstance(existing_candidates, list):
        base_candidates = [c for c in existing_candidates if isinstance(c, dict)]

    if not base_candidates:
        product = _payload_to_product_descriptor(payload, adapter)
        url = _stringify(payload.get("url") or payload.get("product_url") or payload.get("href"))
        if product and url and not is_pack_or_bundle(product.title, product.raw_text):
            base_candidates = [{"url": url, "product": asdict(product)}]

    normalized: List[Dict[str, Any]] = []
    for entry in base_candidates:
        url = _stringify(entry.get("url"))
        product_dict = entry.get("product")
        if not isinstance(product_dict, dict):
            product_dict = {}
        candidate = _normalized_candidate(adapter, url, product_dict)
        if candidate:
            normalized.append(candidate)
        if len(normalized) >= 10:
            break

    payload["candidates"] = normalized


def _default_html_provider(url: str) -> Optional[str]:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
        with urlopen(req, timeout=12) as response:
            code = getattr(response, "status", None)
            if code is None:
                try:
                    code = response.getcode()
                except Exception:
                    code = None
            if code and code >= 400:
                return None
            data = response.read()
            if not data:
                return None
            charset = response.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="ignore")
    except Exception:
        return None
def build_finder_block(
    *,
    ean: str,
    descriptor: Optional[Dict[str, Any]],
    adapter_results: List[RawAdapterResult],
    threshold: float,
) -> Optional[Dict[str, Any]]:
    fp = FinderPipeline()

    seeds_added = False
    for res in adapter_results:
        if res.adapter not in EAN_ONLY_ADAPTERS:
            continue
        if res.status != "OK":
            continue
        pd = _payload_to_product_descriptor(res.payload, source=res.adapter)
        if pd:
            fp.consolidator.add(pd)
            seeds_added = True

    if descriptor:
        pd_descriptor = _payload_to_product_descriptor(descriptor, source=str(descriptor.get("source") or "manual"))
        if pd_descriptor:
            fp.consolidator.add(pd_descriptor)
            seeds_added = True

    if not seeds_added:
        return None

    consolidated = fp.consolidator.merged()
    if not consolidated.ean:
        consolidated.ean = ean

    keywords = fp.generate_keywords(consolidated)

    candidates: List[MatchResult] = []
    for res in adapter_results:
        if res.adapter in EAN_ONLY_ADAPTERS:
            continue
        if res.status != "OK":
            continue

        entries: List[Dict[str, Any]] = []
        raw_entries = res.payload.get("candidates")
        if isinstance(raw_entries, list):
            entries = [entry for entry in raw_entries if isinstance(entry, dict)]

        if not entries:
            fallback_pd = _payload_to_product_descriptor(res.payload, source=res.adapter)
            fallback_url = _stringify(res.payload.get("url") or res.payload.get("product_url") or res.payload.get("href"))
            if fallback_pd and fallback_url and not is_pack_or_bundle(fallback_pd.title, fallback_pd.raw_text):
                entries = [
                    {
                        "url": fallback_url,
                        "product": asdict(fallback_pd),
                    }
                ]

        adapter_cls = next((cls for cls in KEYWORD_REGISTRY if getattr(cls, "name", "") == res.adapter), None)
        adapter_instance = adapter_cls() if adapter_cls else None
        if adapter_instance and adapter_instance.name == "leclerc" and not getattr(adapter_instance, "_html_provider", None):
            adapter_instance._html_provider = _default_html_provider

        policy = fp._policy(res.adapter)
        adapter_provider: Optional[ImageCompareProvider] = None
        if adapter_instance and hasattr(adapter_instance, "image_compare"):
            try:
                adapter_provider = adapter_instance.image_compare()
            except Exception:
                adapter_provider = None

        for entry in entries:
            url = _stringify(entry.get("url"))
            product_data = entry.get("product") if isinstance(entry.get("product"), dict) else {}
            candidate_pd = _payload_to_product_descriptor(product_data, source=res.adapter)
            if not candidate_pd:
                continue

            score = fp.matcher.score(consolidated, candidate_pd)
            base_score = score
            forced_score = False
            if adapter_instance:
                original_strict = fp.matcher.strict_qty
                override_strict = adapter_instance.override_strict_qty()
                if override_strict is not None:
                    fp.matcher.strict_qty = bool(override_strict)
                try:
                    forced = adapter_instance.hard_validate(consolidated, url, candidate_pd)
                    if forced is not None:
                        score = float(forced)
                        forced_score = True
                    else:
                        score = fp.matcher.score(consolidated, candidate_pd)
                        base_score = score
                finally:
                    fp.matcher.strict_qty = original_strict

            if not forced_score:
                img_pass = True
                if policy.require_image_lock:
                    img_pass = fp.matcher.image_match(
                        consolidated.image_url,
                        candidate_pd.image_url,
                        provider=adapter_provider,
                    )
                meets_threshold = base_score >= policy.min_text_score
                if policy.require_image_lock and img_pass and not meets_threshold:
                    score = max(base_score, policy.min_text_score)
                    meets_threshold = True
                else:
                    score = base_score
                if adapter_instance and adapter_instance.name == "monoprix" and img_pass:
                    score = max(score, 0.995)

            candidates.append(
                MatchResult(
                    adapter=res.adapter,
                    url=url,
                    descriptor=candidate_pd,
                    score=score,
                )
            )

    if not candidates:
        return {
            "consolidated": asdict(consolidated),
            "keywords": keywords,
            "candidates": [],
            "decision": None,
            "audit": [asdict(entry) for entry in fp.audit],
        }

    candidates.sort(key=lambda r: -r.score)
    decision = fp.decide(consolidated, candidates, threshold=threshold)

    return {
        "consolidated": asdict(consolidated),
        "keywords": keywords,
        "candidates": [
            {
                "adapter": c.adapter,
                "url": c.url,
                "score": round(float(c.score), 4),
                "product": asdict(c.descriptor),
            }
            for c in candidates[:20]
        ],
        "decision": (
            {
                "adapter": decision.adapter,
                "url": decision.url,
                "score": round(float(decision.score), 4),
                "product": asdict(decision.descriptor),
            }
            if decision
            else None
        ),
        "audit": [asdict(entry) for entry in fp.audit],
    }


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
    return descriptor


def _seed_payloads_for_ai(seed_results: Dict[str, "RawAdapterResult"]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for res in seed_results.values():
        if res.status != "OK":
            continue
        payload = res.payload if isinstance(res.payload, dict) else None
        if not payload:
            continue
        entry = {
            "adapter": res.adapter,
            "status": res.status,
            "payload": payload,
        }
        if res.metadata:
            entry["metadata"] = res.metadata
        entries.append(entry)
    return entries


def _apply_ai_summary_to_descriptor(descriptor: Dict[str, Any], summary_payload: Dict[str, Any]) -> bool:
    updated = False
    profile = summary_payload.get("profile")
    if isinstance(profile, dict):
        descriptor["ai_profile"] = profile
        profile_brand = profile.get("brand")
        if profile_brand and (
            not descriptor.get("brand") or is_generic_brand(descriptor.get("brand"))
        ):
            normalized = normalize_brand_candidate(profile_brand)
            descriptor["brand"] = normalized or profile_brand
        updated = True
    keywords = summary_payload.get("keywords")
    if isinstance(keywords, list):
        descriptor["ai_keywords"] = [kw for kw in keywords if isinstance(kw, str) and kw.strip()]
        updated = True
    primary_keywords = summary_payload.get("primary_keywords")
    if isinstance(primary_keywords, list) and primary_keywords:
        descriptor["primary_keywords"] = [
            " ".join(str(item).split()) for item in primary_keywords if isinstance(item, str)
        ]
        updated = True
    secondary_keywords = summary_payload.get("secondary_keywords")
    if isinstance(secondary_keywords, list) and secondary_keywords:
        descriptor["secondary_keywords"] = [
            " ".join(str(item).split()) for item in secondary_keywords if isinstance(item, str)
        ]
        updated = True
    category = summary_payload.get("category")
    if isinstance(category, str) and category:
        descriptor["ai_category"] = category
        updated = True
    if updated:
        descriptor["ai_profile_generated_at_eur"] = datetime.now(PARIS_TZ).isoformat()
    return updated


def run_ai_seed_summary(
    ean: str,
    descriptor: Dict[str, Any],
    seed_results: Dict[str, "RawAdapterResult"],
    *,
    log_dir_provider: Callable[[], Optional[Path]],
) -> Optional[Dict[str, Any]]:
    if not AI_ASSIST_ENABLED or ai_summarize_product_seed is None:
        return None
    seed_payloads = _seed_payloads_for_ai(seed_results)
    if not seed_payloads:
        return None
    context = {
        "descriptor": descriptor,
        "ean": ean,
    }
    try:
        response = ai_summarize_product_seed(seed_payloads, context=context)
    except Exception as exc:  # pragma: no cover - network/runtime errors
        log_dir = log_dir_provider()
        inline = SimpleNamespace(
            status="exception",
            data={"exception": str(exc)},
            error=str(exc),
            raw_prompt=None,
            raw_response=None,
        )
        _log_ai_response(log_dir, "01_seed_summary_error", inline)
        return None
    log_dir = log_dir_provider()
    _log_ai_response(log_dir, "01_seed_summary", response)
    if response.status != "ok":
        return None
    data = response.data or {}
    if _apply_ai_summary_to_descriptor(descriptor, data):
        save_manual_descriptor_entry(ean, descriptor)
    return data


def run_ai_store_queries(
    store: str,
    descriptor: Dict[str, Any],
    *,
    log_dir_provider: Callable[[], Optional[Path]],
    profile: Optional[Dict[str, Any]] = None,
    max_queries: int = 5,
    max_length: int = 30,
) -> Dict[str, Any]:
    if not AI_ASSIST_ENABLED or ai_suggest_search_queries is None:
        return {}
    ai_profile = profile or descriptor.get("ai_profile")
    if not isinstance(ai_profile, dict):
        return {}
    try:
        response = ai_suggest_search_queries(
            ai_profile,
            descriptor=descriptor,
            store=store,
            max_queries=max_queries,
            max_length=max_length,
        )
    except Exception as exc:  # pragma: no cover - network/runtime errors
        log_dir = log_dir_provider()
        inline = SimpleNamespace(
            status="exception",
            data={"exception": str(exc)},
            error=str(exc),
            raw_prompt=None,
            raw_response=None,
        )
        _log_ai_response(log_dir, f"02_queries_{store}_error", inline)
        return {}
    log_dir = log_dir_provider()
    _log_ai_response(log_dir, f"02_queries_{store}", response)
    if response.status != "ok":
        return {}
    return response.data or {}


def _apply_store_queries_to_descriptor(
    descriptor: Dict[str, Any],
    store: str,
    queries_payload: Dict[str, Any],
) -> List[str]:
    if not queries_payload:
        return []
    queries_raw = queries_payload.get("queries")
    if not isinstance(queries_raw, list):
        return []
    cleaned: List[str] = []
    seen_lower: set[str] = set()
    for item in queries_raw:
        if not isinstance(item, str):
            continue
        candidate = " ".join(item.split())
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in seen_lower:
            continue
        seen_lower.add(lowered)
        cleaned.append(candidate)
    if not cleaned:
        return []
    descriptor[f"{store}_ai_queries"] = cleaned
    if store == "leclerc":
        descriptor["leclerc_queries"] = cleaned
        descriptor["leclerc_query"] = cleaned[0]
    else:
        descriptor[f"{store}_queries"] = cleaned
        queries_block = descriptor.get("queries")
        if not isinstance(queries_block, dict):
            queries_block = {}
        queries_block[store] = cleaned
        descriptor["queries"] = queries_block
    secondary = queries_payload.get("secondary_keywords")
    if isinstance(secondary, list):
        descriptor[f"{store}_secondary_keywords"] = [
            " ".join(str(item).split()) for item in secondary if isinstance(item, str)
        ]
    if store == "leclerc" and "primary_keywords" not in descriptor and cleaned:
        descriptor["primary_keywords"] = cleaned[:5]
    save_manual_descriptor_entry(str(descriptor.get("ean", "")), descriptor)
    return cleaned


def _merge_keyword_sources(*sources: Optional[Iterable[str]], limit: int = 8) -> List[str]:
    merged: List[str] = []
    seen: set[str] = set()
    for source in sources:
        if not source:
            continue
        if isinstance(source, str):
            iterable = [source]
        else:
            iterable = list(source)  # type: ignore[arg-type]
        for item in iterable:
            if not isinstance(item, str):
                continue
            candidate = " ".join(item.split())
            if not candidate:
                continue
            lowered = candidate.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            merged.append(candidate)
            if limit and len(merged) >= limit:
                return merged
    return merged


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
    base_descriptor = get_seed_descriptor(ean) or {"ean": ean}
    descriptor_current = {"ean": ean}
    best_seed_score = 0
    if base_descriptor:
        if base_descriptor.get("source") in {"carrefour_market", "carrefour_city", "carrefour_super"}:
            descriptor_current.update(base_descriptor)
            best_seed_score = 2
        else:
            descriptor_current.update(base_descriptor)
            best_seed_score = 1
    if descriptor:
        descriptor_current = merge_descriptor(descriptor_current, descriptor)
    seed_missing = not seed_descriptor_exists(ean)

    seed_order = [
        "carrefour_city",
        "carrefour_market",
        "carrefour_super",
        "auchan",
        "chronodrive",
        "courseu",
        "g20",
    ]

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
        annotate_adapter_payload(adapter, res.payload, ean=ean)
        seed_results[adapter] = res
        if res.status == "OK" and isinstance(res.payload, dict):
            updates = descriptor_from_payload(ean, adapter, res.payload)
            descriptor_current = merge_descriptor(descriptor_current, updates)
            seed_score = 2 if adapter in {"carrefour_city", "carrefour_market", "carrefour_super"} else 1
            if seed_score >= best_seed_score:
                descriptor_current["source"] = adapter.replace("carrefour_", "carrefour_")
                best_seed_score = seed_score
            if adapter in {"carrefour_city", "carrefour_market", "carrefour_super"}:
                if updates.get("name") and not descriptor_current.get("seed_primary_name"):
                    descriptor_current["seed_primary_name"] = updates.get("name")
                if updates.get("quantity") and not descriptor_current.get("seed_primary_quantity"):
                    descriptor_current["seed_primary_quantity"] = updates.get("quantity")
            save_manual_descriptor_entry(ean, descriptor_current)

    if base_descriptor:
        fallback_fields = (
            "name",
            "description",
            "brand",
            "quantity",
            "seed_primary_name",
            "seed_primary_quantity",
            "note",
        )
        for key in fallback_fields:
            if descriptor_current.get(key):
                continue
            value = base_descriptor.get(key)
            if isinstance(value, str) and value.strip():
                descriptor_current[key] = value.strip()
        if not descriptor_current.get("image"):
            seed_image = base_descriptor.get("image")
            if isinstance(seed_image, str) and seed_image.strip():
                descriptor_current["image"] = seed_image.strip()
        if not descriptor_current.get("source"):
            descriptor_current["source"] = base_descriptor.get("source")

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
    save_manual_descriptor_entry(ean, descriptor_current)
    if seed_missing:
        add_dynamic_seed_entry(descriptor_current)
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
    finder_keywords: Optional[List[str]] = None,
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
    if "CDP_URL" not in env:
        adapter_cdp = _cdp_url_for_adapter(adapter)
        if adapter_cdp:
            env["CDP_URL"] = adapter_cdp
    if extra_env:
        env.update(extra_env)
    env["EAN"] = ean
    env["HEADLESS"] = "1" if headless else "0"
    env.setdefault("USE_CDP", "1")
    if "CDP_URL" not in env and os.getenv("CDP_URL"):
        env["CDP_URL"] = os.environ["CDP_URL"]
    if proxy:
        env["PROXY"] = proxy
    if finder_keywords:
        cleaned_keywords = [
            " ".join(kw.split())
            for kw in finder_keywords
            if isinstance(kw, str) and kw.strip()
        ]
        if cleaned_keywords:
            env["FINDER_KEYWORDS"] = json.dumps(cleaned_keywords, ensure_ascii=False)
    else:
        env.pop("FINDER_KEYWORDS", None)
    if adapter == "monoprix":
        env.setdefault("MONOPRIX_MAX_TERMS", "3")
        env.setdefault("MONOPRIX_MAX_PRODUCTS", "4")
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
        seen: set[str] = set()
        adapter_uses_ean_search = adapter not in {"leclerc"}

        def add_candidate(value: Optional[str]) -> None:
            if not isinstance(value, str):
                return
            cleaned = value.strip()
            if not cleaned or cleaned.lower() in seen:
                return
            seen.add(cleaned.lower())
            candidates.append(cleaned)

        cached_query = _cached_query_for(adapter, ean)
        if cached_query:
            add_candidate(cached_query)

        if finder_keywords:
            for kw in finder_keywords:
                add_candidate(kw)
        if adapter != "leclerc":
            add_candidate(query)
        if descriptor and adapter != "leclerc":
            seed_q = descriptor.get("seed_query")
            add_candidate(seed_q)
        if adapter_uses_ean_search:
            add_candidate(ean)
        if not candidates:
            fallback = None
            if not finder_keywords:
                fallback = query if query else (ean if adapter_uses_ean_search else None)
            add_candidate(fallback)
        if adapter == "monoprix" and len(candidates) > 4:
            candidates = candidates[:4]
        query_candidates = candidates

    best_result: Optional[RawAdapterResult] = None
    for candidate_query in query_candidates:
        local_env = env.copy()
        if adapter in EAN_ONLY_ADAPTERS:
            local_env["QUERY"] = ean
        else:
            local_env["QUERY"] = candidate_query

        command = [sys.executable, str(script_path)]
        started_at = datetime.now(PARIS_TZ)
        proc = subprocess.run(
            command,
            env=local_env,
            capture_output=True,
            text=True,
            cwd=str(ROOT_DIR),
        )
        finished_at = datetime.now(PARIS_TZ)
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

        meta = None
        if isinstance(payload, dict):
            raw_meta = payload.get("_meta")
            if isinstance(raw_meta, dict):
                meta = raw_meta
        abort_requested = bool(meta and meta.get("abort_search"))
        abort_reason = meta.get("abort_reason") if isinstance(meta, dict) else None

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
        if abort_requested and abort_reason:
            result.metadata["abort_reason"] = abort_reason

        if best_result is None or severity(result.status) > severity(best_result.status):
            best_result = result

        if abort_requested:
            return result

        if severity(result.status) >= severity("NO_PRICE"):
            if result.status == "OK":
                last_query = result.metadata.get("attempt_query") if isinstance(result.metadata, dict) else None
                if not last_query:
                    last_query = candidate_query
                _store_cached_query(adapter, ean, last_query)
            return result

    if best_result is not None:
        if best_result.status == "OK":
            last_query = best_result.metadata.get("attempt_query") if isinstance(best_result.metadata, dict) else None
            if not last_query:
                last_query = best_result.env.get("QUERY")
            _store_cached_query(adapter, ean, last_query)
        return best_result

    # Fallback: return last attempt result even if none succeeded
    return RawAdapterResult(
        adapter=adapter,
        status="ERROR",
        payload={},
        started_at=datetime.now(PARIS_TZ),
        finished_at=datetime.now(PARIS_TZ),
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
        previous_entry = ean_entry.get(res.adapter)
        previous_snapshot = None
        if isinstance(previous_entry, dict):
            previous_snapshot = {
                "status": previous_entry.get("status"),
                "payload": previous_entry.get("payload"),
                "updated_at": previous_entry.get("updated_at"),
                "error": previous_entry.get("error"),
                "store_query": previous_entry.get("store_query"),
            }
        entry = {
            "status": res.status,
            "payload": res.payload,
            "updated_at": run.finished_at.isoformat(),
            "duration_seconds": (res.finished_at - res.started_at).total_seconds(),
            "error": res.error,
            "store_query": res.env.get("STORE_QUERY"),
        }
        if previous_snapshot:
            entry["previous"] = previous_snapshot
        ean_entry[res.adapter] = entry

    if run.finder is not None:
        ean_entry["_finder"] = run.finder

    summary[run.ean] = ean_entry
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def export_dataset_snapshot(run: PipelineRun, *, results_dir: Path) -> None:
    dataset_dir = results_dir / f"test-{run.ean}"
    ensure_results_dir(dataset_dir)
    dataset_latest = dataset_dir / "latest.json"
    dataset_latest.write_text(json.dumps(run.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    dataset_summary_path = dataset_dir / "summary.json"
    if dataset_summary_path.exists():
        try:
            dataset_summary = json.loads(dataset_summary_path.read_text(encoding="utf-8"))
        except Exception:
            dataset_summary = {}
    else:
        dataset_summary = {}
    ean_entry = dataset_summary.setdefault(run.ean, {})
    for res in run.adapter_results:
        ean_entry[res.adapter] = {
            "status": res.status,
            "payload": res.payload,
            "updated_at": run.finished_at.isoformat(),
            "duration_seconds": (res.finished_at - res.started_at).total_seconds(),
            "error": res.error,
            "store_query": res.env.get("STORE_QUERY"),
        }
    if run.finder is not None:
        ean_entry["_finder"] = run.finder
    dataset_summary[run.ean] = ean_entry
    dataset_summary_path.write_text(json.dumps(dataset_summary, ensure_ascii=False, indent=2), encoding="utf-8")


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
    parser.add_argument("--use_finder", action="store_true", help="Active le post-traitement Finder")
    parser.add_argument("--finder_threshold", type=float, default=0.7, help="Seuil de décision Finder")
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
    ai_log_dir: Optional[Path] = None

    def ensure_ai_log_dir() -> Optional[Path]:
        nonlocal ai_log_dir
        if ai_log_dir is not None:
            return ai_log_dir
        try:
            ai_log_dir = _make_ai_log_dir(ean)
        except Exception:
            ai_log_dir = None
        return ai_log_dir

    started_at = datetime.now(PARIS_TZ)
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
    run_ai_seed_summary(
        ean,
        descriptor,
        seed_results,
        log_dir_provider=ensure_ai_log_dir,
    )
    descriptor = ensure_brand_from_results(ean, descriptor, list(seed_results.values()))
    descriptor = ensure_nutriscore_from_results(ean, descriptor, list(seed_results.values()))
    query = build_search_query(ean, descriptor)
    ai_profile_block = descriptor.get("ai_profile") if isinstance(descriptor.get("ai_profile"), dict) else None
    leclerc_ai_payload = run_ai_store_queries(
        "leclerc",
        descriptor,
        log_dir_provider=ensure_ai_log_dir,
        profile=ai_profile_block,
    )
    leclerc_ai_queries = _apply_store_queries_to_descriptor(descriptor, "leclerc", leclerc_ai_payload)
    monoprix_ai_payload = run_ai_store_queries(
        "monoprix",
        descriptor,
        log_dir_provider=ensure_ai_log_dir,
        profile=ai_profile_block,
    )
    monoprix_ai_queries = _apply_store_queries_to_descriptor(descriptor, "monoprix", monoprix_ai_payload)

    heuristic_keywords: List[str] = []
    seed_fp = FinderPipeline()
    for res in seed_results.values():
        if res.status == "OK":
            pd_seed = _payload_to_product_descriptor(res.payload, res.adapter)
            if pd_seed:
                seed_fp.consolidator.add(pd_seed)
    base_pd_descriptor_input = dict(descriptor or {"ean": ean})
    base_pd_descriptor_input["source"] = "seed"
    pd_descriptor = _payload_to_product_descriptor(base_pd_descriptor_input, "seed")
    if pd_descriptor:
        seed_fp.consolidator.add(pd_descriptor)
    if seed_fp.consolidator.sources:
        merged_seed = seed_fp.consolidator.merged()
        heuristic_keywords = KeywordGenerator(max_keywords=4).make(merged_seed)
    elif pd_descriptor:
        heuristic_keywords = KeywordGenerator(max_keywords=4).make(pd_descriptor)

    ai_primary_source = descriptor.get("primary_keywords")
    if isinstance(ai_primary_source, list):
        ai_primary_keywords = [str(item) for item in ai_primary_source if isinstance(item, (str, int, float))]
    else:
        ai_primary_keywords = []
    default_keywords = _merge_keyword_sources(ai_primary_keywords, heuristic_keywords, limit=8)
    adapter_keyword_map = {
        "leclerc": _merge_keyword_sources(leclerc_ai_queries, default_keywords, heuristic_keywords, limit=8),
        "monoprix": _merge_keyword_sources(monoprix_ai_queries, default_keywords, heuristic_keywords, limit=3),
    }
    if not default_keywords:
        default_keywords = heuristic_keywords

parallel_adapters = os.getenv("PARALLEL_ADAPTERS", "0").lower() in {"1", "true", "yes"}

    def _prepare_adapter(adapter_name: str, index: int):
        adapter_debug: Optional[Path] = None
        if debug_root:
            adapter_debug = debug_root / f"{index:02d}-{adapter_name}"
            adapter_debug.mkdir(parents=True, exist_ok=True)
        adapter_query = query
        keywords_for_adapter = adapter_keyword_map.get(adapter_name) or default_keywords
        if not keywords_for_adapter:
            keywords_for_adapter = heuristic_keywords
        return adapter_debug, adapter_query, keywords_for_adapter

    if not parallel_adapters:
        for idx, adapter in enumerate(adapters, 1):
            print(f"\n=== Adaptateur {adapter} ===")
            if adapter in seed_results:
                res = seed_results[adapter]
                annotate_adapter_payload(adapter, res.payload, ean=ean)
                results.append(res)
                print(json.dumps(res.payload, ensure_ascii=False))
                if res.error:
                    print(f"[WARN] {adapter} -> {res.error}")
                continue

            adapter_debug, adapter_query, keywords_for_adapter = _prepare_adapter(adapter, len(results)+1)
            res = run_adapter(
                adapter,
                ean,
                adapter_query,
                headless=not args.headed,
                proxy=args.proxy,
                extra_env={"HUMAN_DEBUG_DIR": str(adapter_debug)} if adapter_debug else None,
                descriptor=descriptor,
                finder_keywords=keywords_for_adapter,
            )
            annotate_adapter_payload(adapter, res.payload, ean=ean)
            results.append(res)
            print(json.dumps(res.payload, ensure_ascii=False))
            if res.error:
                print(f"[WARN] {adapter} -> {res.error}")
            if adapter_debug:
                res.metadata["debug_dir"] = str(adapter_debug)
    else:
        tasks = []
        adapter_order = list(adapters)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(adapter_order)) as executor:
            for idx, adapter in enumerate(adapter_order, 1):
                if adapter in seed_results:
                    res = seed_results[adapter]
                    annotate_adapter_payload(adapter, res.payload, ean=ean)
                    results.append(res)
                    print(f"\n=== Adaptateur {adapter} ===")
                    print(json.dumps(res.payload, ensure_ascii=False))
                    if res.error:
                        print(f"[WARN] {adapter} -> {res.error}")
                    continue
                adapter_debug, adapter_query, keywords_for_adapter = _prepare_adapter(adapter, idx)
                fut = executor.submit(
                    run_adapter,
                    adapter,
                    ean,
                    adapter_query,
                    headless=not args.headed,
                    proxy=args.proxy,
                    extra_env={"HUMAN_DEBUG_DIR": str(adapter_debug)} if adapter_debug else None,
                    descriptor=descriptor,
                    finder_keywords=keywords_for_adapter,
                )
                tasks.append((adapter, adapter_debug, fut))

            for adapter, adapter_debug, fut in tasks:
                print(f"\n=== Adaptateur {adapter} ===")
                try:
                    res = fut.result()
                except Exception as exc:  # pragma: no cover - defensive
                    res = RawAdapterResult(
                        adapter=adapter,
                        status="ERROR",
                        payload={"status": "ERROR", "error": str(exc)},
                        started_at=datetime.now(PARIS_TZ),
                        finished_at=datetime.now(PARIS_TZ),
                        script_path=str(ADAPTER_SCRIPTS[adapter]["script"]),
                        command=[sys.executable, str(ADAPTER_SCRIPTS[adapter]["script"])],
                        env={},
                        exit_code=-1,
                        stdout="",
                        stderr=str(exc),
                    )
                annotate_adapter_payload(adapter, res.payload, ean=ean)
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
        ai_leclerc_cached = descriptor.get("leclerc_ai_queries")
        if isinstance(ai_leclerc_cached, list) and ai_leclerc_cached:
            descriptor["leclerc_query"] = ai_leclerc_cached[0]
            descriptor["leclerc_queries"] = ai_leclerc_cached
        else:
            leclerc_profile = build_leclerc_search_profile(descriptor)
            leclerc_queries = leclerc_profile.get("queries") or []
            if not leclerc_queries:
                fallback_ean = descriptor.get("ean")
                if fallback_ean:
                    leclerc_queries = [str(fallback_ean).strip()]
            if leclerc_queries:
                descriptor["leclerc_query"] = leclerc_queries[0]
                descriptor["leclerc_queries"] = leclerc_queries
        save_manual_descriptor_entry(ean, descriptor)

    finder_block: Optional[Dict[str, Any]] = None
    if args.use_finder:
        try:
            finder_block = build_finder_block(
                ean=ean,
                descriptor=descriptor,
                adapter_results=results,
                threshold=args.finder_threshold,
            )
            if finder_block:
                decision = finder_block.get("decision")
                if decision:
                    print("\n[Finder] Décision:", json.dumps(decision, ensure_ascii=False))
                else:
                    print("\n[Finder] Aucun match retenu (candidats analysés).")
            else:
                print("\n[Finder] Post-traitement indisponible (seeds/candidats manquants).")
        except Exception as exc:  # pragma: no cover - instrumentation best effort
            print(f"\n[WARN] Finder post-traitement: {exc}")
            finder_block = {"error": str(exc)}

    finished_at = datetime.now(PARIS_TZ)

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
        finder=finder_block,
    )

    if human_mode and debug_root:
        run.notes.append(f"Human debug captures dans {debug_root}")

    results_dir = Path(args.results_dir)
    update_summary(run, results_dir=results_dir)
    output_path = save_run(run, results_dir=results_dir)
    export_dataset_snapshot(run, results_dir=results_dir)
    print(f"\nRésultats enregistrés dans {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
