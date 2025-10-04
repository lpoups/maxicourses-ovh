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
import sys
from typing import Optional

from datetime import datetime
from pathlib import Path
import re
from urllib.parse import urlparse

from playwright.async_api import async_playwright


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
STORE_URL = os.environ.get("STORE_URL", "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx")
CDP_URL = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
HUMAN_DELAY_MS = env_int("LECLERC_HUMAN_DELAY_MS", 5000)
RESULT_DELAY_MS = env_int("LECLERC_RESULT_DELAY_MS", 12000)
PDP_DELAY_MS = env_int("LECLERC_PDP_DELAY_MS", 7000)
TYPE_MIN_DELAY = env_int("LECLERC_TYPE_MIN_MS", 80)
TYPE_MAX_DELAY = env_int("LECLERC_TYPE_MAX_MS", 180)

MANUAL_DESCRIPTOR: dict[str, dict] = {}
try:
    descriptor_path = Path(__file__).with_name("manual_descriptors.json")
    if descriptor_path.exists():
        MANUAL_DESCRIPTOR = json.loads(descriptor_path.read_text(encoding="utf-8"))
except Exception:
    MANUAL_DESCRIPTOR = {}


async def human_pause(page, base_ms: int) -> None:
    jitter = random.randint(-int(base_ms * 0.2), int(base_ms * 0.2))
    await page.wait_for_timeout(max(400, base_ms + jitter))


def _normalize(text: str) -> str:
    return " ".join(text.lower().split()) if text else ""


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [tok for tok in re.split(r"[^0-9a-zà-öø-ÿ]+", text.lower()) if len(tok) >= 2]


GENERIC_TOKENS = {
    "lot", "lots", "pack", "format", "ml", "g", "kg", "cl", "l", "sans", "avec",
    "capsules", "capsule", "pcs", "piece", "pieces", "unit", "unite", "unites",
}


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

    brand_lower = None
    if isinstance(descriptor_entry, dict):
        brand_value = descriptor_entry.get('brand') or ''
        brand_tokens = _tokenize(brand_value)
        for token in brand_tokens:
            if token in {'savora', 'amora'}:
                brand_lower = token
                break
        if not brand_lower:
            name_tokens = _tokenize(descriptor_entry.get('name'))
            for token in name_tokens:
                if token in {'savora', 'amora'}:
                    brand_lower = token
                    break
        if brand_lower:
            add(f"moutarde {brand_lower}")
            quantity = (descriptor_entry.get('seed_primary_quantity') or descriptor_entry.get('quantity') or '').strip()
            quantity_token = re.sub(r"\s+", '', quantity.lower())
            if quantity_token:
                add(f"moutarde {brand_lower} {quantity_token}")
        add(descriptor_entry.get('seed_query'))
        queries = descriptor_entry.get('leclerc_queries')
        if isinstance(queries, list):
            for q in queries:
                add(q)
        add(descriptor_entry.get('leclerc_query'))
    add(fallback_query)
    if ean:
        add(ean)

    trimmed: List[str] = []
    for query in candidates:
        if len(query) <= 45:
            trimmed.append(query)
            continue
        pieces = []
        for token in query.split():
            tentative = " ".join(pieces + [token]) if pieces else token
            if len(tentative) <= 45:
                pieces.append(token)
            else:
                break
        trimmed.append(" ".join(pieces) if pieces else query[:45])
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
    if ean and ean in haystack:
        score += 100
    for tok in query_tokens:
        if tok in haystack:
            score += 6
    for tok in descriptor_tokens:
        if tok in haystack:
            score += 3
    if 'supremo' in descriptor_tokens and 'supremo' not in haystack:
        score -= 60
    brand_present = False
    for tok in brand_tokens:
        if tok and tok in haystack:
            score += 30
            brand_present = True
    if brand_tokens and not brand_present:
        score -= 80
    if descriptor_numbers:
        card_numbers = set(_numeric_tokens(label) + _numeric_tokens(href))
        if card_numbers & set(descriptor_numbers):
            score += 10
        else:
            score -= 25
    return score


