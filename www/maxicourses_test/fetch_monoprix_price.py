#!/usr/bin/env python3
"""Fetcher Monoprix (texte uniquement) respectant le mandat de collecte."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
import unicodedata
import typing
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, quote
import logging
from playwright.async_api import Page, BrowserContext

print("--- DÉBUT DE L'EXÉCUTION DE FETCH_MONOPRIX_PRICE ---", file=sys.stderr)

from rich import print
import requests
from pipeline.image_matching import descriptor_matches_candidate

try:  # Pillow est optionnel mais requis pour le matching visuel
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for  # noqa: E402
from collection_mandate import get_method  # noqa: E402
from descriptor_store import all_descriptors  # noqa: E402
try:
    from pipeline.finder import MonoprixAdapter  # type: ignore
except Exception:  # pragma: no cover - provider optional
    MonoprixAdapter = None  # type: ignore


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


def _parse_finder_keywords() -> list[str]:
    raw = os.environ.get("FINDER_KEYWORDS")
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            result: list[str] = []
            for item in data:
                if isinstance(item, str):
                    cleaned = item.strip()
                    if cleaned:
                        result.append(cleaned)
            return result
    except json.JSONDecodeError:
        pass
    return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]


FINDER_KEYWORDS = _parse_finder_keywords()


def _looks_like_ean(term: typing.Optional[str]) -> bool:
    if not term:
        return False
    cleaned = "".join(ch for ch in term if ch.isdigit())
    if not cleaned:
        return False
    return cleaned == term.replace(" ", "") and 8 <= len(cleaned) <= 14

# Mots-clés pour détecter les cartes où le produit n'est pas disponible
CARD_BANNED_KEYWORDS = {
    "la carte n'est pas acceptée",
    "la carte n'est pas acceptée",
}

# Variants normalisés pour le verrou "variant_lock"
VARIANT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "nature": [
        re.compile(r"\bnature\b", re.IGNORECASE),
        re.compile(r"sans\s+sucres?", re.IGNORECASE),
        re.compile(r"\boriginal\b", re.IGNORECASE),
    ],
    "fraise": [re.compile(r"\bfraises?\b", re.IGNORECASE)],
    "framboise": [re.compile(r"\bframboises?\b", re.IGNORECASE)],
    "vanille": [re.compile(r"\bvanill?e\b", re.IGNORECASE)],
    "amande": [re.compile(r"\bamandes?\b", re.IGNORECASE)],
    "coco": [re.compile(r"\bnoix\s+de\s+coco\b", re.IGNORECASE), re.compile(r"\bcoco\b", re.IGNORECASE)],
    "mangue": [re.compile(r"\bmangues?\b", re.IGNORECASE)],
    "chocolat": [re.compile(r"\bchocolat\b", re.IGNORECASE)],
    "orange": [re.compile(r"\borange\b", re.IGNORECASE)],
    "sans sucre": [
        re.compile(r"\bsans\s+sucres?\b", re.IGNORECASE),
        re.compile(r"\bzero\b", re.IGNORECASE),
        re.compile(r"\bz[eé]ro\b", re.IGNORECASE),
    ],
    "rouge": [
        re.compile(r"\brouge\b", re.IGNORECASE),
        re.compile(r"\bsanguine\b", re.IGNORECASE),
    ],
}

SEED_VARIANTS = ["nature", "vanille", "amande", "coco", "mangue", "chocolat", "orange", "sans sucre", "rouge"]
MAX_PRODUCTS_PER_TERM = int(os.environ.get("MONOPRIX_MAX_PRODUCTS", "12"))
DESCRIPTOR_MATCH_COVERAGE = float(os.environ.get("MONOPRIX_DESCRIPTOR_COVERAGE", "0.7"))


def _ahash_js() -> str:
    return """
    async (imgUrl) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      const loaded = new Promise((res, rej) => {
        img.onload = () => res();
        img.onerror = (e) => rej(e);
      });
      img.src = imgUrl;
      await loaded;

      const size = 8;
      const canvas = document.createElement('canvas');
      canvas.width = size; canvas.height = size;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, size, size);
      const data = ctx.getImageData(0, 0, size, size).data;

      const gray = [];
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i], g = data[i+1], b = data[i+2];
        const y = Math.round(0.299*r + 0.587*g + 0.114*b);
        gray.push(y);
      }
      const avg = gray.reduce((a,b)=>a+b,0) / gray.length;

      let hash = 0n;
      for (let i = 0; i < gray.length; i++) {
        hash = (hash << 1n) | (gray[i] >= avg ? 1n : 0n);
      }
      return hash.toString();
    }
    """


def _hamming64(a: int, b: int) -> int:
    x = a ^ b
    count = 0
    while x:
        x &= x - 1
        count += 1
    return count


async def _compute_ahash(ctx: BrowserContext, url: Optional[str]) -> Optional[int]:
    if not url:
        return None
    page = await ctx.new_page()
    try:
        await page.goto("about:blank")
        script = _ahash_js()
        h_str = await page.evaluate(
            f"""async (targetUrl) => {{
                const fn = {script};
                return await fn(targetUrl);
            }}""",
            url,
        )
        return int(h_str) if h_str is not None else None
    except Exception:
        return None
    finally:
        await page.close()


async def _compare_images_async(ctx: BrowserContext, seed_url: Optional[str], cand_url: Optional[str]) -> bool:
    a = await _compute_ahash(ctx, seed_url)
    b = await _compute_ahash(ctx, cand_url)
    if a is None or b is None:
        return False
    return _hamming64(a, b) <= 8


def compare_images_via_playwright(ctx: BrowserContext, seed_url: Optional[str], cand_url: Optional[str]) -> bool:
    async def _runner() -> bool:
        return await _compare_images_async(ctx, seed_url, cand_url)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return False
    try:
        return asyncio.run(_runner())
    except RuntimeError:
        return False


def inject_monoprix_image_provider(ctx: BrowserContext) -> None:
    if MonoprixAdapter is None:
        return
    MonoprixAdapter._image_provider = lambda seed, cand: compare_images_via_playwright(ctx, seed, cand)

# --- Patterns Regex ---
MULTIPLIER_PATTERN = re.compile(r"\b\d+\s*(?:x|×)\s*\d+\b", flags=re.IGNORECASE)
SIZE_TOKEN_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)[\s]*(ml|cl|l|kg|g)\b", flags=re.IGNORECASE)

VALIDATION_STOPWORDS = {
    "dessert",
    "desserts",
    "vegetal",
    "végétal",
    "produit",
    "produits",
    "soja",
    "lait",
    "naturel",
    "nature",
    "avec",
    "sans",
    "gourmand",
    "format",
    "brasse",
    "brassé",
    "aromates",
    "amorates",
    "epices",
    "épices",
    "aux",
    "multi",
    "usages",
    "flacon",
}

MONOPRIX_PRODUCT_TOKENS = {
    "yaourt",
    "yaourts",
    "dessert",
    "desserts",
    "boire",
    "boisson",
    "boissons",
    "proteine",
    "proteines",
    "protéine",
    "protéines",
    "protéiné",
    "protéinés",
}


def _seed_search_tokens(descriptor: dict[str, typing.Any]) -> list[str]:
    tokens: dict[str, str] = {}

    def add_token(token: str) -> None:
        token = token.strip()
        if not token:
            return
        normalized = _normalize_search_text(token)
        if (
            normalized
            and normalized not in VALIDATION_STOPWORDS
            and not normalized.isdigit()
            and len(normalized) >= 3
        ):
            tokens.setdefault(normalized, token)

    sources: list[typing.Any] = [
        descriptor.get("seed_primary_name"),
        descriptor.get("seed_query"),
        descriptor.get("name"),
        descriptor.get("description"),
    ]

    for value in sources:
        if isinstance(value, str):
            for token in _tokenize_preserve_case(value):
                add_token(token)

    return list(tokens.values())
# Manual descriptor cache (hardcoded catalog)
MANUAL_DESCRIPTOR: dict[str, dict] = all_descriptors()


@dataclass
class Result:
    status: str
    price: typing.Optional[str] = None
    title: typing.Optional[str] = None
    url: typing.Optional[str] = None
    note: typing.Optional[str] = None
    image: typing.Optional[str] = None
    matched_ean: typing.Optional[str] = None
    unit_price: typing.Optional[str] = None
    quantity: typing.Optional[str] = None
    store: typing.Optional[str] = None
    raw_text: typing.Optional[str] = None
    extras: typing.Optional[dict[str, typing.Any]] = None
    candidates: typing.Optional[list] = None


def tokens_for(value: typing.Optional[str]) -> list[str]:
    if not isinstance(value, str):
        return []
    return [tok for tok in re.findall(r"[0-9a-zà-öø-ÿ]+", value.lower()) if len(tok) >= 3]


def normalize_space(value: typing.Optional[str]) -> typing.Optional[str]:
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip()


def _descriptor_validation_tokens(descriptor: dict[str, typing.Any]) -> list[str]:
    tokens: set[str] = set()

    def collect(source: typing.Optional[str]) -> None:
        if not isinstance(source, str):
            return
        for tok in tokens_for(source):
            normalized = _normalize_search_text(tok)
            if (
                normalized
                and normalized not in VALIDATION_STOPWORDS
                and len(normalized) >= 3
            ):
                tokens.add(normalized)

    collect(descriptor.get("brand"))
    collect(descriptor.get("variant"))
    collect(descriptor.get("seed_primary_name"))
    collect(descriptor.get("name"))
    collect(descriptor.get("seed_query"))
    collect(descriptor.get("description"))

    canonical = descriptor.get("canonical")
    if isinstance(canonical, dict):
        collect(canonical.get("brand"))
        collect(canonical.get("line"))
        collect(canonical.get("name_core"))
        signature = canonical.get("normalized_signature")
        if isinstance(signature, str):
            collect(signature)
        for feature in canonical.get("features") or []:
            collect(feature)

    size_token = _preferred_size_token(descriptor)
    if size_token:
        tokens.add(_normalize_search_text(size_token))

    return sorted(tokens)


def _descriptor_core_tokens(descriptor: dict[str, typing.Any]) -> set[str]:
    core: set[str] = set()

    def collect(source: typing.Optional[str]) -> None:
        if not isinstance(source, str):
            return
        for tok in tokens_for(source):
            normalized = _normalize_search_text(tok)
            if normalized and normalized not in VALIDATION_STOPWORDS:
                core.add(normalized)

    for field in ("brand", "seed_primary_name", "name", "seed_query"):
        collect(descriptor.get(field))

    quantity_token = _preferred_size_token(descriptor)
    if quantity_token:
        normalized_quantity = _normalize_search_text(quantity_token)
        if normalized_quantity:
            core.add(normalized_quantity)
            core.add(normalized_quantity.replace(" ", ""))

    return core


def _normalize_search_text(value: typing.Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value.lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def detect_variant_from_text(text: typing.Optional[str]) -> typing.Optional[str]:
    normalized = _normalize_search_text(text)
    if not normalized:
        return None
    hits: list[str] = []
    for variant, patterns in VARIANT_PATTERNS.items():
        if any(pattern.search(normalized) for pattern in patterns):
            hits.append(variant)
    if "nature" in hits and len(hits) > 1:
        hits = [variant for variant in hits if variant != "nature"]
    return hits[0] if hits else None


def _seed_variant_from_descriptor(descriptor: dict[str, typing.Any]) -> typing.Optional[str]:
    canonical = descriptor.get("canonical") if isinstance(descriptor.get("canonical"), dict) else {}
    for key in ("variant_norm", "variant"):
        candidate = canonical.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    flavor = canonical.get("flavor_color")
    if isinstance(flavor, str) and flavor.strip():
        return flavor.strip().lower()
    descriptor_variant = descriptor.get("variant")
    if isinstance(descriptor_variant, str) and descriptor_variant.strip():
        return descriptor_variant.strip().lower()
    return None


def seed_variant_negatives(seed_variant: typing.Optional[str]) -> list[str]:
    variant = (seed_variant or "").strip().lower()
    if not variant:
        return []
    negatives: list[str] = []
    for token in SEED_VARIANTS:
        if token == variant:
            continue
        if token == "nature" and variant != "nature":
            # ne pas bloquer les combinaisons "nature + <variant>" (ex. nature aux amandes)
            continue
        if token not in negatives:
            negatives.append(token)
    if variant == "orange":
        negatives.extend(["sans sucre", "sans sucres", "zero", "zéro", "rouge", "sanguine"])
    elif variant in {"sans sucre", "zero", "zéro"}:
        negatives.extend(["orange", "original"])
    return list(dict.fromkeys(negatives))


def _extract_category_tokens(descriptor: dict[str, typing.Any]) -> list[str]:
    categories = descriptor.get("categories")
    if not isinstance(categories, str):
        return []
    tokens: list[str] = []
    for chunk in categories.split(","):
        for token in re.findall(r"[a-zA-ZÀ-ÖØ-öø-ÿ']+", chunk.lower()):
            if len(token) >= 4 and token not in tokens:
                tokens.append(token)
    return tokens


def _collect_monoprix_negatives(descriptor: dict[str, typing.Any], seed_variant: typing.Optional[str]) -> list[str]:
    negatives: list[str] = []
    neg_map = descriptor.get("negatives")
    if isinstance(neg_map, dict):
        store_tokens = neg_map.get("monoprix") or []
        for token in store_tokens:
            if isinstance(token, str) and token.strip():
                negatives.append(token.strip().lower())
    negatives.extend(seed_variant_negatives(seed_variant))

    descriptor_tokens = set(_descriptor_validation_tokens(descriptor))
    allow_packaging = descriptor.get("allow_monoprix_squeeze")
    if not allow_packaging:
        packaging_bans = {"squeeze", "squeez"}
        for token in packaging_bans:
            if token not in descriptor_tokens:
                negatives.append(token)

    return list(dict.fromkeys(negatives))


def _unit_family_for_unit(unit: str) -> str:
    unit_lower = unit.lower()
    if unit_lower in {"ml", "cl", "dl", "l"}:
        return "volume"
    if unit_lower in {"g", "kg"}:
        return "mass"
    return "count"


def _candidate_quantity(result: Result) -> typing.Optional[tuple[Decimal, str]]:
    sources: list[typing.Optional[str]] = [result.quantity, result.raw_text]
    for source in sources:
        if not isinstance(source, str):
            continue
        normalized = _normalize_quantity_text(source)
        candidate = normalized or source
        parsed = _parse_quantity_to_base(candidate)
        if parsed:
            return parsed
    return None


def _select_quantity_from_candidates(
    candidates: typing.Iterable[typing.Optional[str]],
) -> typing.Optional[str]:
    """Choisit la quantité la plus pertinente parmi plusieurs sources."""
    best_candidate: typing.Optional[str] = None
    best_value: typing.Optional[float] = None

    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        normalized = _normalize_quantity_text(candidate)
        if not normalized:
            continue
        parsed = _parse_quantity_to_base(normalized)
        if parsed:
            amount, _ = parsed
            try:
                value = float(amount)
            except (TypeError, ValueError):
                value = None
            if value is None:
                if best_candidate is None:
                    best_candidate = normalized
                continue
            if best_value is None or value > best_value:
                best_value = value
                best_candidate = normalized
        elif best_candidate is None:
            best_candidate = normalized

    return best_candidate


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
    canonical = descriptor.get("canonical")
    if isinstance(canonical, dict):
        for image_url in canonical.get("images") or []:
            candidates.append(image_url)
    for extra_key in ("reference_image", "reference_images"):
        extra_value = descriptor.get(extra_key)
        if isinstance(extra_value, str):
            candidates.append(extra_value)
        elif isinstance(extra_value, list):
            candidates.extend(extra_value)
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


def _format_size_token(value: typing.Union[int, float, Decimal, str], unit: typing.Optional[str]) -> typing.Optional[str]:
    if value is None or unit is None:
        return None
    try:
        numeric = Decimal(str(value))
    except InvalidOperation:
        return None
    normalized = format(numeric.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    normalized = normalized.replace(",", ".")
    unit_clean = unit.strip().upper()
    if not unit_clean:
        return None
    return f"{normalized}{unit_clean}"


def _size_token_from_text(value: typing.Optional[str]) -> typing.Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.replace("·", " ")
    match = SIZE_TOKEN_PATTERN.search(cleaned)
    if not match:
        return None
    number = match.group(1).replace(",", ".")
    unit = match.group(2)
    try:
        numeric = Decimal(number)
    except InvalidOperation:
        return None
    return _format_size_token(numeric, unit)


def _preferred_size_token(descriptor: dict[str, typing.Any]) -> typing.Optional[str]:
    if not isinstance(descriptor, dict):
        return None
    for field in (
        "seed_primary_quantity",
        "quantity",
        "seed_query",
        "seed_primary_name",
        "name",
        "description",
    ):
        token = _size_token_from_text(descriptor.get(field))
        if token:
            return token
    canonical = descriptor.get("canonical")
    if isinstance(canonical, dict):
        size_value = canonical.get("size_value")
        size_unit = canonical.get("size_unit")
        token = _format_size_token(size_value, size_unit)
        if token:
            return token
    return None


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


def _compare_image_with_descriptor(descriptor: dict[str, typing.Any], image_url: typing.Optional[str], *, threshold: int = 16) -> bool:
    current_ean = descriptor.get("ean") or EAN
    cleaned = _sanitize_url(image_url)
    if not cleaned:
        return False
    return descriptor_matches_candidate(descriptor, cleaned, ean=current_ean, threshold=threshold)


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
    candidate = re.sub(r"(\d),(\d{1,2})([a-zA-Z])", r"\1,\2\3", candidate)
    candidate = candidate.replace(" l", " L").replace(" ml", " ML").replace(" cl", " CL")

    # Tronque si nécessaire
    if len(candidate) > max_len:
        candidate = candidate[:max_len].rstrip()
        
    return candidate if candidate else None


def _sanitize_url(value: typing.Optional[str]) -> typing.Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", "", value.strip())
    return cleaned or None


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
    "boisson",
    "boissons",
    "soda",
    "sodas",
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
    size_token = _preferred_size_token(descriptor)
    function_token = _select_function_token(tokens, descriptor, brand_token.lower())
    if not function_token:
        function_token = _select_function_token([], descriptor, brand_token.lower())
    if size_token:
        return f"{brand_token} {size_token}"
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

    for keyword in FINDER_KEYWORDS[:5]:
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


def _preferred_monoprix_terms(descriptor: dict[str, typing.Any], max_len: int) -> list[str]:
    preferred: list[str] = []
    brand = normalize_space(descriptor.get("brand"))
    if not brand:
        return preferred

    brand_normalized = _normalize_search_text(brand)

    def push(term: typing.Optional[str]) -> None:
        prepared = _prepare_query(term, max_len)
        if not prepared:
            return
        lowered = prepared.lower()
        for existing in preferred:
            if existing.lower() == lowered:
                return
        preferred.append(prepared)

    variant_sources: list[str] = []
    canonical = descriptor.get("canonical")
    if isinstance(canonical, dict):
        for key in ("variant", "variant_norm", "flavor", "flavor_color"):
            value = canonical.get(key)
            if isinstance(value, str):
                variant_sources.append(value)
    for key in ("variant", "seed_variant", "flavor"):
        value = descriptor.get(key)
        if isinstance(value, str):
            variant_sources.append(value)
    variant_phrase = ""
    for candidate in variant_sources:
        cleaned = normalize_space(candidate)
        if cleaned:
            variant_phrase = cleaned
            break

    variant_tokens: list[str] = []
    seen_variant_tokens: set[str] = set()
    for source in variant_sources:
        for token in _tokenize_preserve_case(source):
            normalized = _normalize_search_text(token)
            if (
                not normalized
                or len(normalized) < 3
                or normalized == brand_normalized
                or normalized in seen_variant_tokens
                or normalized in VALIDATION_STOPWORDS
                or normalized in MONOPRIX_PRODUCT_TOKENS
                or any(ch.isdigit() for ch in normalized)
            ):
                continue
            seen_variant_tokens.add(normalized)
            variant_tokens.append(token)

    if variant_phrase and _normalize_search_text(variant_phrase) != brand_normalized:
        push(f"{brand} {variant_phrase}")
    if len(variant_tokens) >= 2:
        combined = " ".join(variant_tokens[:2])
        if combined:
            push(f"{brand} {combined}")
    for token in variant_tokens:
        push(f"{brand} {token}")

    product_tokens: list[str] = []
    seen_product_tokens: set[str] = set()
    product_sources: list[typing.Any] = [
        descriptor.get("seed_primary_name"),
        descriptor.get("seed_query"),
        descriptor.get("name"),
        descriptor.get("description"),
    ]
    for source in product_sources:
        if isinstance(source, str):
            for token in tokens_for(source):
                normalized = _normalize_search_text(token)
                if (
                    normalized
                    and normalized in MONOPRIX_PRODUCT_TOKENS
                    and normalized not in seen_product_tokens
                ):
                    seen_product_tokens.add(normalized)
                    product_tokens.append(token)

    for token in product_tokens[:2]:
        push(f"{brand} {token}")

    if variant_tokens and product_tokens:
        push(f"{brand} {variant_tokens[0]} {product_tokens[0]}")

    return preferred


def _prioritize_monoprix_terms(
    descriptor: dict[str, typing.Any],
    candidate_terms: list[str],
    max_len: int,
    max_terms: int,
) -> list[str]:
    prioritized: list[str] = []
    seen: set[str] = set()

    def push(term: typing.Optional[str]) -> None:
        prepared = _prepare_query(term, max_len)
        if not prepared:
            return
        lowered = prepared.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        prioritized.append(prepared)

    for term in _preferred_monoprix_terms(descriptor, max_len):
        push(term)
        if max_terms > 0 and len(prioritized) >= max_terms:
            return prioritized[:max_terms]

    for term in candidate_terms:
        push(term)
        if max_terms > 0 and len(prioritized) >= max_terms:
            return prioritized[:max_terms]

    if max_terms > 0:
        return prioritized[:max_terms]
    return prioritized


def _descriptor_function_token(descriptor: dict) -> typing.Optional[str]:
    brand = descriptor.get("brand")
    brand_lower = brand.lower() if isinstance(brand, str) else ""
    for field in (
        descriptor.get("seed_primary_name"),
        descriptor.get("name"),
        descriptor.get("description"),
        descriptor.get("seed_query"),
    ):
        if not isinstance(field, str):
            continue
        for token in WORD_PATTERN.findall(field):
            lowered = token.lower()
            if len(lowered) < 3:
                continue
            if lowered in MONOPRIX_GENERIC_STOPWORDS:
                continue
            if lowered in MONOPRIX_UNIT_TOKENS:
                continue
            if brand_lower and lowered == brand_lower:
                continue
            return token
    return None


def build_query_terms() -> list[str]:
    """Return textual terms sorted by relevance (Finder first, minimal fallbacks)."""
    terms: list[str] = []
    max_len = int(os.environ.get("MONOPRIX_MAX_QUERY_LEN", "30"))
    max_terms = int(os.environ.get("MONOPRIX_MAX_TERMS", "12"))
    descriptor = MANUAL_DESCRIPTOR.get(EAN) if EAN else {}
    if not isinstance(descriptor, dict):
        descriptor = {}
    seen: set[str] = set()

    def primary_tokens_from_descriptor(data: dict[str, typing.Any]) -> list[str]:
        raw_fields: list[str] = []
        for key in ("brand", "seed_primary_name", "name", "description"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                raw_fields.append(value)
        tokens: list[str] = []
        for field in raw_fields:
            for chunk in field.split():
                normalized = _normalize_search_text(chunk)
                if not normalized:
                    continue
                if any(ch.isdigit() for ch in normalized):
                    continue
                if normalized in MONOPRIX_UNIT_TOKENS:
                    continue
                if normalized in MONOPRIX_GENERIC_STOPWORDS:
                    continue
                if normalized not in tokens:
                    tokens.append(normalized)
        return tokens

    def add(term: typing.Optional[str]) -> None:
        candidate = _prepare_query(term, max_len)
        if not candidate:
            return
        if _looks_like_ean(candidate):
            return
        normalized_candidate = candidate.lower()
        if normalized_candidate in seen:
            return
        seen.add(normalized_candidate)
        terms.append(candidate)
        if max_terms > 0 and len(terms) >= max_terms:
            return

    primary_tokens = primary_tokens_from_descriptor(descriptor)
    if len(primary_tokens) >= 2:
        add(" ".join(primary_tokens[:2]))
        if len(primary_tokens) >= 3:
            add(" ".join(primary_tokens[:3]))

    for keyword in FINDER_KEYWORDS:
        add(keyword)

    # 1. Finder-provided term from the environment (primary source)
    if QUERY:
        add(QUERY)

    # 2. Minimal fallback built from descriptor (brand + function)
    if max_terms <= 0 or len(terms) < max_terms:
        brand = normalize_space(descriptor.get("brand"))
        function_token = _descriptor_function_token(descriptor) or ""
        if brand and function_token:
            add(f"{brand} {function_token}")
        elif brand:
            add(brand)
        elif function_token:
            add(function_token)

    # 3. Seed query trimmed to the first two words as an additional fallback
    if max_terms <= 0 or len(terms) < max_terms:
        seed_query = descriptor.get("seed_query")
        if isinstance(seed_query, str) and seed_query.strip():
            trimmed = " ".join(seed_query.split()[:2])
            add(trimmed)

    # 4. Final fallback: EAN search
    if max_terms <= 0 or len(terms) < max_terms:
        if EAN:
            add(EAN)

    return terms[:max_terms] if max_terms > 0 else terms


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
    seed_variant = _seed_variant_from_descriptor(descriptor_entry)
    category_tokens = _extract_category_tokens(descriptor_entry)
    dynamic_negatives = _collect_monoprix_negatives(descriptor_entry, seed_variant)
    sys.stderr.write(
        f"[MONOPRIX_DEBUG] Seed variant: {seed_variant} | dynamic negatives: {dynamic_negatives}\n"
    )

    candidate_records: list[dict[str, typing.Any]] = []
    candidate_index: dict[str, dict] = {}

    def _enrich_candidate_entry(
        entry: dict[str, typing.Any],
        product_result: Result,
        score_value: typing.Union[int, float],
        extras: dict[str, typing.Any],
    ) -> None:
        entry["status"] = product_result.status or entry.get("status") or "CHECKED"
        entry["score"] = float(score_value)
        product_block = entry.get("product")
        if not isinstance(product_block, dict):
            product_block = {}
            entry["product"] = product_block

        def _set(field: str, value: typing.Optional[str]) -> None:
            if value:
                product_block[field] = value

        _set("title", product_result.title)
        _set("brand", product_block.get("brand") or descriptor_entry.get("brand"))
        _set("kind", product_block.get("kind") or descriptor_entry.get("seed_primary_name") or descriptor_entry.get("name"))
        _set("qty", product_result.quantity or product_block.get("qty") or descriptor_entry.get("quantity") or descriptor_entry.get("seed_primary_quantity"))
        image_value = product_result.note or product_result.image or product_block.get("image_url")
        if image_value:
            clean_image = _sanitize_url(image_value)
            if clean_image:
                product_block["image_url"] = clean_image
        _set("raw_text", product_result.raw_text or product_block.get("raw_text"))
        _set("unit_price", product_result.unit_price)
        _set("price", product_result.price)
        if product_result.matched_ean:
            product_block["ean"] = product_result.matched_ean
        entry.setdefault("extras", {}).update(extras or {})

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
            fallback_url = urljoin(base_url, f"search?q={quote(term, safe='')}")
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
            
        product_urls: list[str] = []
        filtered_urls: list[str] = []

        descriptor_brand_norm = _normalize_search_text(descriptor_entry.get("brand")) if descriptor_entry else ""
        target_quantity = descriptor_entry.get("seed_primary_quantity") if descriptor_entry else None
        if not target_quantity and descriptor_entry:
            target_quantity = descriptor_entry.get("quantity")
        target_quantity_norm = _normalize_quantity_text(target_quantity) if target_quantity else None
        target_quantity_compact = target_quantity_norm.replace(" ", "").lower() if target_quantity_norm else None

        cards_locator = page.locator("[data-testid='product-card'], article[data-testid='product-card'], article[data-testid*='product-card'], li[data-testid='product-card'], li[data-testid*='product-card'], div[data-testid='product-card'], div.product-card")
        card_count = await cards_locator.count()
        sys.stderr.write(f"[MONOPRIX_DEBUG]  - Found {card_count} product card nodes.\n")
        if card_count:
            for idx in range(card_count):
                card = cards_locator.nth(idx)
                card_data = await extract_from_card(page, card, base_url)
                url = card_data.get("url")
                title = card_data.get("title") or ""
                quantity_text = card_data.get("quantity")
                if not url or not title:
                    continue
                url = urljoin(base_url, url)
                title_norm = _normalize_search_text(title)
                title_compact = title_norm.replace(" ", "").lower()
                quantity_norm = _normalize_quantity_text(quantity_text)
                quantity_compact = quantity_norm.replace(" ", "").lower() if quantity_norm else None

                brand_ok = True
                if descriptor_brand_norm:
                    brand_ok = descriptor_brand_norm in title_norm

                quantity_ok = True
                if target_quantity_compact:
                    quantity_ok = False
                    if quantity_compact and quantity_compact == target_quantity_compact:
                        quantity_ok = True
                    elif target_quantity_compact in title_compact:
                        quantity_ok = True

                if brand_ok and quantity_ok:
                    if url not in filtered_urls:
                        filtered_urls.append(url)

        if filtered_urls:
            product_urls = filtered_urls
            sys.stderr.write(f"[MONOPRIX_DEBUG]  - Filtered to {len(product_urls)} candidate URLs matching brand/quantity.\n")
        else:
            for link in product_links:
                href = await link.get_attribute("href")
                if not href:
                    continue
                full_url = urljoin(base_url, href)
                if full_url in product_urls:
                    continue
                link_text = _normalize_search_text(await link.inner_text())
                link_compact = link_text.replace(" ", "")
                brand_ok = True
                if descriptor_brand_norm:
                    brand_ok = descriptor_brand_norm in link_text
                quantity_ok = True
                if target_quantity_compact:
                    quantity_ok = target_quantity_compact in link_compact
                if brand_ok and quantity_ok:
                    product_urls.append(full_url)

        if not product_urls:
            for link in product_links:
                href = await link.get_attribute("href")
                if not href:
                    continue
                full_url = urljoin(base_url, href)
                if full_url not in product_urls:
                    product_urls.append(full_url)

        sys.stderr.write(f"[MONOPRIX_DEBUG]  - Found {len(product_urls)} product URLs to check.\n")

        for full_url in product_urls[:MAX_PRODUCTS_PER_TERM]:
            if full_url in candidate_index:
                continue
            if len(candidate_records) >= MAX_PRODUCTS_PER_TERM:
                break
            candidate_entry = {
                "url": full_url,
                "status": "PENDING",
                "product": {
                    "title": "",
                    "brand": descriptor_entry.get("brand") or "",
                    "kind": descriptor_entry.get("seed_primary_name") or descriptor_entry.get("name") or "",
                    "qty": descriptor_entry.get("quantity") or descriptor_entry.get("seed_primary_quantity") or "",
                    "qualifiers": descriptor_entry.get("qualifiers") or [],
                    "ean": None,
                    "image_url": None,
                    "source": "monoprix",
                    "raw_text": "",
                },
            }
            candidate_records.append(candidate_entry)
            candidate_index[full_url] = candidate_entry

        fallback_results: list[tuple[int, Result]] = []
        for product_url in product_urls[:MAX_PRODUCTS_PER_TERM]:
            sys.stderr.write(f"[MONOPRIX_DEBUG]  - Parsing product page in new tab: {product_url}\n")
            entry = candidate_index.get(product_url)
            if entry is None:
                entry = {
                    "url": product_url,
                    "status": "PENDING",
                    "product": {
                        "title": "",
                        "brand": descriptor_entry.get("brand") or "",
                        "kind": descriptor_entry.get("seed_primary_name") or descriptor_entry.get("name") or "",
                        "qty": descriptor_entry.get("quantity") or descriptor_entry.get("seed_primary_quantity") or "",
                        "qualifiers": descriptor_entry.get("qualifiers") or [],
                        "ean": None,
                        "image_url": None,
                        "source": "monoprix",
                        "raw_text": "",
                    },
                }
                candidate_index[product_url] = entry
                if entry not in candidate_records and len(candidate_records) < MAX_PRODUCTS_PER_TERM:
                    candidate_records.append(entry)
            new_page = await context.new_page()
            try:
                product_result = await parse_product_page(new_page, product_url, descriptor_entry)
            finally:
                await new_page.close()
                sys.stderr.write(f"[MONOPRIX_DEBUG]  - Closed tab for {product_url}\n")

            if not product_result:
                continue

            score, plausible, extras = evaluate_candidate(
                product_result,
                descriptor_entry,
                negatives=dynamic_negatives,
                seed_variant=seed_variant,
                category_tokens=category_tokens,
            )
            product_result.extras = extras
            image_match = await _image_matches_descriptor_async(descriptor_entry, product_result.note)
            extras["image_match"] = image_match
            if image_match:
                score += 30
                target_ean = descriptor_entry.get("ean") or EAN
                if target_ean:
                    product_result.matched_ean = str(target_ean)
                sys.stderr.write(f"[MONOPRIX_DEBUG]  - Image match FOUND for '{product_result.title}'.\n")
            else:
                sys.stderr.write(f"[MONOPRIX_DEBUG]  - No image match for '{product_result.title}'.\n")
                extras["vetoes"].append("image_mismatch")

            extras["final_score"] = score
            extras["plausible_baseline"] = plausible

            entry = candidate_index.get(product_url)
            if entry:
                _enrich_candidate_entry(entry, product_result, score, extras)

            core_tokens = descriptor_entry.get("_monoprix_core_tokens")
            if core_tokens is None:
                core_tokens = _descriptor_core_tokens(descriptor_entry)
                descriptor_entry["_monoprix_core_tokens"] = core_tokens

            if core_tokens:
                def _compact(value: typing.Optional[str]) -> str:
                    return "".join(ch for ch in (value or "") if not ch.isspace())
                title_blob = _normalize_search_text(product_result.title)
                normalized_blob = _normalize_search_text(product_result.raw_text)
                title_compact = _compact(title_blob)
                normalized_compact = _compact(normalized_blob)
                missing_core = []
                for token in core_tokens:
                    if not token:
                        continue
                    token_compact = _compact(token)
                    token_variants = {token, token_compact}
                    if token.endswith("e"):
                        token_variants.add(f"{token}s")
                        token_variants.add(f"{token_compact}s")
                    if token.endswith("es") and len(token) > 2:
                        token_variants.add(token[:-1])
                        token_variants.add(token_compact[:-1])
                    if not any(
                        variant and (
                            (title_blob and variant in title_blob)
                            or (normalized_blob and variant in normalized_blob)
                            or (title_compact and variant in title_compact)
                            or (normalized_compact and variant in normalized_compact)
                        )
                        for variant in token_variants
                    ):
                        missing_core.append(token)
                if missing_core:
                    extras.setdefault("missing_core_tokens", missing_core)
                    extras["vetoes"].append("core_token")

            # Image match = validation absolue (pas d'EAN côté Monoprix)
            final_plausible = image_match

            has_core_gap = bool(extras.get("missing_core_tokens"))
            final_plausible = image_match and not has_core_gap

            if final_plausible:
                product_result.status = "OK"
                product_result.candidates = list(candidate_records)
                sys.stderr.write(f"[MONOPRIX_DEBUG] Best match (early return): '{product_result.title}' (Score: {score})\n")
                return product_result

            fallback_results.append((score, product_result))
            sys.stderr.write(
                f"[MONOPRIX_DEBUG]  - Candidate rejected '{product_result.title}' | vetoes={extras['vetoes']}\n"
            )

        if fallback_results:
            fallback_results.sort(key=lambda x: x[0], reverse=True)
            top_score, top_result = fallback_results[0]
            sys.stderr.write(
                f"[MONOPRIX_DEBUG]  - Best rejected candidate '{top_result.title}' (Score: {top_score}) | vetoes={top_result.extras.get('vetoes')}\n"
            )
            vetoes = set(top_result.extras.get("vetoes") or [])
            baseline_ok = bool(top_result.extras.get("plausible_baseline"))
            if baseline_ok and vetoes.issubset({"image_mismatch"}) and top_result.price:
                top_result.status = "OK"
                top_result.extras.setdefault("notes", []).append("accepted_without_image_match")
                sys.stderr.write(
                    f"[MONOPRIX_DEBUG]  - Accepting fallback candidate despite image mismatch: '{top_result.title}'.\n"
                )
                top_result.candidates = list(candidate_records)
                return top_result
        else:
            sys.stderr.write("[MONOPRIX_DEBUG]  - No product detail pages parsed successfully.\n")

    no_res = Result(status="NO_RESULTS")
    if candidate_records:
        no_res.candidates = candidate_records
    return no_res


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

        packaging_texts: list[typing.Optional[str]] = []
        if json_size:
            packaging_texts.append(json_size)

        for selector in (
            "[data-testid='pdp-packaging']",
            "[data-testid='pdp-weight']",
            "[data-testid='pdp-selling-unit']",
            "[data-testid='pdp-size']",
            ".pdp-packaging",
            ".pdp-product-info",
        ):
            packaging_texts.append(await read_text(page.locator(selector)))

        packaging_texts.extend([title, unit_price])
        quantity = _select_quantity_from_candidates(packaging_texts)

        if not quantity and descriptor_quantity:
            normalized_descriptor_quantity = _normalize_quantity_text(descriptor_quantity)
            quantity = normalized_descriptor_quantity or descriptor_quantity

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

        try:
            body_text = await page.inner_text("body")
        except Exception:
            body_text = ""

        image_url = _sanitize_url(image_url)
        sys.stderr.write(f"[MONOPRIX_DEBUG] Extracted image URL: {image_url}\n")

        return Result(
            status="OK_PARTIAL",
            title=title,
            price=price,
            unit_price=unit_price,
            quantity=quantity,
            url=page.url,
            note=image_url,
            image=image_url,
            raw_text=body_text,
        )
    except Exception as e:
        sys.stderr.write(f"[MONOPRIX_DEBUG] Error parsing product page {url}: {e}\n")
        return None


def evaluate_candidate(
    result: Result,
    descriptor: dict[str, typing.Any],
    *,
    negatives: list[str],
    seed_variant: typing.Optional[str],
    category_tokens: list[str],
    size_tolerance: float = 0.25,
) -> tuple[int, bool, dict]:
    """Évalue un candidat Monoprix en appliquant les vérifications de veto."""
    extras: dict[str, typing.Any] = {
        "seed_variant": seed_variant,
        "candidate_variant": None,
        "negatives_hit": [],
        "variant_ok": True,
        "unit_family_ok": True,
        "size_ok": True,
        "category_ok": True,
        "vetoes": [],
    }

    title_lower = (result.title or "").lower()
    text_fields = [result.title, result.quantity, result.unit_price, result.raw_text]
    text_blob = " ".join(value for value in text_fields if isinstance(value, str))
    normalized_blob = _normalize_search_text(text_blob)
    url_normalized = _normalize_search_text(result.url)
    title_normalized = _normalize_search_text(result.title)
    quantity_normalized = _normalize_search_text(result.quantity)
    negative_haystacks = [title_normalized, quantity_normalized, url_normalized]

    # Dynamic negatives
    for token in negatives:
        token_norm = _normalize_search_text(token)
        if token_norm and any(token_norm in hay for hay in negative_haystacks if hay):
            extras["negatives_hit"].append(token)
            extras["vetoes"].append("neg_token")
            break

    # Variant lock
    candidate_variant = detect_variant_from_text(text_blob)
    extras["candidate_variant"] = candidate_variant
    if seed_variant:
        if seed_variant == "nature":
            if candidate_variant and candidate_variant != "nature":
                extras["variant_ok"] = False
                extras["vetoes"].append("variant_mismatch")
            elif not candidate_variant:
                extras["variant_ok"] = False
                extras["vetoes"].append("variant_missing")
        else:
            if candidate_variant and candidate_variant != seed_variant:
                extras["variant_ok"] = False
                extras["vetoes"].append("variant_mismatch")
            elif not candidate_variant:
                extras["variant_ok"] = False
                extras["vetoes"].append("variant_missing")

    # Unit family & size tolerance
    descriptor_quantity = descriptor.get("seed_primary_quantity") or descriptor.get("quantity")
    seed_parsed = _parse_quantity_to_base(_normalize_quantity_text(descriptor_quantity) or descriptor_quantity) if descriptor_quantity else None
    extras["candidate_quantity"] = result.quantity
    candidate_parsed = _candidate_quantity(result)
    if seed_parsed and candidate_parsed:
        seed_amount, seed_unit = seed_parsed
        cand_amount, cand_unit = candidate_parsed
        seed_family = _unit_family_for_unit(seed_unit)
        cand_family = _unit_family_for_unit(cand_unit)
        if seed_family != cand_family:
            extras["unit_family_ok"] = False
            extras["vetoes"].append("unit_family")
        else:
            seed_val = float(seed_amount)
            cand_val = float(cand_amount)
            if seed_val > 0:
                ratio = abs(cand_val - seed_val) / seed_val
                extras["candidate_size_ratio"] = ratio
                if ratio >= size_tolerance:
                    extras["size_ok"] = False
                    extras["vetoes"].append("size_out_of_range")

    # Category check
    if category_tokens:
        if not any(token in normalized_blob for token in category_tokens):
            extras["category_ok"] = False
            extras["vetoes"].append("category")

    # Validation tokens (descriptors seed)
    validation_tokens = _descriptor_validation_tokens(descriptor)
    matched_tokens: list[str] = []
    missing_tokens: list[str] = []
    considered_tokens = 0
    if validation_tokens:
        for token in validation_tokens:
            if not token:
                continue
            if any(ch.isdigit() for ch in token):
                continue
            considered_tokens += 1
            token_hit = False
            token_compact = "".join(ch for ch in token if not ch.isspace())
            blob_compact = "".join(ch for ch in normalized_blob if not ch.isspace()) if normalized_blob else ""
            if token in normalized_blob:
                token_hit = True
            elif token.endswith("e") and f"{token}s" in normalized_blob:
                token_hit = True
            elif token.endswith("es") and token[:-1] in normalized_blob:
                token_hit = True
            elif token_compact and token_compact in blob_compact:
                token_hit = True
            if token_hit:
                matched_tokens.append(token)
            else:
                missing_tokens.append(token)
        coverage = len(matched_tokens) / considered_tokens if considered_tokens else 0.0
        extras["descriptor_token_coverage"] = {
            "coverage": coverage,
            "matched": matched_tokens,
            "missing": missing_tokens,
            "total": considered_tokens,
        }
        extras["missing_tokens"] = missing_tokens
        if coverage < DESCRIPTOR_MATCH_COVERAGE:
            extras["vetoes"].append("descriptor_coverage")

    # Baseline scoring (brand + keywords)
    score = 0
    plausible = False
    brand_match = False
    brand = (descriptor.get("brand") or "").lower()
    if brand and brand in title_lower:
        score += 10
        brand_match = True

    quantity_ref = descriptor.get("quantity") or descriptor.get("seed_primary_quantity")
    if quantity_ref:
        quantity_clean = str(quantity_ref).replace(" ", "").lower()
        title_nospace = title_lower.replace(" ", "")
        if quantity_clean and quantity_clean in title_nospace:
            score += 5

    keyword_match_count = 0
    finder_terms = []
    finder_terms.extend(FINDER_KEYWORDS)
    if QUERY:
        finder_terms.append(QUERY)
    for keyword in finder_terms:
        if not isinstance(keyword, str):
            continue
        normalized = keyword.strip().lower()
        if not normalized:
            continue
        if normalized in title_lower:
            score += 20
            keyword_match_count += 1

    plausible = brand_match
    if keyword_match_count > 0:
        plausible = True

    if _has_banned_keyword(title_lower):
        score -= 15

    if extras["negatives_hit"]:
        score -= 120
    if not extras["variant_ok"]:
        score -= 150

    if extras["vetoes"]:
        plausible = False

    sys.stderr.write(
        "[MONOPRIX_DEBUG][SCORE] - Title: '%s' | Brand: '%s' | Variant(seed/cand)=(%s/%s) | "
        "Vetoes=%s | NegHits=%s | Score=%s | Plausible=%s\n"
        % (
            result.title,
            brand,
            seed_variant,
            candidate_variant,
            extras["vetoes"],
            extras["negatives_hit"],
            score,
            plausible,
        )
    )

    return score, plausible, extras


async def run() -> Result:
    sys.stderr.write("[MONOPRIX_DEBUG] Starting run() function\n")
    if os.environ.get("USE_CDP") != "1":
        sys.stderr.write("[MONOPRIX_DEBUG] ERROR: USE_CDP=1 is not set\n")
        return Result(status="ERROR", note="USE_CDP=1 obligatoire pour Monoprix")

    terms = build_query_terms()
    if not terms:
        sys.stderr.write("[MONOPRIX_DEBUG] NO_QUERY: build_query_terms() returned no terms\n")
        return Result(status="NO_QUERY")

    descriptor_entry = MANUAL_DESCRIPTOR.get(EAN) if EAN else None
    if not descriptor_entry:
        sys.stderr.write(f"[MONOPRIX_DEBUG] ERROR: EAN '{EAN}' not found in descriptor store. Scoring will fail.\n")
        # Optionnel : on peut décider de s'arrêter ici si le descripteur est essentiel
        # return Result(status="ERROR", note=f"EAN {EAN} not in descriptors")
    else:
        sys.stderr.write(f"[MONOPRIX_DEBUG] Successfully loaded descriptor for EAN '{EAN}'.\n")

    if descriptor_entry:
        manual_queries: list[str] = []
        queries_map = descriptor_entry.get("queries")
        if isinstance(queries_map, dict):
            manual_queries = queries_map.get("monoprix") or []
        if not manual_queries:
            manual_queries = descriptor_entry.get("monoprix_queries") or []
        manual_queries = [q for q in manual_queries if isinstance(q, str) and q.strip()]
        filtered_manual = [q for q in manual_queries if not _looks_like_ean(q)]
        if filtered_manual:
            terms = filtered_manual[:3]
        elif manual_queries:
            terms = manual_queries[:3]
        else:
            filtered_terms = [t for t in terms if not _looks_like_ean(t)]
            terms = filtered_terms or terms
    else:
        filtered_terms = [t for t in terms if not _looks_like_ean(t)]
        terms = filtered_terms or terms

    sys.stderr.write(f"[MONOPRIX_DEBUG] Search terms: {terms}\n")

    storage_state = state_path_for("monoprix")
    sys.stderr.write(f"[MONOPRIX_DEBUG] Using storage state: {storage_state}\n")
    
    p, browser, context, page = await make_context(
        headless=HEADLESS,
        proxy=PROXY,
        storage_state_path=storage_state,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    )
    try:
        inject_monoprix_image_provider(context)
    except Exception:
        pass
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
