#!/usr/bin/env python3
"""Human-paced Leclerc Drive lookup via Chrome 9222.

- Connects to an already running Chrome started with ``start_chrome_debug.sh``.
- Types the query slowly (human-like), waits for results, opens the best match,
  then extracts price/unit/URL from the PDP.
- Exposes :func:`run_manual_leclerc` for reuse inside other scripts.

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


async def human_pause(page, base_ms: int) -> None:
    jitter = random.randint(-int(base_ms * 0.2), int(base_ms * 0.2))
    await page.wait_for_timeout(max(400, base_ms + jitter))


def _normalize(text: str) -> str:
    return " ".join(text.lower().split()) if text else ""


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
    if not query:
        return {"status": "ERROR", "error": "QUERY is required"}
    if os.environ.get("USE_CDP") != "1":
        return {"status": "ERROR", "error": "SET USE_CDP=1 (Chrome remote obligatoire)"}

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
        chosen_score = -1
        for idx in range(card_count):
            try:
                label = await cards.nth(idx).locator("a.aWCRS310_Product").first.inner_text(timeout=5000)
            except Exception:
                continue
            score = sum(1 for tok in expected_tokens if tok in _normalize(label))
            if score > chosen_score:
                chosen_index = idx
                chosen_label = label
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

        return {
            "status": "OK" if price else "NO_PRICE",
            "title": title,
            "price": price,
            "unit_price": unit_price,
            "quantity": quantity,
            "url": page.url,
            "matched_ean": matched_ean or ean or None,
            "debug": {
                "chosen_index": chosen_index,
                "chosen_label": chosen_label,
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
