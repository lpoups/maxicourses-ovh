#!/usr/bin/env python3
"""Fetcher Monoprix (texte uniquement) respectant le mandat de collecte."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
import typing
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, quote, quote_plus
import logging
from playwright.async_api import Page

print("--- DÉBUT DE L'EXÉCUTION DE FETCH_MONOPRIX_PRICE ---", file=sys.stderr)

from rich import print
import requests

try:  # Pillow est optionnel mais requis pour le matching visuel
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for  # noqa: E402
from collection_mandate import get_method  # noqa: E402


EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
HOME_URL = os.environ.get("HOME_URL", "https://courses.monoprix.fr/")
STORE_URL = os.environ.get("STORE_URL", "")
MANDATE = get_method("monoprix")
DEBUG_MONOPRIX = os.environ.get("DEBUG_MONOPRIX") == "1"
DEBUG_DUMP_ROOT = os.environ.get("HUMAN_DEBUG_DIR") or os.environ.get("MONOPRIX_DEBUG_DIR")
FAILURE_LOG_PATH = Path(__file__).resolve().with_name("logs") / "seed_failures.log"

IMAGE_HASH_CACHE: dict[Path, int] = {}
REMOTE_HASH_CACHE: dict[str, int] = {}

# Mots-clés pour détecter les cartes où le produit n'est pas disponible
CARD_BANNED_KEYWORDS = {
    "la carte n'est pas acceptée",
    "la carte n'est pas acceptée",
}

# --- Patterns Regex ---
MULTIPLIER_PATTERN = re.compile(r"\b\d+\s*(?:x|×)\s*\d+\b", flags=re.IGNORECASE)
# Manual descriptor cache
MANUAL_DESCRIPTOR: dict[str, dict] = {}
try:
    # Build a path to the descriptor file relative to this script's location.
    # This is more robust than assuming a specific parent directory structure.
    descriptor_path = Path(__file__).resolve().parent / "manual_descriptors.json"
    
    sys.stderr.write(f"[MONOPRIX_DEBUG] Attempting to load manual descriptors from: {descriptor_path}\n")

    if descriptor_path.exists():
        MANUAL_DESCRIPTOR = json.loads(descriptor_path.read_text(encoding="utf-8"))
        sys.stderr.write(f"[MONOPRIX_DEBUG] SUCCESS: manual_descriptors.json loaded successfully.\n")
    else:
        sys.stderr.write(f"[MONOPRIX_DEBUG] CRITICAL: manual_descriptors.json not found at the expected path.\n")
        # As a fallback, check the parent directory, just in case.
        fallback_path = Path(__file__).resolve().parent.parent / "manual_descriptors.json"
        sys.stderr.write(f"[MONOPRIX_DEBUG] Attempting fallback path: {fallback_path}\n")
        if fallback_path.exists():
            MANUAL_DESCRIPTOR = json.loads(fallback_path.read_text(encoding="utf-8"))
            sys.stderr.write(f"[MONOPRIX_DEBUG] SUCCESS: Loaded manual_descriptors.json from fallback path.\n")
        else:
            sys.stderr.write(f"[MONOPRIX_DEBUG] CRITICAL: Fallback path also failed. Descriptors are NOT loaded.\n")

except Exception as e:
    sys.stderr.write(f"[MONOPRIX_DEBUG] ERROR: An exception occurred while loading manual_descriptors.json: {e}\n")
    MANUAL_DESCRIPTOR = {}


@dataclass
class Result:
    status: str
    price: typing.Optional[str] = None
    title: typing.Optional[str] = None
    url: typing.Optional[str] = None
    note: typing.Optional[str] = None
    matched_ean: typing.Optional[str] = None
    unit_price: typing.Optional[str] = None
    quantity: typing.Optional[str] = None
    store: typing.Optional[str] = None


def tokens_for(value: typing.Optional[str]) -> list[str]:
    if not isinstance(value, str):
        return []
    return [tok for tok in re.findall(r"[0-9a-zà-öø-ÿ]+", value.lower()) if len(tok) >= 3]


def normalize_space(value: typing.Optional[str]) -> typing.Optional[str]:
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip()


async def read_text(locator, *, timeout: int = 500) -> typing.Optional[str]:
    """Safely return the first locator text, or None on timeout/missing node."""
    try:
        handle = locator.first
        if not await handle.count():
            return None
        raw = await handle.text_content(timeout=timeout)
        return normalize_space(raw)
    except Exception:
        return None


def _descriptor_image_path(descriptor: dict[str, typing.Any]) -> typing.Optional[Path]:
    image_ref = descriptor.get("image")
    if isinstance(image_ref, str) and image_ref.strip():
        candidate = Path(image_ref.strip())
        if not candidate.is_absolute():
            base_dir = Path(__file__).resolve().parent
            candidate = base_dir / candidate
            if candidate.exists():
                return candidate
            pipeline_candidate = base_dir / "pipeline" / image_ref.strip().lstrip("./")
            if pipeline_candidate.exists():
                return pipeline_candidate
        elif candidate.exists():
            return candidate
    ean = descriptor.get("ean") or EAN
    if ean:
        base_dir = Path(__file__).resolve().parent
        for path in [base_dir / "assets" / f"{ean}.jpg", base_dir / "pipeline" / "assets" / f"{ean}.jpg"]:
            if path.exists():
                return path
    return None


def _descriptor_remote_images(descriptor: dict[str, typing.Any]) -> list[str]:
    urls: list[str] = []
    candidates: list[typing.Optional[str]] = [descriptor.get("image")]
    ai_profile = descriptor.get("ai_profile")
    if isinstance(ai_profile, dict):
        candidates.append(ai_profile.get("image"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            trimmed = candidate.strip()
            if trimmed.startswith("http") and trimmed not in urls:
                urls.append(trimmed)
    return urls


def _average_hash(image, hash_size: int = 16) -> int:
    # image: Image.Image (type hint original pour référence)
    resample = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
    grayscale = image.convert("L").resize((hash_size, hash_size), resample=resample)
    pixels = list(grayscale.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for idx, pixel in enumerate(pixels):
        if pixel > avg:
            bits |= 1 << idx
    return bits


def _hash_distance(first: int, second: int) -> int:
    return bin(first ^ second).count("1")


def _local_image_hash(path: Path) -> typing.Optional[int]:
    if path in IMAGE_HASH_CACHE:
        return IMAGE_HASH_CACHE[path]
    if Image is None:
        return None
    try:
        with Image.open(path) as img:
            value = _average_hash(img)
    except Exception:
        return None
    IMAGE_HASH_CACHE[path] = value
    return value


def _remote_image_hash(url: str) -> typing.Optional[int]:
    cached = REMOTE_HASH_CACHE.get(url)
    if cached is not None:
        return cached
    if Image is None:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": HOME_URL,
    }
    try:
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
    except Exception:
        return None
    try:
        with Image.open(io.BytesIO(response.content)) as img:
            value = _average_hash(img)
    except Exception:
        return None
    REMOTE_HASH_CACHE[url] = value
    return value


def _to_decimal(value: typing.Any) -> typing.Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        cleaned = cleaned.replace("€", "").replace("EUR", "").replace(" ", "").replace(",", ".")
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None
    return None


def _format_price_value(value: typing.Any) -> typing.Optional[str]:
    amount = _to_decimal(value)
    if amount is None:
        return None
    normalized = format(amount.quantize(Decimal("0.01")), "f")
    if "." not in normalized:
        normalized = f"{normalized}.00"
    elif len(normalized.split(".")[1]) < 2:
        normalized = normalized + "0"
    return normalized.replace(".", ",")


def _parse_quantity_to_base(quantity: typing.Optional[str]) -> typing.Optional[tuple[Decimal, str]]:
    if not quantity:
        return None
    text = str(quantity).strip().lower()
    if not text:
        return None
    text = text.replace(" ", "")
    match = re.search(r"(\d+(?:[.,]\d+)?)([a-z]+)", text)
    if not match:
        return None
    value = match.group(1).replace(",", ".")
    unit_raw = match.group(2)
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    if unit_raw in {"ml", "millilitre", "millilitres"}:
        return amount / Decimal(1000), "L"
    if unit_raw in {"cl", "centilitre", "centilitres"}:
        return amount / Decimal(100), "L"
    if unit_raw in {"l", "litre", "litres"}:
        return amount, "L"
    if unit_raw in {"g", "gramme", "grammes"}:
        return amount / Decimal(1000), "KG"
    if unit_raw in {"kg", "kilogramme", "kilogrammes"}:
        return amount, "KG"
    return None


def _normalize_quantity_text(quantity: typing.Optional[str]) -> typing.Optional[str]:
    if not quantity:
        return None
    text = str(quantity).strip()
    if not text:
        return None
    compact = text.replace(" ", "")
    match = re.search(r"(\d+(?:[.,]\d+)?)([a-zA-Z]+)", compact)
    if not match:
        return text
    number = match.group(1).replace(".", ",")
    unit = match.group(2).upper()
    return f"{number} {unit}"


def _compute_unit_price(price_value: typing.Any, quantity: typing.Optional[str]) -> typing.Optional[str]:
    price_amount = _to_decimal(price_value)
    if price_amount is None or price_amount <= 0:
        return None
    parsed = _parse_quantity_to_base(quantity)
    if not parsed:
        return None
    amount, unit = parsed
    if amount is None or amount <= 0:
        return None
    try:
        per_unit = price_amount / amount
    except (ArithmeticError, InvalidOperation):
        return None
    formatted = _format_price_value(per_unit)
    if not formatted:
        return None
    return f"{formatted} € / {unit}"


def _iter_product_nodes(payload: typing.Any) -> typing.Iterator[dict]:
    if isinstance(payload, dict):
        if payload.get("@type") == "Product" or "offers" in payload:
            yield payload
        for value in payload.values():
            if isinstance(value, (dict, list)):
                yield from _iter_product_nodes(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_product_nodes(item)


async def _extract_offer_from_json_ld(page: Page) -> typing.Optional[dict[str, typing.Any]]:
    selectors = [
        "script[data-test='product-details-structured-data']",
        "script[type='application/ld+json']",
    ]
    for selector in selectors:
        try:
            scripts = page.locator(selector)
            count = await scripts.count()
        except Exception:
            continue
        for idx in range(count):
            try:
                raw = await scripts.nth(idx).text_content()
            except Exception:
                continue
            if not raw:
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for candidate in _iter_product_nodes(payload):
                offers = candidate.get("offers")
                if isinstance(offers, list):
                    offers = next((item for item in offers if isinstance(item, dict)), None)
                if not isinstance(offers, dict):
                    continue
                price = offers.get("price")
                currency = offers.get("priceCurrency")
                availability = offers.get("availability")
                size = candidate.get("size") or candidate.get("weight")
                name = candidate.get("name")
                if price is None:
                    continue
                result = {
                    "price": price,
                    "currency": currency,
                    "availability": availability,
                    "size": size,
                    "name": name,
                }
                return result
    return None


def _compare_image_with_descriptor(descriptor: dict[str, typing.Any], image_url: typing.Optional[str], *, threshold: int = 32) -> bool:
    current_ean = descriptor.get("ean") or EAN
    is_debug_ean = current_ean == "3665468000312"
    if is_debug_ean:
        sys.stderr.write(f"\n[DEBUG MONOPRIX IMG] EAN: {current_ean}\n")
        sys.stderr.write(f"[DEBUG MONOPRIX IMG] Comparing Monoprix image: {image_url}\n")
        sys.stderr.write(f"[DEBUG MONOPRIX IMG] Threshold: {threshold}\n")

    if Image is None or not image_url:
        if is_debug_ean:
            sys.stderr.write("[DEBUG MONOPRIX IMG] No image URL or Pillow not installed. Aborting.\n")
        return False
    reference_hashes: list[int] = []
    local_path = _descriptor_image_path(descriptor)
    if local_path:
        local_hash = _local_image_hash(local_path)
        if is_debug_ean:
            sys.stderr.write(f"[DEBUG MONOPRIX IMG] Reference local image: {local_path} -> hash: {local_hash}\n")
        if local_hash is not None:
            reference_hashes.append(local_hash)

    for remote_source in _descriptor_remote_images(descriptor):
        absolute_source = remote_source if remote_source.startswith("http") else urljoin(HOME_URL, remote_source)
        ref_hash = _remote_image_hash(absolute_source)
        if is_debug_ean:
            sys.stderr.write(f"[DEBUG MONOPRIX IMG] Reference remote image: {absolute_source} -> hash: {ref_hash}\n")
        if ref_hash is not None and ref_hash not in reference_hashes:
            reference_hashes.append(ref_hash)

    if not reference_hashes:
        if is_debug_ean:
            sys.stderr.write("[DEBUG MONOPRIX IMG] No valid reference hashes found.\n")
        return False

    absolute_url = image_url if image_url.startswith("http") else urljoin(HOME_URL, image_url)
    remote_hash = _remote_image_hash(absolute_url)
    if is_debug_ean:
        sys.stderr.write(f"[DEBUG MONOPRIX IMG] Monoprix image hash: {remote_hash}\n")

    if remote_hash is None:
        if is_debug_ean:
            sys.stderr.write("[DEBUG MONOPRIX IMG] Could not hash Monoprix image.\n")
        return False

    is_match = False
    for reference in reference_hashes:
        distance = _hash_distance(reference, remote_hash)
        if is_debug_ean:
            sys.stderr.write(f"[DEBUG MONOPRIX IMG] Distance to ref hash {reference}: {distance}\n")
        if distance <= threshold:
            is_match = True
            if is_debug_ean:
                sys.stderr.write(f"[DEBUG MONOPRIX IMG] Match found! Distance {distance} <= {threshold}\n")
            break  # Found a match

    if is_debug_ean:
        sys.stderr.write(f"[DEBUG MONOPRIX IMG] Final decision: {'MATCH' if is_match else 'MISMATCH'}\n\n")

    return is_match


async def _image_matches_descriptor_async(descriptor: dict[str, typing.Any], image_url: typing.Optional[str]) -> bool:
    if Image is None:
        return False
    return await asyncio.to_thread(_compare_image_with_descriptor, descriptor, image_url)


def _log_failure(ean: str, reason: str, descriptor: dict, context: dict) -> None:
    payload = {
        "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "store": "monoprix",
        "product_id": ean,
        "failure_reason": reason,
        "checked_attributes": {
            "ean": ean,
            "brand": descriptor.get("brand"),
            "quantity": descriptor.get("quantity") or descriptor.get("seed_primary_quantity"),
            "variant": descriptor.get("seed_primary_name") or descriptor.get("name"),
        },
        "suggested_action": "affiner mots-clés / heuristiques",
        "additional_info": context,
    }
    try:
        FAILURE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with FAILURE_LOG_PATH.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        logging.exception("Impossible d'écrire le log d'échec Monoprix")


def _has_banned_keyword(text: str) -> bool:
    lowered = text.lower().replace("\xa0", " ")
    if MULTIPLIER_PATTERN.search(lowered):
        return True
    return any(keyword in lowered for keyword in CARD_BANNED_KEYWORDS)


def _prepare_query(term: typing.Optional[str], max_len: int) -> typing.Optional[str]:
    if not isinstance(term, str):
        return None
    
    # Normalise l'espacement et supprime les espaces de début/fin
    candidate = " ".join(term.split()).strip()
    if not candidate:
        return None

    # Garde les mots uniques tout en préservant l'ordre
    tokens = candidate.split()
    unique_tokens = []
    seen_tokens = set()
    for token in tokens:
        # Utilise le token en minuscule pour la déduplication
        lowered_token = token.lower()
        if lowered_token not in seen_tokens:
            unique_tokens.append(token)
            seen_tokens.add(lowered_token)
    
    candidate = " ".join(unique_tokens)

    # Applique les transformations regex
    candidate = re.sub(r"(\d+)\.(\d+)", r"\1,\2", candidate)
    candidate = re.sub(r"(\d),(\d{1,2})([a-zA-Z])", r"\1,\2 \3", candidate)
    candidate = candidate.replace(" l", " L").replace(" ml", " ML").replace(" cl", " CL")

    # Tronque si nécessaire
    if len(candidate) > max_len:
        candidate = candidate[:max_len].rstrip()
        
    return candidate if candidate else None


WORD_PATTERN = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+")
MONOPRIX_UNIT_TOKENS = {
    "ml",
    "l",
    "cl",
    "dl",
    "kg",
    "g",
    "mg",
    "x",
    "lot",
    "lots",
    "pack",
    "packs",
    "u",
    "pc",
    "pcs",
    "tablettes",
    "capsules",
    "bouteille",
    "bouteilles",
    "dose",
    "doses",
}
MONOPRIX_GENERIC_STOPWORDS = {
    "avec",
    "pour",
    "sans",
    "sur",
    "des",
    "les",
    "aux",
    "dans",
    "par",
    "de",
    "du",
    "la",
    "le",
    "et",
    "au",
    "en",
    "un",
    "une",
    "monoprix",
}


def _tokenize_preserve_case(value: typing.Optional[str]) -> list[str]:
    if not isinstance(value, str):
        return []
    return WORD_PATTERN.findall(value)


def _is_valid_brand_token(token: str) -> bool:
    if not token:
        return False
    lowered = token.lower()
    if lowered in MONOPRIX_UNIT_TOKENS or lowered in MONOPRIX_GENERIC_STOPWORDS:
        return False
    return len(lowered) >= 2


def _is_valid_function_token(token: str) -> bool:
    if not token:
        return False
    lowered = token.lower()
    if lowered in MONOPRIX_UNIT_TOKENS or lowered in MONOPRIX_GENERIC_STOPWORDS:
        return False
    if any(ch.isdigit() for ch in lowered):
        return False
    return len(lowered) >= 3


def _iter_descriptor_tokens(descriptor: dict[str, typing.Any]) -> typing.Iterator[str]:
    if not isinstance(descriptor, dict):
        return
    ordered_fields: list[str] = [
        "primary_keywords",
        "secondary_keywords",
        "seed_primary_name",
        "seed_query",
        "name",
        "description",
    ]
    for field in ordered_fields:
        value = descriptor.get(field)
        if isinstance(value, str):
            for token in _tokenize_preserve_case(value):
                yield token
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    for token in _tokenize_preserve_case(item):
                        yield token


def _pick_brand_token(descriptor: dict[str, typing.Any], initial_tokens: list[str]) -> typing.Optional[str]:
    descriptor = descriptor if isinstance(descriptor, dict) else {}
    brand_value = descriptor.get("brand")
    brand_tokens = _tokenize_preserve_case(brand_value)
    for token in brand_tokens:
        if _is_valid_brand_token(token):
            return token
    descriptor_tokens = list(_iter_descriptor_tokens(descriptor))
    combined_tokens: list[str] = list(initial_tokens) + descriptor_tokens
    for token in combined_tokens:
        if token.isupper() and _is_valid_brand_token(token):
            return token
    for token in combined_tokens:
        if token[:1].isupper() and _is_valid_brand_token(token):
            return token
    for token in combined_tokens:
        if _is_valid_brand_token(token):
            return token
    return None


def _select_function_token(
    preferred_tokens: list[str],
    descriptor: dict[str, typing.Any],
    brand_lower: str,
) -> typing.Optional[str]:
    seen: set[str] = set()
    for token in preferred_tokens:
        lowered = token.lower()
        if lowered == brand_lower or lowered in seen:
            continue
        seen.add(lowered)
        if _is_valid_function_token(token):
            return token
    for token in _iter_descriptor_tokens(descriptor):
        lowered = token.lower()
        if lowered == brand_lower or lowered in seen:
            continue
        seen.add(lowered)
        if _is_valid_function_token(token):
            return token
    return None


def _build_two_keyword_query(term: typing.Optional[str], descriptor: dict[str, typing.Any]) -> typing.Optional[str]:
    descriptor = descriptor if isinstance(descriptor, dict) else {}
    tokens = _tokenize_preserve_case(term)
    brand_token = _pick_brand_token(descriptor, tokens)
    if not brand_token:
        return None
    function_token = _select_function_token(tokens, descriptor, brand_token.lower())
    if not function_token:
        function_token = _select_function_token([], descriptor, brand_token.lower())
    if not function_token:
        return None
    return f"{brand_token} {function_token}"


def _enforce_two_keyword_term(
    term: typing.Optional[str],
    descriptor: dict[str, typing.Any],
    max_len: int,
) -> typing.Optional[str]:
    descriptor = descriptor if isinstance(descriptor, dict) else {}
    candidate = _build_two_keyword_query(term, descriptor)
    if not candidate:
        candidate = _build_two_keyword_query("", descriptor)
    if not candidate and isinstance(term, str):
        tokens = _tokenize_preserve_case(term)
        if len(tokens) >= 2:
            candidate = f"{tokens[0]} {tokens[1]}"
        elif len(tokens) == 1:
            # Impossible de construire deux mots, abandon
            return None
    if not candidate:
        return None
    prepared = _prepare_query(candidate, max_len)
    if not prepared:
        return None
    parts = prepared.split()
    if len(parts) > 2:
        prepared = " ".join(parts[:2])
        parts = prepared.split()
    if len(parts) < 2:
        fallback = _build_two_keyword_query("", descriptor)
        if fallback:
            prepared_fallback = _prepare_query(fallback, max_len)
            if prepared_fallback:
                fallback_parts = prepared_fallback.split()
                if len(fallback_parts) >= 2:
                    return " ".join(fallback_parts[:2])
        return None
    return prepared


def _monoprix_fallback_terms(descriptor: dict, max_len: int) -> list[str]:
    terms: list[str] = []
    brand = normalize_space(descriptor.get("brand"))
    quantity = descriptor.get("seed_primary_quantity") or descriptor.get("quantity") or ""
    numbers = set()
    for source in (quantity, descriptor.get("name"), descriptor.get("description")):
        if isinstance(source, str):
            for match in re.findall(r"\d+[.,]?\d*", source):
                numbers.add(match)
    numbers_normalized = set()
    for num in numbers:
        numbers_normalized.add(num)
        numbers_normalized.add(num.replace(".", ","))
        numbers_normalized.add(num.replace(",", "."))

    if brand:
        terms.append(brand)
    for num in sorted(numbers_normalized):
        if not num:
            continue
        normalized = re.sub(r"(\d+)\.(\d+)", r"\1,\2", num)
        if brand:
            terms.append(f"{brand} {normalized}")
            if quantity and any(unit in quantity.lower() for unit in ("l", "kg", "g", "ml", "cl")):
                unit = re.search(r"(kg|g|l|ml|cl)", quantity, re.IGNORECASE)
                if unit:
                    unit_value = unit.group(1).upper()
                    terms.append(f"{brand} {normalized} {unit_value}")
        else:
            terms.append(normalized)

    primary_keywords = descriptor.get("primary_keywords") or []
    for keyword in primary_keywords[:5]:
        prepared = _prepare_query(keyword, max_len)
        if prepared:
            terms.append(prepared)

    descriptor_name = normalize_space(descriptor.get("name"))
    if brand and descriptor_name:
        name_tokens = [tok for tok in descriptor_name.split() if tok.lower() not in {"au", "aux", "de", "du", "des"}]
        if len(name_tokens) >= 2:
            first = _prepare_query(f"{brand} {name_tokens[0]}", max_len)
            if first:
                terms.append(first)
            second = _prepare_query(f"{brand} {name_tokens[0]} {name_tokens[1]}", max_len)
            if second:
                terms.append(second)

    return [term for term in terms if isinstance(term, str) and term.strip()]


def build_query_terms() -> list[str]:
    """Return textual terms sorted by relevance."""
    terms: list[str] = []
    max_len = int(os.environ.get("MONOPRIX_MAX_QUERY_LEN", "30"))
    max_terms = int(os.environ.get("MONOPRIX_MAX_TERMS", "4"))
    descriptor = MANUAL_DESCRIPTOR.get(EAN) if EAN else {}
    if not isinstance(descriptor, dict):
        descriptor = {}
    seen: set[str] = set()

    def add(term: typing.Optional[str]) -> None:
        candidate = _enforce_two_keyword_term(term, descriptor, max_len)
        if not candidate:
            return
        # Normalize and add to seen set to avoid duplicates
        normalized_candidate = candidate.lower()
        if normalized_candidate in seen:
            return
        seen.add(normalized_candidate)
        terms.append(candidate)
        if max_terms > 0 and len(terms) >= max_terms:
            return

    # 1. Utiliser en priorité les primary_keywords (déjà issus des seeds)
    primary = descriptor.get("primary_keywords")
    if isinstance(primary, (list, tuple)):
        for item in primary:
            add(item)
            if max_terms > 0 and len(terms) >= max_terms:
                break

    # 2. Requêtes fournies via l'environnement (QUERY) ensuite
    if max_terms <= 0 or len(terms) < max_terms:
        if QUERY:
            add(QUERY)

    # 3. Autres champs du descriptor pour récupérer la fonction (seed/name/description)
    if max_terms <= 0 or len(terms) < max_terms:
        additional_entries: list[typing.Optional[str]] = [
            descriptor.get("seed_primary_name"),
            descriptor.get("seed_query"),
            descriptor.get("name"),
            descriptor.get("description"),
        ]
        for entry in additional_entries:
            if entry:
                add(entry)
                if max_terms > 0 and len(terms) >= max_terms:
                    break

    # 4. Fallback historique (quantités, variantes)
    if max_terms <= 0 or len(terms) < max_terms:
        for fallback in _monoprix_fallback_terms(descriptor, max_len):
            add(fallback)
            if max_terms > 0 and len(terms) >= max_terms:
                break

    # 5. Ultime recours : construire à partir du descriptor seul
    if not terms:
        add("")

    if max_terms > 0:
        return terms[:max_terms]
    return terms


def expected_tokens() -> tuple[list[str], list[str], list[str]]:
    descriptor = MANUAL_DESCRIPTOR.get(EAN) if EAN else None
    descriptor_tokens: list[str] = []
    number_tokens: list[str] = []
    brand_tokens: list[str] = []
    if isinstance(descriptor, dict):
        for key in ("brand", "name", "description", "quantity"):
            raw = descriptor.get(key)
            descriptor_tokens.extend(tokens_for(raw))
            number_tokens.extend(re.findall(r"\d+", raw or ""))
        brand_tokens = tokens_for(descriptor.get("brand"))
    descriptor_tokens = sorted(set(descriptor_tokens))
    number_tokens = sorted(set(number_tokens))
    brand_tokens = sorted(set(brand_tokens))
    return descriptor_tokens, number_tokens, brand_tokens


async def accept_cookies(page) -> None:
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Tout accepter')",
        "button:has-text(\"J'accepte\")",
        "button:has-text('Accepter')",
        "button:has-text('OK')",
    ]
    for sel in selectors:
        try:
            node = page.locator(sel).first
            if await node.count():
                await node.click()
                await page.wait_for_timeout(600)
                break
        except Exception:
            continue


async def ensure_store(page) -> None:
    target = STORE_URL or HOME_URL
    try:
        await page.goto(target, wait_until="domcontentloaded")
        await accept_cookies(page)
        await page.wait_for_timeout(800)
    except Exception:
        return


async def ensure_search_ready(page) -> bool:
    selectors = [
        "input[type='search']",
        "input[placeholder*='Recher']",
        "input[data-testid='search-input']",
        "form[role='search'] input",
    ]
    for sel in selectors:
        try:
            locator = page.locator(sel).first
            if await locator.count():
                await locator.click()
                await locator.fill("")
                return True
        except Exception:
            continue
    # try opening search drawer
    try:
        toggle = page.locator("button[aria-label*='cherche'], button[data-testid='open-search']").first
        if await toggle.count():
            await toggle.click()
            await page.wait_for_timeout(400)
            return await ensure_search_ready(page)
    except Exception:
        pass
    return False


async def capture_debug(page, name: str) -> None:
    if not DEBUG_MONOPRIX or not DEBUG_DUMP_ROOT:
        return

    sys.stderr.write(f"[DEBUG MONOPRIX CAPTURE] Attempting capture for '{name}'\n")
    sys.stderr.write(f"[DEBUG MONOPRIX CAPTURE] Root dump dir: {DEBUG_DUMP_ROOT}\n")
    
    try:
        # Utilise un identifiant de session pour regrouper les captures d'une même exécution
        session_id = os.environ.get("COPILOT_DEBUG_SESSION_ID")
        if not session_id:
            session_id = f"run-{EAN}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            os.environ["COPILOT_DEBUG_SESSION_ID"] = session_id

        dump_dir = Path(DEBUG_DUMP_ROOT) / session_id
        dump_dir.mkdir(parents=True, exist_ok=True)
        
        screenshot_path = dump_dir / f"{name}.png"
        html_path = dump_dir / f"{name}.html"
        
        sys.stderr.write(f"[DEBUG MONOPRIX CAPTURE] Screenshot path: {screenshot_path}\n")
        
        await page.screenshot(path=str(screenshot_path), full_page=True)
        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
        
        sys.stderr.write(f"[DEBUG MONOPRIX CAPTURE] Successfully captured '{name}' to {dump_dir}\n")

    except Exception as e:
        sys.stderr.write(f"[DEBUG MONOPRIX CAPTURE] FAILED to capture '{name}': {e}\n")
        # Ne pas masquer l'erreur pour voir la trace complète
        logging.exception("Monoprix debug capture failed")


async def extract_from_card(page, card, base_url: str) -> dict[str, typing.Optional[str]]:
    title = await read_text(card.locator("h2, h3, .product-card__title, .product-title, .product-card-name"))

    price = None
    for selector in (
        "[data-testid='price']",
        "[data-testid='product-price']",
        ".product-card__price",
        ".price",
        ".product-price",
    ):
        candidate = await read_text(card.locator(selector))
        if candidate:
            price = candidate
            break

    unit_price = None
    for selector in (
        "[data-testid='unit-price']",
        "[data-testid='product-unit-price']",
        ".product-card__unit-price",
        ".price-per-unit",
        ".product-price__unit",
    ):
        candidate = await read_text(card.locator(selector))
        if candidate:
            unit_price = candidate
            break

    quantity = None
    for selector in (
        ".product-card__details",
        ".product-card__description",
        ".product-card__subtitle",
        "[data-testid='product-card-description']",
    ):
        candidate = await read_text(card.locator(selector))
        if candidate:
            quantity = candidate
            break

    url = None
    image_url = None
    try:
        link = card.locator("a[href]").first
        if await link.count():
            href = await link.get_attribute("href")
            if href:
                url = urljoin(base_url, href)
    except Exception:
        url = None

    for selector in (
        "img[data-testid='product-card-image']",
        "img[class*='product']",
        "img",
    ):
        try:
            candidate = await card.locator(selector).first.get_attribute("src")
            if candidate:
                image_url = candidate
                break
        except Exception:
            continue

    return {
        "title": title,
        "price": price,
        "unit_price": unit_price,
        "quantity": quantity,
        "url": url,
        "image_url": image_url,
    }


async def open_product(page, url: str) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
    except Exception:
        raise


async def extract_from_pdp(page) -> dict[str, typing.Optional[str]]:
    data: dict[str, typing.Optional[str]] = {
        "title": None,
        "price": None,
        "unit_price": None,
        "quantity": None,
        "image_url": None,
    }

    data["title"] = await read_text(page.locator("h1"))

    for selector in ("[data-testid='product-price']", ".price", ".product-price__amount"):
        candidate = await read_text(page.locator(selector))
        if candidate:
            data["price"] = candidate
            break

    for selector in ("[data-testid='product-unit-price']", ".price-per-unit", ".product-price__unit"):
        candidate = await read_text(page.locator(selector))
        if candidate:
            data["unit_price"] = candidate
            break

    for selector in (".product-characteristics", "[data-testid='product-details']"):
        candidate = await read_text(page.locator(selector))
        if candidate:
            data["quantity"] = candidate
            break

    try:
        body_text = await page.inner_text("body")
    except Exception:
        body_text = ""

    if not data.get("price") and body_text:
        price_candidates = [c for c in re.findall(r"(\d+,\d{2})\s*€", body_text)
                             if c not in {"0,00", "60,00"}]
        numeric_candidates = [float(c.replace(',', '.')) for c in price_candidates]
        if numeric_candidates:
            best = min(numeric_candidates)
            data["price"] = f"{best:.2f}".replace('.', ',')

    if not data.get("unit_price") and body_text:
        match = re.search(r"(\d+,\d{2}\s*€\s*/\s*(?:kilo|kg|litre|l))", body_text, re.IGNORECASE)
        if match:
            data["unit_price"] = match.group(1).replace("kilo", "KG").replace("litre", "L")

    if not data.get("quantity") and body_text:
        match = re.search(r"(\d+[,\.]?\d*\s*(?:g|kg|ml|l))", body_text, re.IGNORECASE)
        if match:
            value = match.group(1).replace(',', '.').strip()
            value = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", value)
            value = value.lower()
            if value.endswith(' l'):
                value = value[:-2] + ' L'
            data["quantity"] = value

    image_url = None
    try:
        image_url = await page.locator("meta[property='og:image']").first.get_attribute("content")
    except Exception:
        image_url = None
    if not image_url:
        try:
            image_url = await page.locator("[data-testid='product-gallery'] img, img[src*='/products/']").first.get_attribute("src")
        except Exception:
            image_url = None
    data["image_url"] = image_url

    data["raw_text"] = body_text

    return data


async def find_best_product(page, context, base_url: str, terms: list[str]) -> typing.Optional[Result]:
    sys.stderr.write("[MONOPRIX_DEBUG] In new find_best_product (human simulation).\n")
    descriptor_entry = MANUAL_DESCRIPTOR.get(EAN, {}) if EAN else {}

    for i, term in enumerate(terms):
        sys.stderr.write(f"[MONOPRIX_DEBUG]  - Term {i+1}/{len(terms)}: '{term}'\n")
        
        try:
            # Naviguer vers la page d'accueil pour s'assurer que nous partons d'un état propre
            await page.goto(base_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            await accept_cookies(page)

            # Trouver et préparer le champ de recherche
            search_input = None
            search_selectors = [
                "input[type='search']",
                "input[placeholder*='Recher']",
                "input[data-testid='search-input']",
                "form[role='search'] input",
            ]
            for selector in search_selectors:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    search_input = locator
                    break
            
            if not search_input:
                # Essayer d'ouvrir le tiroir de recherche si le champ n'est pas visible
                toggle = page.locator("button[aria-label*='cherche'], button[data-testid='open-search']").first
                if await toggle.count():
                    sys.stderr.write("[MONOPRIX_DEBUG]  - Search input not visible, trying to click toggle.\n")
                    await toggle.click()
                    await page.wait_for_timeout(500)
                    # Retenter de trouver l'input
                    for selector in search_selectors:
                        locator = page.locator(selector).first
                        if await locator.count() > 0 and await locator.is_visible():
                            search_input = locator
                            break
            
            if not search_input:
                sys.stderr.write("[MONOPRIX_DEBUG]  - Could not find a visible search input.\n")
                await capture_debug(page, f"monoprix_search_input_not_found_{i}")
                continue

            # Simuler la saisie humaine et valider
            sys.stderr.write(f"[MONOPRIX_DEBUG]  - Typing '{term}' into search input.\n")
            await search_input.click()
            await search_input.fill("") # Vider le champ
            await search_input.press_sequentially(term, delay=100)
            await page.keyboard.press("Enter")
            
            sys.stderr.write(f"[MONOPRIX_DEBUG]  - Pressed Enter. Waiting for results page to load...\n")
            await page.wait_for_load_state("networkidle", timeout=7000)
            await page.wait_for_timeout(3000) # Attente pour le chargement des images

        except Exception as e:
            sys.stderr.write(f"[MONOPRIX_DEBUG]  - Search simulation failed: {e}\n")
            await capture_debug(page, f"monoprix_search_error_{i}")
            continue

        await capture_debug(page, f"monoprix_search_results_{i}")

        # Récupérer tous les liens de produits sur la page
        product_links = await page.locator("a[href*='/p/'], a[href*='/products/']").all()

        # Fallback : navigation directe vers la page de recherche si la simulation n'affiche rien
        if not product_links:
            fallback_url = urljoin(base_url, f"search?q={quote_plus(term)}")
            sys.stderr.write("[MONOPRIX_DEBUG]  - No product links after typing. Trying fallback URL: "
                             f"{fallback_url}\n")
            try:
                await page.goto(fallback_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000) # Attente pour le chargement des images
                await capture_debug(page, f"monoprix_search_results_fallback_{i}")
                product_links = await page.locator("a[href*='/p/'], a[href*='/products/']").all()
            except Exception as fallback_error:
                sys.stderr.write(f"[MONOPRIX_DEBUG]  - Fallback search navigation failed: {fallback_error}\n")
                product_links = []

        if not product_links:
            sys.stderr.write("[MONOPRIX_DEBUG]  - Still no product links found.\n")
            continue
            
        product_urls = []
        for link in product_links:
            href = await link.get_attribute("href")
            if href:
                full_url = urljoin(base_url, href)
                if full_url not in product_urls:
                    product_urls.append(full_url)

        sys.stderr.write(f"[MONOPRIX_DEBUG]  - Found {len(product_urls)} product URLs to check.\n")

        all_results = []
        for product_url in product_urls[:5]: # Limite aux 5 premiers pour la démo
            sys.stderr.write(f"[MONOPRIX_DEBUG]  - Parsing product page in new tab: {product_url}\n")
            new_page = await context.new_page()
            try:
                product_result = await parse_product_page(new_page, product_url, descriptor_entry)
                if product_result:
                    all_results.append(product_result)
            finally:
                await new_page.close()
                sys.stderr.write(f"[MONOPRIX_DEBUG]  - Closed tab for {product_url}\n")

        if not all_results:
            continue

        # Appliquer la logique de scoring et de correspondance d'image
        scored_results = []
        for res in all_results:
            score, plausible = calculate_score(res.title, descriptor_entry)
            sys.stderr.write(f"[MONOPRIX_DEBUG]  - Scoring '{res.title}': Initial Score={score}, Plausible={plausible}\n")

            # res.note contient l'URL de l'image
            image_match = await _image_matches_descriptor_async(descriptor_entry, res.note)
            if image_match:
                score += 50  # Bonus important pour la correspondance d'image
                plausible = True # Une correspondance d'image rend le produit plausible
                sys.stderr.write(f"[MONOPRIX_DEBUG]  - Image match FOUND for '{res.title}'. New score={score}\n")
            else:
                sys.stderr.write(f"[MONOPRIX_DEBUG]  - No image match for '{res.title}'.\n")

            if plausible:
                scored_results.append((score, res))
        
        if not scored_results:
            sys.stderr.write("[MONOPRIX_DEBUG]  - No plausible results after scoring and image matching.\n")
            continue

        scored_results.sort(key=lambda x: x[0], reverse=True)
        best_score, best_result = scored_results[0]
        
        sys.stderr.write(f"[MONOPRIX_DEBUG] Best match: '{best_result.title}' (Score: {best_score})\n")
        best_result.status = "OK"
        return best_result

    return Result(status="NO_RESULTS")


async def parse_product_page(
    page: Page,
    url: str,
    descriptor: typing.Optional[dict[str, typing.Any]] = None,
) -> typing.Optional[Result]:
    """Analyse une page de détail produit pour en extraire les informations."""
    descriptor = descriptor or {}
    try:
        await page.goto(url, wait_until="networkidle")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000) # Attendre le chargement après scroll
        await capture_debug(page, f"monoprix_product_page_{page.url.split('/')[-1]}")

        title_locator = page.locator("h1[data-testid='pdp-title']")
        title = await read_text(title_locator)
        if not title:
            # Fallback pour d'autres structures possibles
            title_locator = page.locator("h1")
            title = await read_text(title_locator)

        if not title:
            sys.stderr.write(f"[MONOPRIX_DEBUG] No title found on page {url}\n")
            return None

        price_locator = page.locator("[data-testid='pdp-price'], .pdp-price__amount").first
        price = await read_text(price_locator)

        unit_price_locator = page.locator("[data-testid='pdp-unit-price'], .pdp-price__unit-price").first
        unit_price = await read_text(unit_price_locator)
        quantity = None

        json_ld_offer = await _extract_offer_from_json_ld(page)
        json_price = json_ld_offer.get("price") if json_ld_offer else None
        json_size = json_ld_offer.get("size") if json_ld_offer else None
        if not title and json_ld_offer and json_ld_offer.get("name"):
            title = json_ld_offer["name"]
        if not price and json_price:
            price_candidate = _format_price_value(json_price)
            if price_candidate:
                price = price_candidate

        descriptor_quantity = descriptor.get("quantity") or descriptor.get("seed_primary_quantity")
        if descriptor_quantity:
            normalized_descriptor_quantity = _normalize_quantity_text(descriptor_quantity)
            quantity = normalized_descriptor_quantity or descriptor_quantity
        elif json_size:
            normalized_size = _normalize_quantity_text(json_size)
            if normalized_size:
                quantity = normalized_size
            else:
                quantity = json_size

        if not unit_price:
            base_quantity = quantity or json_size or descriptor_quantity
            unit_price_candidate = _compute_unit_price(json_price or price, base_quantity)
            if unit_price_candidate:
                unit_price = unit_price_candidate

        # Cherche l'image principale du produit en priorité dans les métadonnées
        image_url = None
        try:
            # Sélecteur plus fiable via les métadonnées Open Graph
            img_locator = page.locator("meta[property='og:image']").first
            if await img_locator.count() > 0:
                image_url = await img_locator.get_attribute("content")
        except Exception:
            image_url = None

        # Fallback sur les sélecteurs d'images visibles si les métadonnées échouent
        if not image_url:
            try:
                img_locator = page.locator("img[data-testid='main-product-image'], .main-image img, [data-testid*='gallery'] img").first
                if await img_locator.count() > 0:
                    image_url = await img_locator.get_attribute("src")
            except Exception:
                pass # L'image reste None si tout échoue

        sys.stderr.write(f"[MONOPRIX_DEBUG] Extracted image URL: {image_url}\n")

        return Result(
            status="OK_PARTIAL",
            title=title,
            price=price,
            unit_price=unit_price,
            quantity=quantity,
            url=page.url,
            note=image_url # Stocke l'URL de l'image dans la note pour vérification
        )
    except Exception as e:
        sys.stderr.write(f"[MONOPRIX_DEBUG] Error parsing product page {url}: {e}\n")
        return None


def calculate_score(title: typing.Optional[str], descriptor: dict) -> tuple[int, bool]:
    """Calcule un score de pertinence pour le titre donné par rapport au descripteur."""
    if not title:
        return 0, False
    title_lower = title.lower()
    score = 0
    plausible = False
    brand_match = False
    
    # Bonus si le nom de la marque est présent
    brand = descriptor.get("brand", "").lower()
    if brand and brand in title_lower:
        score += 10
        brand_match = True

    # Bonus si la quantité est mentionnée
    quantity = descriptor.get("quantity") or descriptor.get("seed_primary_quantity")
    if quantity:
        # Recherche de la quantité exacte, en normalisant les espaces
        quantity_str = str(quantity).replace(" ", "").lower()
        title_nospace = title_lower.replace(" ", "")
        if re.search(r"\b" + re.escape(quantity_str) + r"\b", title_nospace):
            score += 5

    # Bonus pour chaque mot-clé principal trouvé dans le titre
    primary_keywords = descriptor.get("primary_keywords", [])
    keyword_match_count = 0
    for keyword in primary_keywords:
        if keyword and keyword.lower() in title_lower:
            score += 20  # Bonus plus important pour les mots-clés
            keyword_match_count += 1
    
    # Un produit est plausible s'il correspond à la marque ET à au moins un mot-clé
    # ou s'il correspond à plusieurs mots-clés.
    plausible = (brand_match and keyword_match_count > 0) or keyword_match_count > 1

    # Pénalité si le titre contient des mots-clés bannis
    if _has_banned_keyword(title_lower):
        score -= 15
    
    sys.stderr.write(f"[MONOPRIX_DEBUG][SCORE] - Title: '{title}' | Brand: '{brand}' | Brand Match: {brand_match} | Keywords Matched: {keyword_match_count} | Score: {score} | Plausible: {plausible}\n")

    return score, plausible


async def run() -> Result:
    sys.stderr.write("[MONOPRIX_DEBUG] Starting run() function\n")
    if os.environ.get("USE_CDP") != "1":
        sys.stderr.write("[MONOPRIX_DEBUG] ERROR: USE_CDP=1 is not set\n")
        return Result(status="ERROR", note="USE_CDP=1 obligatoire pour Monoprix")

    terms = build_query_terms()
    if not terms:
        sys.stderr.write("[MONOPRIX_DEBUG] NO_QUERY: build_query_terms() returned no terms\n")
        return Result(status="NO_QUERY")
    sys.stderr.write(f"[MONOPRIX_DEBUG] Search terms: {terms}\n")

    descriptor_entry = MANUAL_DESCRIPTOR.get(EAN) if EAN else None
    if not descriptor_entry:
        sys.stderr.write(f"[MONOPRIX_DEBUG] ERROR: EAN '{EAN}' not found in manual_descriptors.json. Scoring will fail.\n")
        # Optionnel : on peut décider de s'arrêter ici si le descripteur est essentiel
        # return Result(status="ERROR", note=f"EAN {EAN} not in descriptors")
    else:
        sys.stderr.write(f"[MONOPRIX_DEBUG] Successfully loaded descriptor for EAN '{EAN}'.\n")

    storage_state = state_path_for("monoprix")
    sys.stderr.write(f"[MONOPRIX_DEBUG] Using storage state: {storage_state}\n")
    
    p, browser, context, page = await make_context(
        headless=HEADLESS,
        proxy=PROXY,
        storage_state_path=storage_state,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    )
    sys.stderr.write("[MONOPRIX_DEBUG] make_context() successful\n")
    
    # async def _close_extra(new_page):
    #     try:
    #         await new_page.close()
    #     except Exception:
    #         pass

    # context.on("page", lambda page_obj: asyncio.create_task(_close_extra(page_obj)))

    try:
        sys.stderr.write("[MONOPRIX_DEBUG] Calling ensure_store()\n")
        await ensure_store(page)
        sys.stderr.write("[MONOPRIX_DEBUG] ensure_store() finished\n")
        
        sys.stderr.write("[MONOPRIX_DEBUG] Calling find_best_product()\n")
        result = await find_best_product(page, context, HOME_URL, terms)
        sys.stderr.write(f"[MONOPRIX_DEBUG] find_best_product() returned: {result}\n")
        
        if result:
            return result
        return Result(status="NO_RESULTS")
    finally:
        sys.stderr.write("[MONOPRIX_DEBUG] Closing browser\n")
        try:
            await browser.close()
        except Exception:
            pass
        await p.stop()


async def _main() -> None:
    result = await run()
    print(json.dumps(result.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        sys.exit(1)
