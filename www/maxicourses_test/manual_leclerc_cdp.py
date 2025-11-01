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

from datetime import datetime
from pathlib import Path
import re
from urllib.parse import urlparse, urljoin

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
STORE_URL = os.environ.get("STORE_URL", "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx")
CDP_URL = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
HUMAN_DELAY_MS = env_int("LECLERC_HUMAN_DELAY_MS", 300)
RESULT_DELAY_MS = env_int("LECLERC_RESULT_DELAY_MS", 600)
PDP_DELAY_MS = env_int("LECLERC_PDP_DELAY_MS", 400)
TYPE_MIN_DELAY = env_int("LECLERC_TYPE_MIN_MS", 8)
FAST_MODE = os.environ.get("LECLERC_FAST_MODE", "1").lower() in {"1", "true", "yes"}


def _env_delay(name: str, default: int, *, minimum: int = 50) -> int:
    value = env_int(name, default)
    if FAST_MODE:
        value = max(minimum, max(1, value) // 10)
    return value


HUMAN_DELAY_MS = _env_delay("LECLERC_HUMAN_DELAY_MS", 300 if FAST_MODE else 200, minimum=50)
RESULT_DELAY_MS = _env_delay("LECLERC_RESULT_DELAY_MS", 600 if FAST_MODE else 300, minimum=50)
PDP_DELAY_MS = _env_delay("LECLERC_PDP_DELAY_MS", 400 if FAST_MODE else 300, minimum=50)
TYPE_MIN_DELAY = _env_delay("LECLERC_TYPE_MIN_MS", 8 if FAST_MODE else 8, minimum=5)
TYPE_MAX_DELAY = _env_delay("LECLERC_TYPE_MAX_MS", 180 if FAST_MODE else 18, minimum=10)


def _adaptive_delay(ms: int, minimum: int = 100) -> int:
    if FAST_MODE:
        return max(minimum, max(1, ms) // 10)
    return max(minimum, ms)

MANUAL_DESCRIPTOR: dict[str, dict] = {}
try:
    descriptor_path = Path(__file__).with_name("manual_descriptors.json")
    if descriptor_path.exists():
        MANUAL_DESCRIPTOR = json.loads(descriptor_path.read_text(encoding="utf-8"))
except Exception:
    MANUAL_DESCRIPTOR = {}

async def human_pause(page, base_ms: int) -> None:
    jitter = random.randint(-int(base_ms * 0.2), int(base_ms * 0.2))
    await page.wait_for_timeout(max(100, base_ms + jitter))


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
    human_delay_ms: int = 50,
    result_delay_ms: int = 120,
    pdp_delay_ms: int = 70,
    type_min_delay: int = 80,
    type_max_delay: int = 80,
) -> dict:
    """Replay a Leclerc Drive search with human pacing and return a JSON-ready dict."""
    started = time.perf_counter()

    if not (query or ean):
        return {"status": "ERROR", "error": "QUERY is required"}
    if os.environ.get("USE_CDP") != "1":
        return {"status": "ERROR", "error": "SET USE_CDP=1 (Chrome remote obligatoire)"}

    sys.stderr.write(
        f"[LECLERC_DEBUG] FAST_MODE={FAST_MODE} | delays => human:{human_delay_ms}ms "
        f"result:{result_delay_ms}ms pdp:{pdp_delay_ms}ms type:[{type_min_delay},{type_max_delay}] "
        f"query:'{query}'\n"
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
            if len(sanitized) >= 2 and sanitized not in brand_tokens:
                brand_tokens.append(sanitized)
    query_candidates = _build_query_candidates(descriptor_entry, query, ean)
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
    expected_pack_count = 1
    if isinstance(descriptor_entry, dict):
        canonical = descriptor_entry.get("canonical")
        if isinstance(canonical, dict):
            candidate_pack = canonical.get("pack_count")
            if isinstance(candidate_pack, int) and candidate_pack > 1:
                expected_pack_count = candidate_pack

    page: Optional["Page"] = None  # type: ignore[name-defined]

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()

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
        chosen_index = -1
        chosen_label: Optional[str] = None
        chosen_href = ""
        card_html = ""

        search_field = page.locator("input[id*='rechercheTexte']").first
        await search_field.click()
        await human_pause(page, _adaptive_delay(1000))
        sys.stderr.write(f"[LECLERC_DEBUG] after focus -> {time.perf_counter()-started:.2f}s\n")
        await search_field.fill("")
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
        card_count = min(await cards.count(), 8)
        if not card_count:
            sys.stderr.write(f"[LECLERC_DEBUG] no cards after {time.perf_counter()-started:.2f}s\n")
            return {"status": "NO_RESULTS", "query": query}

        expected_tokens = [tok.lower() for tok in query.split() if len(tok) > 2]
        chosen_index = 0
        chosen_label = None
        chosen_href = ""
        chosen_score = -10_000
        for idx in range(card_count):
            try:
                link = cards.nth(idx).locator("a.aWCRS310_Product").first
                label = await link.inner_text(timeout=1500)
                href = await link.get_attribute("href", timeout=1500) or ""
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
            if score > chosen_score:
                chosen_index = idx
                chosen_label = label
                chosen_href = href
                chosen_score = score

        try:
            card_html = await cards.nth(chosen_index).inner_html(timeout=1500)
        except Exception:
            card_html = ""
        sys.stderr.write(f"[LECLERC_DEBUG] chosen href='{chosen_href}' label='{chosen_label}'\n")
        sys.stderr.write(f"[LECLERC_DEBUG] card html snippet:\n{card_html[:500]}...\n")

        card_to_open = cards.nth(chosen_index)
        await card_to_open.locator("a.aWCRS310_Product").first.click()
        try:
            await page.wait_for_url("**/fiche-produits-*.aspx", timeout=6000)
        except PlaywrightTimeoutError:
            if chosen_href:
                pdp_url = urljoin(store_url, chosen_href)
                sys.stderr.write(
                    f"[LECLERC_DEBUG] wait_for_url timeout; navigating to fallback {pdp_url}\n"
                )
                await page.goto(pdp_url, wait_until="domcontentloaded")
            else:
                sys.stderr.write("[LECLERC_DEBUG] wait_for_url timeout and no chosen href\n")
        sys.stderr.write(f"[LECLERC_DEBUG] after PDP navigation -> {time.perf_counter()-started:.2f}s\n")
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
                "elapsed_seconds": round(time.perf_counter()-started, 2),
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
