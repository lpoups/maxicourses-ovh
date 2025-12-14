#!/usr/bin/env python3
"""Human-paced Leclerc Drive lookup via Chrome 9222.

- Connects to an already running Chrome started with ``start_chrome_debug.sh``.
- Types the query slowly (human-like), waits for results, opens the best match,
  then extracts price/unit/URL from the PDP.
- Exposes :func:`run_manual_leclerc` for reuse inside other scripts.

Mandate: the enforced workflow is documented in
``collection_mandate.METHODS['leclerc_drive']``.

CLI usage example::

    USE_CDP=1 CDP_URL=http://127.0.0.1:9222 \\
    STORE_URL="https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx" \\
    QUERY="Coca Cola 1,75 L" EAN=5000112611861 \\
    python3 manual_leclerc_cdp.py

The script prints a JSON payload on stdout. It requires Chrome remote (port 9222)
to be up before invocation.

"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
import sys
from typing import Optional, List
from functools import lru_cache

from datetime import datetime
from pathlib import Path
import tempfile
import uuid
import re
import unicodedata
from urllib.parse import urlparse, urljoin

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright
from seed_catalog import all_seeds  # noqa: E402
try:
    from pipeline.finder import LeclercAdapter  # type: ignore
    from pipeline.image_matching import descriptor_matches_candidate
except Exception:  # pragma: no cover - Finder optional
    LeclercAdapter = None  # type: ignore

    def descriptor_matches_candidate(*_args, **_kwargs) -> bool:
        return False


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
STORE_URL = os.environ.get("STORE_URL", "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx")
CDP_URL = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
NO_DELAY = os.environ.get("LECLERC_NO_DELAY", "0").lower() in {"1", "true", "yes"}
HUMAN_DELAY_MS = env_int("LECLERC_HUMAN_DELAY_MS", 100)
RESULT_DELAY_MS = env_int("LECLERC_RESULT_DELAY_MS", 100)
PDP_DELAY_MS = env_int("LECLERC_PDP_DELAY_MS", 100)
TYPE_MIN_DELAY = env_int("LECLERC_TYPE_MIN_MS", 8)
FAST_MODE = os.environ.get("LECLERC_FAST_MODE", "1").lower() in {"1", "true", "yes"}
MAX_RESULT_DELAY_MS = 2000  # plafond voulu entre deux lectures de listing
MAX_PDP_DELAY_MS = 2000     # plafond voulu entre ouverture d'une fiche et retour
MIN_DELAY_MS = 0 if NO_DELAY else 25   # floor divisé par 2
MIN_ADAPTIVE_MS = 0 if NO_DELAY else 50


def _env_delay(name: str, default: int, *, minimum: int = 50) -> int:
    value = env_int(name, default)
    if FAST_MODE:
        value = max(minimum, max(1, value) // 10)
    return value


HUMAN_DELAY_MS = _env_delay("LECLERC_HUMAN_DELAY_MS", 100 if FAST_MODE else 70, minimum=MIN_DELAY_MS)
RESULT_DELAY_MS = _env_delay("LECLERC_RESULT_DELAY_MS", 100 if FAST_MODE else 70, minimum=MIN_DELAY_MS)
PDP_DELAY_MS = _env_delay("LECLERC_PDP_DELAY_MS", 200 if FAST_MODE else 100, minimum=MIN_DELAY_MS)
TYPE_MIN_DELAY = _env_delay("LECLERC_TYPE_MIN_MS", 8 if FAST_MODE else 8, minimum=0 if NO_DELAY else 5)
TYPE_MAX_DELAY = _env_delay("LECLERC_TYPE_MAX_MS", 180 if FAST_MODE else 18, minimum=10)
# Cap direct pour respecter les 2s max demandées
RESULT_DELAY_MS = min(RESULT_DELAY_MS, MAX_RESULT_DELAY_MS)
PDP_DELAY_MS = min(PDP_DELAY_MS, MAX_PDP_DELAY_MS)


def _adaptive_delay(ms: int, minimum: int = 100) -> int:
    minv = MIN_ADAPTIVE_MS if NO_DELAY else minimum
    if FAST_MODE:
        return max(minv, max(1, ms) // 10)
    return max(minv, ms)

MANUAL_DESCRIPTOR: dict[str, dict] = all_seeds()
EAN_PATTERN = re.compile(r"(?<!\d)(\d{13})(?!\d)")


def _extract_ean_from_html(html: str, url: Optional[str] = None) -> Optional[str]:
    if not html:
        return None
    patterns = [
        re.compile(r'"(?:gtin13|gtin|gtin14|ean)"\s*:\s*"(\d{13})"', flags=re.IGNORECASE),
        re.compile(r">\s*EAN\s*[:#]?\s*(\d{13})", flags=re.IGNORECASE),
        re.compile(r"data-(?:ean|productean|gtin)=\"?(\d{13})\"?", flags=re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.search(html)
        if match:
            return match.group(1)
    if url:
        match = EAN_PATTERN.search(url)
        if match:
            return match.group(1)
    match = EAN_PATTERN.search(html)
    if match:
        return match.group(1)
    return None


async def _find_info_link(page) -> Optional[str]:
    selectors = [
        "a:has-text(\"Informations pratiques\")",
        "a:has-text(\"information produit\")",
        "a[href*='fiche']",
    ]
    for sel in selectors:
        try:
            node = page.locator(sel).first
            if await node.count():
                href = await node.get_attribute("href")
                if href and not href.lower().startswith("javascript:"):
                    return href
        except Exception:
            continue
    return None


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )


def make_leclerc_html_provider(ctx) -> callable:
    """Build a cached HTML provider backed by Playwright."""

    loop = asyncio.get_running_loop()

    @lru_cache(maxsize=64)
    def _cached_html(url: str) -> Optional[str]:
        async def _fetch() -> Optional[str]:
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded")
                return await page.content()
            except Exception:
                return None
            finally:
                await page.close()

        if loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(_fetch(), loop)
                return future.result(timeout=15)
            except Exception:
                return None
        return None

    return _cached_html


def inject_leclerc_html_provider(ctx) -> None:
    if LeclercAdapter is None:
        return
    try:
        LeclercAdapter._html_provider = make_leclerc_html_provider(ctx)  # type: ignore[attr-defined]
    except Exception:
        pass

async def human_pause(page, base_ms: int) -> None:
    if NO_DELAY:
        return
    jitter = random.randint(-int(base_ms * 0.2), int(base_ms * 0.2))
    await page.wait_for_timeout(max(50, base_ms + jitter))


def _normalize(text: str) -> str:
    return " ".join(text.lower().split()) if text else ""


def normalize_space(value: Optional[str]) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [tok for tok in re.split(r"[^0-9a-zà-öø-ÿ]+", text.lower()) if len(tok) >= 2]


GENERIC_TOKENS = {
    "lot", "lots", "pack", "format", "ml", "g", "kg", "cl", "l", "sans", "avec",
    "capsules", "capsule", "pcs", "piece", "pieces", "unit", "unite", "unites",
}

DEFAULT_NEGATIVE_PATTERNS = [
    "sans sucre",
    "sans sucres",
    "sans-sucre",
]

LECLERC_MAX_PDP = env_int("LECLERC_MAX_PDP", 12)


def _build_query_candidates(descriptor_entry: Optional[dict], fallback_query: str, ean: str) -> List[str]:
    candidates: List[str] = []

    def add(value: Optional[str]) -> None:
        if not isinstance(value, str):
            return
        cleaned = " ".join(value.split())
        if not cleaned:
            return
        if cleaned in candidates:
            return
        candidates.append(cleaned)

    primary_keywords: List[str] = []
    if isinstance(descriptor_entry, dict):
        primary_raw = descriptor_entry.get("primary_keywords")
        if isinstance(primary_raw, (list, tuple)):
            primary_keywords = [
                normalize_space(str(item))
                for item in primary_raw
                if isinstance(item, str) and normalize_space(item)
            ][:5]
    for keyword in primary_keywords:
        add(keyword)

    if not candidates and isinstance(descriptor_entry, dict):
        seed_query = descriptor_entry.get("seed_query")
        if isinstance(seed_query, str) and seed_query.strip():
            add(seed_query.strip())

    if not candidates and fallback_query:
        add(fallback_query)

    trimmed: List[str] = []
    for query in candidates:
        if len(query) <= 30:
            trimmed.append(query)
            continue
        pieces = []
        for token in query.split():
            tentative = " ".join(pieces + [token]) if pieces else token
            if len(tentative) <= 30:
                pieces.append(token)
            else:
                break
        trimmed.append(" ".join(pieces) if pieces else query[:30].rstrip())
    return trimmed


def _descriptor_tokens(entry: Optional[dict]) -> List[str]:
    tokens: List[str] = []
    if not isinstance(entry, dict):
        return tokens
    for key in ("brand", "name", "description", "quantity"):
        value = entry.get(key)
        for tok in _tokenize(value):
            if tok not in GENERIC_TOKENS and tok not in tokens:
                tokens.append(tok)
    return tokens


def _score_card(
    label: str,
    href: str,
    query_tokens: List[str],
    descriptor_tokens: List[str],
    descriptor_numbers: List[str],
    brand_tokens: List[str],
    ean: str,
) -> int:
    haystack = f"{href} {label}".lower()
    score = 0
    
    # EAN Match: Definitive proof.
    if ean and ean in haystack:
        score += 500  # Massive bonus, overrides almost everything
        return score

    # Query tokens
    for tok in query_tokens:
        if tok in haystack:
            score += 6
            
    # Descriptor tokens
    descriptor_core = [tok for tok in descriptor_tokens if len(tok) >= 4]
    descriptor_hits = 0
    for tok in descriptor_core:
        if tok in haystack:
            score += 8
            descriptor_hits += 1
            
    # Missing descriptor penalty
    if descriptor_core:
        missing = len(descriptor_core) - descriptor_hits
        if missing > 0:
            score -= missing * 5 # Reduced penalty (was 12)

    # Supremo sanity check
    if 'supremo' in descriptor_tokens and 'supremo' not in haystack:
        score -= 60
        
    # Brand check: Important but shouldn't kill a good visual match
    brand_present = False
    for tok in brand_tokens:
        if tok and tok in haystack:
            score += 30
            brand_present = True
            
    if brand_tokens and not brand_present:
        score -= 40 # Reduced penalty (was 80) to allow for weird title formatting
        
    # Quantity numbers check
    if descriptor_numbers:
        card_numbers = set(_numeric_tokens(label) + _numeric_tokens(href))
        if card_numbers & set(descriptor_numbers):
            score += 10
        else:
            score -= 10 # Reduced penalty (was 25)

    sys.stderr.write(f"[LECLERC_SCORE] '{label}' Score: {score} (Brand: {brand_present})\n")
    return score


def _numeric_tokens(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return re.findall(r"\d+", text)


def _build_candidate_product(
    descriptor_entry: Optional[dict],
    title: str,
    matched_ean: Optional[str],
    html_snippet: str,
    image_url: Optional[str],
    quantity_text: Optional[str],
) -> dict:
    def _norm(value: Optional[str]) -> str:
        if not isinstance(value, str):
            return ""
        return " ".join(value.split())

    product = {
        "title": _norm(title),
        "brand": "",
        "kind": "",
        "qty": _norm(quantity_text),
        "qualifiers": [],
        "ean": matched_ean,
        "image_url": image_url,
        "source": "leclerc",
        "raw_text": (html_snippet or "")[:4000],
    }

    if isinstance(descriptor_entry, dict):
        brand = _norm(descriptor_entry.get("brand"))
        if brand:
            product["brand"] = brand
        description = (
            _norm(descriptor_entry.get("seed_primary_name"))
            or _norm(descriptor_entry.get("name"))
            or _norm(descriptor_entry.get("description"))
        )
        if description:
            product["kind"] = description
        if not product["qty"]:
            qty = (
                _norm(descriptor_entry.get("quantity"))
                or _norm(descriptor_entry.get("seed_primary_quantity"))
            )
            if qty:
                product["qty"] = qty
        qualifiers = descriptor_entry.get("qualifiers")
        if isinstance(qualifiers, list):
            norm_q = [_norm(str(item)) for item in qualifiers if _norm(str(item))]
            if norm_q:
                product["qualifiers"] = norm_q
    return product


def _normalized_unit_price(price: Optional[str], quantity: Optional[str]) -> Optional[str]:
    """Compute a coherent €/L or €/kg when the site unit is inconsistent."""
    if not price or not quantity:
        return None
    try:
        price_val = float(str(price).replace(",", "."))
    except Exception:
        return None
    q = str(quantity).upper().replace(" ", "")
    # Handle multipack: "6X33CL" or "4X1.5L"
    match = re.search(r"(?:(\d+)[X])?([0-9]+(?:[.,][0-9]+)?)(L|CL|ML|KG|G)", q)
    if not match:
        return None
    try:
        count = float(match.group(1)) if match.group(1) else 1.0
        unit_val = float(match.group(2).replace(",", "."))
        qty_val = count * unit_val
    except Exception:
        return None
    unit = match.group(3)
    if unit == "L":
        per = price_val / max(qty_val, 1e-6)
        return f"{per:.2f} € / L"
    if unit == "CL":
        per = price_val / (qty_val / 100.0)
        return f"{per:.2f} € / L"
    if unit == "ML":
        per = price_val / (qty_val / 1000.0)
        return f"{per:.2f} € / L"
    if unit == "KG":
        per = price_val / max(qty_val, 1e-6)
        return f"{per:.2f} € / kg"
    if unit == "G":
        per = price_val / (qty_val / 1000.0)
        return f"{per:.2f} € / kg"
    return None


async def run_manual_leclerc(
    *,
    query: str,
    ean: str,
    store_url: str,
    cdp_url: str = "http://127.0.0.1:9222",
    human_delay_ms: int = 50,
    result_delay_ms: int = 120,
    pdp_delay_ms: int = 70,
    type_min_delay: int = 80,
    type_max_delay: int = 80,
    direct_url: Optional[str] = None,
    skip_search: bool = False,
) -> dict:
    """Replay a Leclerc Drive search with human pacing and return a JSON-ready dict.
    
    If direct_url is provided, skip the search phase and go directly to the product page.
    If skip_search is True and direct_url fails, return NO_PRICE without fallback.
    """
    started = time.perf_counter()

    # Quick price update mode: direct URL provided
    if direct_url:
        sys.stderr.write(f"[LECLERC_DEBUG] DIRECT_URL mode: {direct_url}\n")
        if not (query or ean):
            return {"status": "ERROR", "error": "QUERY or EAN is required"}
        if os.environ.get("USE_CDP") != "1":
            return {"status": "ERROR", "error": "SET USE_CDP=1 (Chrome remote obligatoire)"}
        
        # We'll jump directly to the PDP extraction logic
        # but first we need to set up the browser context
        pass  # Continue with browser setup below
    else:
        # Regular search mode
        if not (query or ean):
            return {"status": "ERROR", "error": "QUERY is required"}
        if os.environ.get("USE_CDP") != "1":
            return {"status": "ERROR", "error": "SET USE_CDP=1 (Chrome remote obligatoire)"}

    # Clamp pour garantir <2s entre fiches
    result_delay_ms = min(result_delay_ms, MAX_RESULT_DELAY_MS)
    pdp_delay_ms = min(pdp_delay_ms, MAX_PDP_DELAY_MS)
    sys.stderr.write(
        f"[LECLERC_DEBUG] FAST_MODE={FAST_MODE} | delays => human:{human_delay_ms}ms "
        f"result:{result_delay_ms}ms pdp:{pdp_delay_ms}ms type:[{type_min_delay},{type_max_delay}] "
        f"query:'{query}' direct_url:{bool(direct_url)}\n"
    )

    descriptor_entry = MANUAL_DESCRIPTOR.get(ean.strip()) if ean else None
    descriptor_tokens = _descriptor_tokens(descriptor_entry)
    descriptor_numbers = []
    if isinstance(descriptor_entry, dict):
        descriptor_numbers.extend(_numeric_tokens(descriptor_entry.get('quantity')))
        descriptor_numbers.extend(_numeric_tokens(descriptor_entry.get('name')))
        descriptor_numbers.extend(_numeric_tokens(descriptor_entry.get('description')))
    descriptor_numbers = [num for num in descriptor_numbers if num]
    brand_tokens: List[str] = []
    if isinstance(descriptor_entry, dict):
        brand_raw = descriptor_entry.get('brand')
        brand_tokens = _tokenize(brand_raw)
        if isinstance(brand_raw, str):
            sanitized = re.sub(r"[^0-9a-z]+", "", brand_raw.lower())
    query_candidates = _build_query_candidates(descriptor_entry, query, ean)
    print(f"DEBUG: descriptor={descriptor_entry}")
    print(f"DEBUG: candidates={query_candidates}")
    sys.stdout.flush()
    if not query:
        if isinstance(descriptor_entry, dict) and descriptor_entry.get("seed_query"):
             query = descriptor_entry["seed_query"]
        elif query_candidates:
             query = query_candidates[0]
    descriptor_negatives: List[str] = []
    leclerc_negatives = None
    if isinstance(descriptor_entry, dict):
        neg_map = descriptor_entry.get("negatives")
        if isinstance(neg_map, dict):
            leclerc_negatives = neg_map.get("leclerc")
    if isinstance(leclerc_negatives, (list, tuple)):
        for item in leclerc_negatives:
            if isinstance(item, str) and item.strip():
                token = item.strip().lower()
                if token not in descriptor_negatives:
                    descriptor_negatives.append(token)
    descriptor_text = ""
    if isinstance(descriptor_entry, dict):
        descriptor_text = " ".join(
            str(descriptor_entry.get(key) or "")
            for key in (
                "seed_primary_name",
                "name",
                "description",
                "seed_primary_quantity",
            )
        ).lower()
    for pattern in DEFAULT_NEGATIVE_PATTERNS:
        token = pattern.strip().lower()
        if not token:
            continue
        if token in descriptor_text:
            continue
        if token not in descriptor_negatives:
            descriptor_negatives.append(token)
    if os.environ.get("LECLERC_LOG_NEGATIVES") == "1":
        sys.stderr.write(f"[LECLERC_DEBUG] negatives={descriptor_negatives}\n")
    expected_pack_count = 1
    if isinstance(descriptor_entry, dict):
        canonical = descriptor_entry.get("canonical")
        if isinstance(canonical, dict):
            candidate_pack = canonical.get("pack_count")
            if isinstance(candidate_pack, int) and candidate_pack > 1:
                expected_pack_count = candidate_pack

    page: Optional["Page"] = None  # type: ignore[name-defined]
    finder_candidates: List[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        try:
            context.set_default_timeout(15000)
            context.set_default_navigation_timeout(15000)
        except Exception:
            pass

        try:
            inject_leclerc_html_provider(context)
        except Exception:
            pass

        if context.pages:
            page = context.pages[0]
        else:
            page = await context.new_page()

        async def _close_extra(new_page):
            nonlocal page
            if page is None:
                page = new_page
                return
            if new_page is page:
                return
            try:
                await new_page.close()
            except Exception:
                pass

        context.on("page", lambda new_page: asyncio.create_task(_close_extra(new_page)))

        await page.bring_to_front()


        # Direct URL mode: skip search and go straight to PDP
        if direct_url:
            sys.stderr.write(f"[LECLERC_DEBUG] Navigating directly to {direct_url}\n")
            try:
                await page.goto(direct_url, wait_until="domcontentloaded", timeout=5000)
                await human_pause(page, pdp_delay_ms)
                sys.stderr.write(f"[LECLERC_DEBUG] Direct navigation successful -> {time.perf_counter()-started:.2f}s\n")
            except Exception as e:
                sys.stderr.write(f"[LECLERC_DEBUG] Direct navigation failed: {e}\n")
                if skip_search:
                    return {"status": "NO_PRICE", "note": "Direct URL failed (skip_search=True)"}
                return {"status": "NO_PRICE", "note": "Direct URL navigation failed"}
            
            # Extract price directly from PDP
            async def text_clean(selector: str) -> Optional[str]:
                node = page.locator(selector).first
                try:
                    if await node.count():
                        value = await node.text_content()
                        if value:
                            return " ".join(value.split())
                except Exception:
                    return None
                return None

            async def first_match_text(selectors: List[str]) -> Optional[str]:
                for selector in selectors:
                    value = await text_clean(selector)
                    if value:
                        return value
                return None
            
            try:
                title_raw = await page.locator("h1").first.text_content()
            except Exception:
                title_raw = None
            title = " ".join(title_raw.split()) if title_raw else ""
            
            whole = await first_match_text([
                ".pWCRS310_PrixPartieEntiere",
                ".prix .prix-actuel-partie-entiere",
                ".pWCRS310_PrixUnitairePartieEntiere",
            ]) or ""
            decimal = await first_match_text([
                ".pWCRS310_PrixPartieDecimale",
                ".prix .prix-actuel-partie-decimale",
                ".pWCRS310_PrixUnitairePartieDecimale",
            ]) or ""
            whole_digits = "".join(filter(str.isdigit, whole))
            decimal_digits = "".join(filter(str.isdigit, decimal))[:2]
            price = f"{int(whole_digits)}.{decimal_digits or '00'}" if whole_digits else None
            if price:
                price = price.replace(".", ",")
            
            unit_price = await first_match_text([
                ".pWCRS310_PrixUniteMesure",
                ".prix .prix-detail",
                ".pWCRS310_PrixUnitaire",
            ])
            
            quantity = None
            if unit_price and "€" in unit_price:
                quantity = await first_match_text([
                    ".spanWCRS310_ContenanceInfo",
                    ".ficheProduit__infos--poids",
                ])
            if not quantity:
                quantity = await first_match_text([
                    ".ficheProduit__infos--poids",
                    ".pWCRS310_ContenanceInfo",
                ])
            if quantity:
                quantity = quantity.upper()
            
            # Try to extract EAN
            try:
                html_content = await page.content()
                matched_ean = _extract_ean_from_html(html_content, direct_url)
            except Exception:
                matched_ean = None
            
            if not price:
                return {"status": "NO_PRICE", "title": title, "url": direct_url, "note": f"Quick update via {direct_url}"}
            
            # Build product object
            product = _build_candidate_product(
                descriptor_entry,
                title,
                matched_ean,
                "",
                None,
                quantity,
            )
            
            # Extract store name from URL
            store_label = "E.Leclerc Drive"
            try:
                parsed = urlparse(direct_url)
                slug = parsed.path or ""
                match = re.search(r"magasin-[0-9-]+-([^./]+)", slug, re.IGNORECASE)
                if match:
                    alias = match.group(1).replace('-', ' ').strip()
                    if alias:
                        store_label = f"E.Leclerc Drive · {alias.title()}"
            except Exception:
                pass
            
            return {
                "status": "OK",
                "title": title,
                "price": price,
                "unit_price": unit_price,
                "quantity": quantity,
                "url": direct_url,
                "matched_ean": matched_ean or ean,
                "store": store_label,
                "note": f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} · {store_label}",
                "_meta": {"supports_keywords": True},
                "equivalent": False,
                "product": product,
            }
        
        # Regular mode: go to store homepage and perform search
        await page.goto(store_url, wait_until="domcontentloaded")
        await human_pause(page, human_delay_ms)
        sys.stderr.write(f"[LECLERC_DEBUG] after home human pause -> {time.perf_counter()-started:.2f}s\n")

        # Cookie consent (OneTrust) if visible
        try:
            consent_button = page.locator("#onetrust-accept-btn-handler")
            if await consent_button.count():
                await consent_button.click()
                await human_pause(page, _adaptive_delay(3000))
                sys.stderr.write(f"[LECLERC_DEBUG] after consent -> {time.perf_counter()-started:.2f}s\n")
        except Exception:
            pass

        expected_tokens = [tok.lower() for tok in query.split() if len(tok) > 2]
        expected_tokens.extend(tok for tok in descriptor_tokens if tok)
        expected_tokens.extend(tok for tok in brand_tokens if tok)
        if descriptor_entry and isinstance(descriptor_entry, dict):
            extra = _tokenize(descriptor_entry.get('seed_primary_name'))
            extra += _tokenize(descriptor_entry.get('description'))
            expected_tokens.extend(extra)
        expected_tokens = list(dict.fromkeys(expected_tokens))

        search_field = page.locator("input[id*='rechercheTexte']").first
        try:
            await search_field.click(force=True, timeout=5000)
        except Exception:
            pass
        await human_pause(page, _adaptive_delay(1000))
        sys.stderr.write(f"[LECLERC_DEBUG] after focus -> {time.perf_counter()-started:.2f}s\n")
        try:
            await search_field.evaluate("el => el.value = ''")
        except Exception:
            pass
        await human_pause(page, _adaptive_delay(500))
        for ch in query:
            await search_field.type(ch, delay=random.randint(type_min_delay, type_max_delay))
        await human_pause(page, _adaptive_delay(600))
        await search_field.press("Enter")
        search_timeout = min(6000, max(1500, result_delay_ms * 20))
        try:
            await page.wait_for_selector("li.liWCRS310_Product", timeout=search_timeout)
        except PlaywrightTimeoutError:
            sys.stderr.write(
                f"[LECLERC_DEBUG] search results timeout after {time.perf_counter()-started:.2f}s\n"
            )
        else:
            sys.stderr.write(
                f"[LECLERC_DEBUG] results visible -> {time.perf_counter()-started:.2f}s\n"
            )
        await human_pause(page, result_delay_ms)
        sys.stderr.write(f"[LECLERC_DEBUG] after result pause -> {time.perf_counter()-started:.2f}s\n")

        cards = page.locator("li.liWCRS310_Product")
        card_count = min(await cards.count(), 12)
        if not card_count:
            sys.stderr.write(f"[LECLERC_DEBUG] no cards after {time.perf_counter()-started:.2f}s\n")
            return {"status": "NO_RESULTS", "query": query}

        candidate_rows: List[dict] = []
        for idx in range(card_count):
            try:
                node = cards.nth(idx).locator("a.aWCRS310_Product").first
                label = await node.inner_text(timeout=1500)
                href = await node.get_attribute("href", timeout=1500) or ""
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue
            normalized_label = (label or "").lower()
            normalized_href = (href or "").lower()
            score = _score_card(
                label or "",
                href,
                expected_tokens,
                descriptor_tokens,
                descriptor_numbers,
                brand_tokens,
                ean,
            )
            penalty = 0
            if descriptor_negatives:
                for token in descriptor_negatives:
                    if token and (token in normalized_label or token in normalized_href):
                        penalty += 120
                        break
            if expected_pack_count <= 1:
                if re.search(r"\b\d+\s*[x×]\s*\d+", normalized_label):
                    penalty += 90
                if " pack" in normalized_label or normalized_label.startswith("pack "):
                    penalty += 60
                if re.search(r"\bx\d+\b", normalized_label):
                    penalty += 60
            score -= penalty
            try:
                snippet = await cards.nth(idx).inner_html(timeout=1500)
            except Exception:
                snippet = ""
            candidate_rows.append(
                {
                    "index": idx,
                    "label": label or "",
                    "href": href,
                    "score": score,
                    "snippet": snippet,
                }
            )

        # [Optim] Fail Fast: Check if any candidate is worthy
        if not candidate_rows:
             sys.stderr.write(f"[LECLERC_DEBUG] no usable cards after filtering\n")
             return {"status": "NO_RESULTS", "query": query}

        max_score = max(c["score"] for c in candidate_rows)
        sys.stderr.write(f"[LECLERC_DEBUG] Best Score: {max_score}\n")

        # Threshold to even consider clicking (40 is barely above brand match)
        # 30 = Brand (30) + nothing else. Weak.
        # 46 = Brand (30) + 2 query tokens (6+6) + 1 descriptor (8) - penalties...
        # if max_score < 10:
        #      sys.stderr.write(f"[LECLERC_DEBUG] FAIL FAST: Max score {max_score} < 40. Aborting search for this query.\n")
        #      return {
        #          "status": "NO_MATCH", 
        #          "query": query, 
        #          "note": f"Low relevance score ({max_score})"
        #      }

        if not candidate_rows:
            sys.stderr.write(f"[LECLERC_DEBUG] no usable cards after filtering\n")
            return {"status": "NO_RESULTS", "query": query}

        # Parcourir les cartes dans l'ordre d'affichage pour couvrir toutes les fiches visibles.
        # L'ordre du site est généralement trié par pertinence sur "Produits en stock",
        # on ne re-trie donc plus les candidats par score pour éviter de rester bloqué
        # sur une promotion hors-sujet en tête de liste.
        search_url = page.url

        async def text_clean(selector: str) -> Optional[str]:
            node = page.locator(selector).first
            try:
                if await node.count():
                    value = await node.text_content()
                    if value:
                        return " ".join(value.split())
            except Exception:
                return None
            return None

        async def first_match_text(selectors: List[str]) -> Optional[str]:
            for selector in selectors:
                value = await text_clean(selector)
                if value:
                    return value
            return None

        final_title: Optional[str] = None
        final_price: Optional[str] = None
        final_unit_price: Optional[str] = None
        final_quantity: Optional[str] = None
        final_url: Optional[str] = None
        final_matched_ean: Optional[str] = None
        final_image_url: Optional[str] = None
        final_reason: Optional[str] = None
        last_candidate_entry: Optional[dict] = None
        best_token_candidate: Optional[dict] = None
        best_token_score: int = -1

        adapter_instance = None
        if LeclercAdapter is not None:
            try:
                adapter_instance = LeclercAdapter()
            except Exception:
                adapter_instance = None

        def _listing_image_from_snippet(snippet: str) -> Optional[str]:
            if not snippet:
                return None
            match = re.search(r'<img[^>]+(?:data-src|src)=["\']([^"\']+)["\']', snippet, flags=re.I)
            if not match:
                return None
            value = match.group(1).strip()
            if not value:
                return None
            if value.startswith("//"):
                return "https:" + value
            if value.startswith("/"):
                return urljoin(store_url, value)
            return value

        for visit_idx, cand in enumerate(candidate_rows[:LECLERC_MAX_PDP]):
            listing_url = urljoin(store_url, cand.get("href", "")) if cand.get("href") else None
            listing_image = _listing_image_from_snippet(cand.get("snippet", ""))
            candidate_entry: dict = {
                "listing_index": cand["index"],
                "listing_label": cand["label"],
                "listing_url": listing_url,
                "score": cand["score"],
                "query": query,
                "status": "PENDING",
            }
            if cand.get("snippet"):
                candidate_entry["listing_snippet"] = cand["snippet"][:4000]

            normalized_label = cand["label"].lower()
            normalized_href = (cand.get("href") or "").lower()
            if descriptor_negatives and any(
                token and (token in normalized_label or token in normalized_href)
                for token in descriptor_negatives
            ):
                candidate_entry["status"] = "REJECTED"
                candidate_entry["reason"] = "negative_keyword"
                finder_candidates.append(candidate_entry)
                continue

            fallback_url = listing_url
            navigated = False
            try:
                if visit_idx > 0:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=2500)
                    await human_pause(page, result_delay_ms)
                cards = page.locator("li.liWCRS310_Product")
                target_card = cards.nth(cand["index"])
                link = target_card.locator("a.aWCRS310_Product").first
                await link.scroll_into_view_if_needed()
                await human_pause(page, _adaptive_delay(200))
                await link.click(timeout=1500)
                try:
                    await page.wait_for_url("**/fiche-produits-*.aspx", timeout=2000)
                    navigated = True
                except PlaywrightTimeoutError:
                    navigated = False
            except Exception:
                navigated = False

            if not navigated and fallback_url:
                sys.stderr.write(
                    f"[LECLERC_DEBUG] navigation fallback to {fallback_url}\n"
                )
                try:
                    await page.goto(fallback_url, wait_until="domcontentloaded", timeout=2500)
                    navigated = True
                except Exception:
                    navigated = False

            if not navigated:
                candidate_entry["status"] = "ERROR"
                candidate_entry["reason"] = "navigation_failed"
                finder_candidates.append(candidate_entry)
                last_candidate_entry = candidate_entry
                continue

            await human_pause(page, pdp_delay_ms)

            current_url = page.url or fallback_url or ""
            candidate_entry["url"] = current_url

            try:
                title_raw = await page.locator("h1").first.text_content()
            except Exception:
                title_raw = None
            raw_title_for_label = title_raw if title_raw else (cand["label"] or "")
            title = " ".join(raw_title_for_label.split()) if raw_title_for_label else cand.get("label") or ""
            candidate_entry["title"] = title

            blocked_token = None
            normalized_title_tokens = title.lower() if title else ""
            if descriptor_negatives and normalized_title_tokens:
                for token in descriptor_negatives:
                    if token and token in normalized_title_tokens:
                        blocked_token = token
                        break
            if blocked_token:
                candidate_entry["status"] = "REJECTED"
                candidate_entry["reason"] = f"negative_keyword_title:{blocked_token}"
                finder_candidates.append(candidate_entry)
                continue

            whole = await first_match_text([
                ".pWCRS310_PrixPartieEntiere",
                ".prix .prix-actuel-partie-entiere",
                ".pWCRS310_PrixUnitairePartieEntiere",
            ]) or ""
            decimal = await first_match_text([
                ".pWCRS310_PrixPartieDecimale",
                ".prix .prix-actuel-partie-decimale",
                ".pWCRS310_PrixUnitairePartieDecimale",
            ]) or ""
            whole_digits = "".join(filter(str.isdigit, whole))
            decimal_digits = "".join(filter(str.isdigit, decimal))[:2]
            price = f"{int(whole_digits)}.{decimal_digits or '00'}" if whole_digits else None
            if price:
                price = price.replace(".", ",")
            unit_price = await first_match_text([
                ".pWCRS310_PrixUniteMesure",
                ".prix .prix-detail",
                ".pWCRS310_PrixUnitaire",
            ])
            quantity = None
            if unit_price and "€" in unit_price:
                quantity = await first_match_text([
                    ".spanWCRS310_ContenanceInfo",
                    ".ficheProduit__infos--poids",
                ])
            if not quantity:
                quantity = await first_match_text([
                    ".ficheProduit__infos--poids",
                    ".pWCRS310_ContenanceInfo",
                ])
            if quantity:
                quantity = quantity.upper()

            candidate_entry["price"] = price
            candidate_entry["unit_price"] = unit_price
            candidate_entry["quantity"] = quantity

            normalized_title_tokens = title.lower() if title else ""
            token_hits_local = sum(1 for tok in expected_tokens if tok and tok in normalized_title_tokens)
            candidate_entry["token_hits"] = token_hits_local
            if price and token_hits_local > best_token_score:
                best_token_candidate = dict(candidate_entry)
                best_token_score = token_hits_local

            image_url = None
            screenshot_path = None
            image_selectors = [
                "img[itemprop='image']",
                ".ficheProduit__visuel img",
                "img[data-testid='medias-img']",
                ".product-image img",
                "img[data-src]",
            ]
            target_locator = None
            for sel in image_selectors:
                node = page.locator(sel).first
                try:
                    if await node.count():
                        target_locator = node
                        break
                except Exception:
                    continue
            if target_locator:
                try:
                    tmp_path = Path(tempfile.gettempdir()) / f"leclerc-img-{uuid.uuid4().hex}.png"
                    await target_locator.screenshot(path=str(tmp_path))
                    screenshot_path = tmp_path
                except Exception:
                    screenshot_path = None
                try:
                    for attr in ("src", "data-src", "data-original", "srcset", "data-srcset"):
                        raw = await target_locator.get_attribute(attr)
                        if not raw:
                            continue
                        raw = raw.strip()
                        if not raw:
                            continue
                        if ("srcset" in attr or "SRCSET" in attr) and " " in raw:
                            raw = raw.split(" ", 1)[0]
                        image_url = raw
                        break
                except Exception:
                    image_url = None
            if not image_url:
                try:
                    meta_candidate = await page.locator("meta[property='og:image']").first.get_attribute("content")
                except Exception:
                    meta_candidate = None
                if meta_candidate:
                    image_url = meta_candidate.strip()
            if image_url:
                if image_url.startswith("//"):
                    image_url = "https:" + image_url
                elif image_url.startswith("/"):
                    image_url = urljoin(current_url, image_url)
            if not image_url:
                image_url = listing_image
            candidate_entry["image_url"] = image_url

            html = ""
            try:
                html = await page.content()
            except Exception:
                html = ""

            observed_eans: List[str] = []
            try:
                path_only = urlparse(current_url or "").path
                path_ean = _extract_ean_from_html(path_only, None)
                if path_ean:
                    observed_eans.append(path_ean)
            except Exception:
                pass
            html_ean = _extract_ean_from_html(html, current_url)
            if html_ean and html_ean not in observed_eans:
                observed_eans.append(html_ean)

            info_ean = None
            info_url = None
            if adapter_instance:
                try:
                    info_url = adapter_instance.find_info_link(current_url)
                    if info_url:
                        info_ean = adapter_instance.extract_ean_from_info(info_url)
                        if info_ean and info_ean not in observed_eans:
                            observed_eans.append(info_ean)
                except Exception:
                    info_ean = None
            candidate_entry["observed_eans"] = observed_eans
            if info_url:
                candidate_entry["info_url"] = info_url

            matched_candidate_ean = None
            if html_ean:
                matched_candidate_ean = html_ean
            elif info_ean:
                matched_candidate_ean = info_ean
            elif observed_eans:
                matched_candidate_ean = observed_eans[0]

            candidate_entry["matched_ean"] = matched_candidate_ean
            candidate_entry["product"] = _build_candidate_product(
                descriptor_entry,
                title or cand["label"],
                matched_candidate_ean,
                html,
                image_url,
                quantity,
            )

            image_match = False
            if descriptor_entry:
                candidate_ref = None
                if screenshot_path and screenshot_path.exists():
                    candidate_ref = str(screenshot_path)
                elif image_url:
                    candidate_ref = image_url
                if candidate_ref:
                    try:
                        image_match = descriptor_matches_candidate(
                            descriptor_entry,
                            candidate_ref,
                            ean=ean or descriptor_entry.get("ean"),
                            threshold=16,
                        )
                    except Exception:
                        image_match = False
            candidate_entry["image_match"] = image_match
            if screenshot_path and screenshot_path.exists():
                try:
                    screenshot_path.unlink()
                except Exception:
                    pass

            if ean:
                if matched_candidate_ean and matched_candidate_ean == ean:
                    candidate_entry["status"] = "MATCHED"
                    candidate_entry["reason"] = "ean_match"
                elif matched_candidate_ean and matched_candidate_ean != ean:
                    candidate_entry["status"] = "REJECTED"
                    candidate_entry["reason"] = "ean_mismatch"
                elif image_match:
                    candidate_entry["status"] = "MATCHED"
                    candidate_entry["reason"] = "image_match_fallback"
                else:
                    candidate_entry["status"] = "REJECTED"
                    candidate_entry["reason"] = "ean_not_found_and_no_image_match"
            else:
                if matched_candidate_ean:
                    candidate_entry["status"] = "MATCHED"
                    candidate_entry["reason"] = "no_seed_strict"
                else:
                    candidate_entry["status"] = "REJECTED"
                    candidate_entry["reason"] = "no_seed_ean"

            finder_candidates.append(candidate_entry)
            last_candidate_entry = candidate_entry

            if candidate_entry["status"] == "MATCHED":
                final_title = title
                final_price = price
                final_unit_price = unit_price
                final_quantity = quantity
                final_url = current_url
                final_matched_ean = matched_candidate_ean
                final_image_url = image_url
                final_reason = candidate_entry.get("reason")
                break

        fallback_entry = best_token_candidate or last_candidate_entry
        if final_title is None and fallback_entry:
            final_title = fallback_entry.get("title") or fallback_entry.get("listing_label")
        if final_price is None and fallback_entry:
            final_price = fallback_entry.get("price")
        if final_unit_price is None and fallback_entry:
            final_unit_price = fallback_entry.get("unit_price")
        if final_quantity is None and fallback_entry:
            candidate_qty = fallback_entry.get("quantity")
            if not candidate_qty and isinstance(fallback_entry.get("product"), dict):
                candidate_qty = fallback_entry["product"].get("qty")
            final_quantity = candidate_qty
        if final_url is None:
            final_url = page.url or (fallback_entry.get("url") if fallback_entry else None)
        if final_matched_ean is None and fallback_entry:
            final_matched_ean = fallback_entry.get("matched_ean")

        title = final_title
        price = final_price
        unit_price = final_unit_price
        quantity = final_quantity
        matched_ean = final_matched_ean

        # Try to read the current drive label; fallback to the slug in the URL.
        async def current_store_label() -> Optional[str]:
            selectors = [
                "button[data-testid='store-switcher__cta']",
                "button[data-testid='header-store-button']",
                "button[id*='ChoisirMonDrive']",
                "button:has(span.store-espot__title)",
                "button.upper-header__store"
            ]
            for sel in selectors:
                try:
                    node = page.locator(sel).first
                    if await node.count():
                        text = await node.text_content(timeout=1500)
                        if text:
                            cleaned = " ".join(text.split()).strip()
                            if cleaned:
                                return cleaned
                except Exception:
                    continue
            return None

        store_label = await current_store_label()
        if not store_label:
            try:
                parsed = urlparse(store_url)
                slug = parsed.path or ""
                match = re.search(r"magasin-[0-9-]+-([^.]+)", slug, re.IGNORECASE)
                if match:
                    alias = match.group(1).replace('-', ' ').strip()
                    if alias:
                        store_label = f"E.Leclerc Drive · {alias.title()}"
            except Exception:
                store_label = None

        timestamp_note = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        if store_label:
            timestamp_note = f"{timestamp_note} · {store_label}"

        normalized_title = _normalize(title or '')
        token_hits = sum(1 for tok in expected_tokens if tok and tok in normalized_title)
        filtered_token_count = sum(1 for tok in expected_tokens if tok)
        token_threshold = max(1, (filtered_token_count + 1) // 2)

        status = "OK" if price else "NO_PRICE"
        equivalent_flag = False
        difference_note: Optional[str] = None
        tokens_ok = token_hits >= token_threshold if token_threshold else False
        if ean:
            if matched_ean and matched_ean != ean:
                status = "NO_MATCH"
                price = None
                unit_price = None
                difference_note = f"EAN détecté {matched_ean} différent du seed {ean}"
            elif matched_ean is None:
                status = "NO_MATCH"
                price = None
                unit_price = None
                difference_note = "EAN introuvable dans la fiche"
        elif matched_ean is None:
            if not tokens_ok:
                status = "NO_MATCH"
                price = None
                unit_price = None

        if not quantity and isinstance(descriptor_entry, dict):
            quantity = descriptor_entry.get('quantity') or quantity

        # Corriger les incohérences de prix unitaire (ex. €/kg sur un volume en L)
        normalized_unit_price = _normalized_unit_price(price, quantity)
        if normalized_unit_price:
            unit_price = normalized_unit_price

        result_payload = {
            "status": status,
            "title": title,
            "price": price,
            "unit_price": unit_price,
            "quantity": quantity,
            "url": final_url or page.url,
            "matched_ean": matched_ean,
            "store": store_label,
            "note": timestamp_note,
            "debug": {
                "attempted_candidates": len(finder_candidates),
                "final_reason": final_reason,
                "tokens": expected_tokens,
                "elapsed_seconds": round(time.perf_counter()-started, 2),
                "image_match": any(c.get("image_match") for c in finder_candidates if c.get("status") == "MATCHED"),
            },
        }
        meta = result_payload.setdefault("_meta", {})
        meta["supports_keywords"] = True
        if equivalent_flag:
            result_payload["equivalent"] = True
            if difference_note:
                result_payload["difference_note"] = difference_note
                meta["difference_note"] = difference_note
        else:
            result_payload["equivalent"] = False
        if finder_candidates:
            result_payload["candidates"] = finder_candidates
        return result_payload


async def _main() -> None:
    print(f"DEBUG: EAN='{EAN}', QUERY='{QUERY}'")
    result = await run_manual_leclerc(
        query=QUERY,
        ean=EAN,
        store_url=STORE_URL,
        cdp_url=CDP_URL,
        human_delay_ms=HUMAN_DELAY_MS,
        result_delay_ms=RESULT_DELAY_MS,
        pdp_delay_ms=PDP_DELAY_MS,
        type_min_delay=TYPE_MIN_DELAY,
        type_max_delay=TYPE_MAX_DELAY,
    )
    # debug field is only useful when invoked manually; hide by default in CLI
    result.pop("debug", None)
    print(json.dumps(result, ensure_ascii=False))


def run_sync() -> dict:
    """Convenience wrapper for synchronous callers (asyncio already handled)."""

    return asyncio.run(
        run_manual_leclerc(
            query=QUERY,
            ean=EAN,
            store_url=STORE_URL,
            cdp_url=CDP_URL,
            human_delay_ms=HUMAN_DELAY_MS,
            result_delay_ms=RESULT_DELAY_MS,
            pdp_delay_ms=PDP_DELAY_MS,
            type_min_delay=TYPE_MIN_DELAY,
            type_max_delay=TYPE_MAX_DELAY,
        )
    )


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        sys.exit(1)