def _numeric_tokens(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return re.findall(r"\d+", text)


async def run_manual_leclerc(
    *,
    query: str,
    ean: str,
    store_url: str,
    cdp_url: str = "http://127.0.0.1:9222",
    human_delay_ms: int = 5000,
    result_delay_ms: int = 12000,
    pdp_delay_ms: int = 7000,
    type_min_delay: int = 80,
    type_max_delay: int = 180,
) -> dict:
    """Replay a Leclerc Drive search with human pacing and return a JSON-ready dict."""
    if not (query or ean):
        return {"status": "ERROR", "error": "QUERY is required"}
    if os.environ.get("USE_CDP") != "1":
        return {"status": "ERROR", "error": "SET USE_CDP=1 (Chrome remote obligatoire)"}

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
            if len(sanitized) >= 2 and sanitized not in brand_tokens:
                brand_tokens.append(sanitized)
    query_candidates = _build_query_candidates(descriptor_entry, query, ean)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()

        await page.goto(store_url, wait_until="domcontentloaded")
        await human_pause(page, human_delay_ms)

        # Cookie consent (OneTrust) if visible
        try:
            consent_button = page.locator("#onetrust-accept-btn-handler")
            if await consent_button.count():
                await consent_button.click()
                await human_pause(page, 3000)
        except Exception:
            pass

        search_field = page.locator("input[id*='rechercheTexte']").first
        await search_field.click()
        await human_pause(page, 1000)
        await search_field.fill("")
        await human_pause(page, 1000)
        for ch in query:
            await search_field.type(ch, delay=random.randint(type_min_delay, type_max_delay))
        await human_pause(page, 1200)
        await search_field.press("Enter")
        await page.wait_for_load_state("networkidle")
        await human_pause(page, result_delay_ms)

        cards = page.locator("li.liWCRS310_Product")
        card_count = await cards.count()
        if not card_count:
            return {"status": "NO_RESULTS", "query": query}

        expected_tokens = [tok.lower() for tok in query.split() if len(tok) > 2]
        chosen_index = 0
        chosen_label = None
        chosen_href = ""
        chosen_score = -10_000
        for idx in range(card_count):
            try:
                link = cards.nth(idx).locator("a.aWCRS310_Product").first
                label = await link.inner_text(timeout=5000)
                href = await link.get_attribute("href") or ""
            except Exception:
                continue
            score = _score_card(
                label or "",
                href,
                expected_tokens,
                descriptor_tokens,
                descriptor_numbers,
                brand_tokens,
                ean,
            )
            if score > chosen_score:
                chosen_index = idx
                chosen_label = label
                chosen_href = href
                chosen_score = score

        card_to_open = cards.nth(chosen_index)
        async with page.expect_navigation(wait_until="domcontentloaded"):
            await card_to_open.locator("a.aWCRS310_Product").first.click()
        await human_pause(page, pdp_delay_ms)

        title = await page.locator("h1").first.text_content()
        title = title.strip() if title else None

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

        whole = await text_clean(".prix .prix-actuel-partie-entiere, .pWCRS310_PrixUnitairePartieEntiere") or ""
        decimal = await text_clean(".prix .prix-actuel-partie-decimale, .pWCRS310_PrixUnitairePartieDecimale") or ""
        whole_digits = "".join(filter(str.isdigit, whole))
        decimal_digits = "".join(filter(str.isdigit, decimal))[:2]
        price = f"{int(whole_digits)}.{decimal_digits or '00'}" if whole_digits else None
        if price:
            price = price.replace('.', ',')

        unit_price = await text_clean(".prix .prix-detail, .pWCRS310_PrixUniteMesure")
        quantity = None
        if unit_price and "€" in unit_price:
            quantity = await text_clean(".spanWCRS310_ContenanceInfo")
        if not quantity:
            quantity = await text_clean(".ficheProduit__infos--poids")
        if quantity:
            quantity = quantity.upper()

        matched_ean = None
        try:
            html = await page.content()
            if ean and ean in html:
                matched_ean = ean
        except Exception:
            matched_ean = None

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
        token_threshold = max(2, len([tok for tok in expected_tokens if tok]) // 2 or 1)

        status = "OK" if price else "NO_PRICE"
        if matched_ean is None:
            if price and token_hits >= token_threshold:
                status = "OK"
            else:
                status = "NO_MATCH"
                price = None
                unit_price = None

        if not quantity and isinstance(descriptor_entry, dict):
            quantity = descriptor_entry.get('quantity') or quantity

        return {
            "status": status,
            "title": title,
            "price": price,
            "unit_price": unit_price,
            "quantity": quantity,
            "url": page.url,
            "matched_ean": matched_ean,
            "store": store_label,
            "note": timestamp_note,
            "debug": {
                "chosen_index": chosen_index,
                "chosen_label": chosen_label,
                "chosen_href": chosen_href,
                "tokens": expected_tokens,
            },
        }


async def _main() -> None:
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
