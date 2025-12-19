#!/usr/bin/env python3
"""Fetcher Course U (Super U Eysines) respectant le mandat de collecte."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import typing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import html as html_module

from rich import print  # noqa: T201
from playwright.async_api import TimeoutError as PlaywrightTimeout

import sys as _sys, os as _os  # noqa: E402
_sys.path.append(_os.path.dirname(__file__))
_sys.path.append(_os.path.join(_os.path.dirname(__file__), "pipeline"))
from pipeline.engine import make_context, state_path_for  # noqa: E402
from collection_mandate import get_method  # noqa: E402
from pipeline.nutriscore import extract_nutriscore_from_html  # noqa: E402
from seed_catalog import get_seed  # noqa: E402
from descriptor_store import get_descriptor  # noqa: E402


EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
STORE_URL = (os.environ.get("STORE_URL") or "https://www.coursesu.com/drive-superu-eysines").rstrip("/")
HOME_URL = STORE_URL
STORE_NAME = os.environ.get("STORE_NAME") or "Super U Eysines"
MANDATE = get_method("courseu")
DIRECT_URL = (os.environ.get("DIRECT_URL") or "").strip()
SKIP_SEARCH = (os.environ.get("SKIP_SEARCH") or "0").lower() in {"1", "true", "yes"}

STATE_PATH = state_path_for("courseu")

COURSEU_BASE_URL = "https://www.coursesu.com"
DESCRIPTOR = get_descriptor(EAN) if EAN else {}


@dataclass
class Result:
    status: str
    price: typing.Optional[str] = None
    unit_price: typing.Optional[str] = None
    quantity: typing.Optional[str] = None
    title: typing.Optional[str] = None
    url: typing.Optional[str] = None
    note: typing.Optional[str] = None
    store: typing.Optional[str] = None
    matched_ean: typing.Optional[str] = None
    nutriscore_grade: typing.Optional[str] = None
    nutriscore_image: typing.Optional[str] = None


def _normalize_space(value: typing.Optional[str]) -> typing.Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _to_decimal(value: typing.Any) -> typing.Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = (
            value.replace("EUR", "")
            .replace("\u202f", " ")
            .replace("€", " ")
        )
        cleaned = re.sub(r"[^\d,.\-]+", " ", cleaned)
        cleaned = cleaned.replace(",", ".")
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def _format_price(value: typing.Any) -> typing.Optional[str]:
    numeric = _to_decimal(value)
    if numeric is None:
        return None
    return f"{numeric:.2f}".replace(".", ",")


def _compute_unit_price(price: typing.Any, quantity: typing.Optional[str]) -> typing.Optional[str]:
    total = _to_decimal(price)
    if total is None or total <= 0 or not quantity:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|l|ml)", quantity, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    if unit == "g":
        value = value / 1000.0
        unit = "kg"
    elif unit == "ml":
        value = value / 1000.0
        unit = "l"
    if value <= 0:
        return None
    per_unit = total / value
    formatted = _format_price(per_unit)
    if not formatted:
        return None
    unit_label = "KG" if unit == "kg" else "L" if unit == "l" else unit.upper()
    return f"{formatted} € / {unit_label}"


def _final_matched_ean(candidate: typing.Optional[str]) -> typing.Optional[str]:
    target = (EAN or "").strip()
    if target:
        return target
    return candidate


def _descriptor_tokens(ean: str) -> list[str]:
    tokens: list[str] = []
    seed_entry = get_seed(ean)
    if isinstance(seed_entry, dict):
        text_fields = (
            "brand",
            "name",
            "description",
            "quantity",
            "seed_primary_name",
            "seed_query",
        )
        for key in text_fields:
            value = seed_entry.get(key)
            if isinstance(value, str):
                tokens.extend(re.findall(r"[0-9a-zà-öø-ÿ]+", value.lower()))
        for list_key in ("primary_keywords", "secondary_keywords"):
            values = seed_entry.get(list_key)
            if isinstance(values, (list, tuple)):
                for item in values:
                    if isinstance(item, str):
                        tokens.extend(re.findall(r"[0-9a-zà-öø-ÿ]+", item.lower()))
    return list(dict.fromkeys(tokens))


def _descriptor_entry(ean: str) -> dict[str, typing.Any]:
    entry = get_seed(ean)
    return entry if isinstance(entry, dict) else {}


def _store_courseu_hint(ean: str, url: str) -> None:
    # manual_descriptors.json deprecated: do nothing
    return


async def accept_cookies(page) -> None:
    selectors = [
        "#onetrust-accept-btn-handler",
        "button#ot-sdk-btn-accept-all",
        "button:has-text('Tout accepter')",
        "button:has-text(\"J'accepte\")",
        "button:has-text('Accepter')",
        "[data-testid='cookie-accept']",
    ]
    for selector in selectors:
        try:
            node = page.locator(selector).first
            if await node.count():
                await node.click()
                await page.wait_for_timeout(500)
                break
        except Exception:
            continue


async def close_overlays(page) -> None:
    selectors = [
        "button[aria-label='Fermer']",
        "button:has-text('Fermer')",
        "button:has-text('Continuer sans accepter')",
        "button.su-modal__close",
        "div[data-testid='modal'] button[aria-label='Fermer']",
        ".modal button[aria-label='Fermer']",
    ]
    for selector in selectors:
        try:
            node = page.locator(selector).first
            if await node.count():
                await node.click()
                await page.wait_for_timeout(300)
        except Exception:
            continue
    # Fallback: force-remove Course U marketing mask that blocks pointer events.
    try:
        await page.evaluate(
            """
            () => {
                const selectors = [
                    '.mask',
                    '.modal-backdrop',
                    '.suu-mask',
                    '.suu-modal',
                    '[data-testid="su-modal"]',
                ];
                let removed = false;
                for (const selector of selectors) {
                    document.querySelectorAll(selector).forEach((node) => {
                        node.remove();
                        removed = true;
                    });
                }
                if (removed) {
                    const body = document.body;
                    if (body && body.style.overflow === 'hidden') {
                        body.style.overflow = '';
                    }
                }
            }
            """
        )
        await page.wait_for_timeout(200)
    except Exception:
        pass


async def ensure_store(page) -> None:
    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded")
    except PlaywrightTimeout:
        pass
    await accept_cookies(page)
    await close_overlays(page)
    await page.wait_for_timeout(800)
    await _dump_html(page, "home")


async def refresh_home(page) -> None:
    try:
        await page.reload(wait_until="domcontentloaded")
    except PlaywrightTimeout:
        pass
    await accept_cookies(page)
    await close_overlays(page)
    await page.wait_for_timeout(500)


async def open_search_box(page) -> None:
    toggles = [
        "[data-search-wrapper] button[data-search-loupe]",
        "button[data-search-loupe]",
        "button[data-search-button]",
        "button:has-text('Rechercher')",
        "button[aria-label*='Rechercher']",
    ]
    for selector in toggles:
        try:
            button = page.locator(selector).first
            if not await button.count():
                continue
            await button.click(force=True)
            await page.wait_for_timeout(250)
            await accept_cookies(page)
            await close_overlays(page)
            break
        except Exception as exc:
            _debug_log(f"search toggle {selector} failed: {exc}")
            continue


DEBUG = os.environ.get("DEBUG_COURSEU") == "1"
HTML_DUMP = os.environ.get("COURSEU_DUMP")


def _debug_log(message: str) -> None:
    if DEBUG:
        sys.stderr.write(f"[COURSEU_DEBUG] {message}\n")


async def _dump_html(page, label: str) -> None:
    if not HTML_DUMP:
        return
    try:
        content = await page.content()
    except Exception as exc:
        _debug_log(f"dump_html failed ({label}): {exc}")
        return
    path = Path(HTML_DUMP)
    if path.is_dir():
        path.mkdir(parents=True, exist_ok=True)
        output = path / f"{label}.html"
    else:
        output = Path(HTML_DUMP)
        output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.write_text(content, encoding="utf-8")
        _debug_log(f"dumped HTML to {output}")
    except Exception as exc:
        _debug_log(f"cannot write dump {output}: {exc}")


async def _is_cf_block(page) -> bool:
    try:
        text = await page.inner_text("body", timeout=2000)
    except Exception:
        return False
    lowered = text.lower()
    if "you are unable to access" in lowered or "you have been blocked" in lowered:
        return True
    if "cloudflare" in lowered and "ray id" in lowered:
        return True
    return False


async def perform_search(page, term: str) -> None:
    await open_search_box(page)
    selectors = [
        "input[type='search'][name*='search']",
        "input[type='search']",
        "input[placeholder*='Rechercher']",
        "input[name='q']",
    ]
    for selector in selectors:
        try:
            await page.wait_for_selector(selector, state="attached", timeout=6000)
            success = await page.eval_on_selector(
                selector,
                """
                (input, value) => {
                    if (!input) {
                        return false;
                    }
                    const form = input.form || input.closest('form');
                    input.focus();
                    input.value = value;
                    const events = ['input', 'change'];
                    for (const type of events) {
                        input.dispatchEvent(new Event(type, { bubbles: true }));
                    }
                    if (form) {
                        if (form.requestSubmit) {
                            form.requestSubmit();
                        } else {
                            form.submit();
                        }
                    } else {
                        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                        input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                    }
                    return true;
                }
                """,
                term,
            )
            if success:
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeout:
                    pass
                await page.wait_for_timeout(1500)
                await accept_cookies(page)
                await close_overlays(page)
                return
        except Exception as exc:
            _debug_log(f"search selector {selector} failed: {exc}")
            continue

    _debug_log("fallback to direct search URL")
    search_url = f"{HOME_URL}/recherche?q={quote_plus(term)}"
    try:
        await page.goto(search_url, wait_until="domcontentloaded")
    except PlaywrightTimeout:
        _debug_log("direct search timeout")
        pass
    await page.wait_for_timeout(1500)
    await accept_cookies(page)
    await _dump_html(page, f"results_{term}")


def _html_is_cf_block(html: str | None) -> bool:
    if not html:
        return False
    lowered = html.lower()
    if "attention required" in lowered and "cloudflare" in lowered:
        return True
    if "sorry, you have been blocked" in lowered:
        return True
    if "cf-error-details" in lowered:
        return True
    if "cloudflare ray id" in lowered:
        return True
    return False


async def open_best_result(page, term: str, ean: str) -> tuple[bool, typing.Optional[str]]:
    tokens = re.findall(r"[0-9a-zà-öø-ÿ]+", term.lower())
    descriptor_tokens = _descriptor_tokens(ean)
    selectors = [
        "a[href*='/p/']",
        "article a[href*='/product']",
        "li a.product-tile__link",
        "div.product-tile a",
    ]
    candidates: list[tuple[int, str, typing.Any]] = []
    for selector in selectors:
        try:
            links = page.locator(selector)
            count = await links.count()
        except Exception:
            continue
        for idx in range(count):
            link = links.nth(idx)
            try:
                href = await link.get_attribute("href") or ""
            except Exception:
                href = ""
            text = ""
            try:
                text = await link.inner_text(timeout=1000)
            except Exception:
                pass
            haystack = f"{href} {text}".lower()
            score = 0
            if ean and ean in haystack:
                score += 200
            for tok in tokens:
                if tok and tok in haystack:
                    score += 5
            for tok in descriptor_tokens:
                if tok and tok in haystack:
                    score += 3
            if score > 0 or ean and ean in haystack:
                candidates.append((score, href, link))
    if not candidates and selectors:
        try:
            fallback_link = page.locator("a[href*='/p/']").first
            if await fallback_link.count():
                href = await fallback_link.get_attribute("href") or ""
                candidates.append((1, href, fallback_link))
        except Exception:
            pass

    if not candidates:
        return False, None

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, href, link = candidates[0]
    target = href or ""
    if not target:
        try:
            await link.click()
            await page.wait_for_timeout(250)
            snapshot = await page.content()
            await accept_cookies(page)
            await close_overlays(page)
            if _html_is_cf_block(snapshot):
                return False, None
            return True, snapshot
        except Exception:
            return False, None

    if not target.startswith("http"):
        target = urljoin(COURSEU_BASE_URL, target)
    try:
        await page.goto(target, wait_until="commit")
    except PlaywrightTimeout:
        pass
    await page.wait_for_timeout(250)
    snapshot = await page.content()
    await accept_cookies(page)
    await close_overlays(page)
    if _html_is_cf_block(snapshot):
        return False, None
    return True, snapshot


async def open_descriptor_product(page, ean: str) -> tuple[bool, typing.Optional[str]]:
    entry = _descriptor_entry(ean)
    hint = entry.get("courseu_url") or entry.get("courseu_slug")
    if not hint:
        return False, None

    if isinstance(hint, str):
        hint = hint.strip()
    if not hint:
        return False, None

    product_url = hint
    if not product_url.startswith("http"):
        product_url = urljoin(COURSEU_BASE_URL, hint.lstrip("/"))

    _debug_log(f"trying descriptor URL {product_url}")
    try:
        await page.goto(product_url, wait_until="commit")
    except PlaywrightTimeout:
        pass
    await page.wait_for_timeout(200)
    snapshot = await page.content()
    await accept_cookies(page)
    await close_overlays(page)
    if _html_is_cf_block(snapshot):
        preview = (snapshot[:160] + "...") if snapshot else ""
        _debug_log(f"descriptor snapshot is CF block (preview={preview})")
        return False, None

    current_url = page.url or ""
    if "/p/" in current_url or "/product" in current_url or snapshot:
        return True, snapshot
    _debug_log(f"descriptor URL did not resolve to PDP ({current_url})")
    return False, None


def _iter_product_nodes(data: typing.Any) -> typing.Iterator[dict]:
    if isinstance(data, dict):
        node_type = data.get("@type")
        if node_type == "Product" or (isinstance(node_type, list) and "Product" in node_type):
            yield data
        for value in data.values():
            yield from _iter_product_nodes(value)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_product_nodes(item)


def _extract_from_html_source(html_source: str) -> tuple[typing.Optional[str], typing.Optional[str], typing.Optional[str], typing.Optional[str]]:
    price = None
    title = None
    quantity = None
    matched_ean = None
    pattern = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(html_source):
        raw = html_module.unescape(match.group(1).strip())
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for product in _iter_product_nodes(payload):
            if not isinstance(product, dict):
                continue
            if not title:
                title = _normalize_space(product.get("name"))
            offers = product.get("offers")
            if isinstance(offers, list):
                offers = next((item for item in offers if isinstance(item, dict)), None)
            if isinstance(offers, dict) and price is None:
                raw_price = offers.get("price") or offers.get("priceValue")
                candidate = _format_price(raw_price)
                if candidate:
                    price = candidate
            if not quantity:
                quantity = _normalize_space(product.get("size") or product.get("weight"))
            if not matched_ean:
                for key in ("gtin13", "gtin", "sku"):
                    value = product.get(key)
                    if isinstance(value, str) and re.fullmatch(r"\d{13}", value.strip()):
                        matched_ean = value.strip()
                        break
    if not title:
        title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_source, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = _normalize_space(re.sub(r"<[^>]+>", "", html_module.unescape(title_match.group(1))))
    if not price:
        data_price = re.search(r'data-item-price="([0-9]+(?:[.,][0-9]+)?)"', html_source)
        if data_price:
            price = _format_price(data_price.group(1))
    if not price:
        price_match = re.search(r"(\d+[.,]\d+)\s*[€EUR]", html_source)
        if price_match:
            price = _format_price(price_match.group(1))
    if not quantity:
        quantity_match = re.search(r"(\d+[.,]?\d*)\s*(g|kg|ml|l)\b", html_source, re.IGNORECASE)
        if quantity_match:
            quantity = _normalize_space(f"{quantity_match.group(1)} {quantity_match.group(2)}")
    if not matched_ean:
        ean_match = re.search(r"(?<!\d)(\d{13})(?!\d)", html_source)
        if ean_match:
            matched_ean = ean_match.group(1)
    return price, title, quantity, matched_ean


async def extract_product_data(page, snapshot: typing.Optional[str] = None) -> tuple[
    typing.Optional[str],
    typing.Optional[str],
    typing.Optional[str],
    typing.Optional[str],
    typing.Optional[str],
    typing.Optional[str],
    typing.Optional[str],
]:
    price = None
    title = None
    quantity = None
    matched_ean = None
    nutri_grade = None
    nutri_image = None

    if snapshot:
        price, title, quantity, matched_ean = _extract_from_html_source(snapshot)
        nutri_grade, nutri_image = extract_nutriscore_from_html(snapshot, base_url=page.url)

    scripts = page.locator("script[type='application/ld+json']")
    count = 0
    try:
        count = await scripts.count()
    except Exception:
        count = 0
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
        for product in _iter_product_nodes(payload):
            if not isinstance(product, dict):
                continue
            if not title:
                title = _normalize_space(product.get("name"))
            offers = product.get("offers")
            if isinstance(offers, list):
                offers = next((item for item in offers if isinstance(item, dict)), None)
            if isinstance(offers, dict) and price is None:
                raw_price = offers.get("price") or offers.get("priceValue")
                price_candidate = _format_price(raw_price)
                if price_candidate:
                    price = price_candidate
            quantity = quantity or _normalize_space(product.get("size") or product.get("weight"))
            if not matched_ean:
                for key in ("gtin13", "gtin", "sku"):
                    value = product.get(key)
                    if isinstance(value, str) and re.fullmatch(r"\d{13}", value):
                        matched_ean = value
                        break
        if price and title:
            break

    if not title:
        try:
            title = await page.locator("h1").first.text_content()
            title = _normalize_space(title)
        except Exception:
            title = None

    if not price:
        selectors = [
            ".product-price",
            ".price-sales",
            "[data-testid='product-price']",
            "span[itemprop='price']",
        ]
        for selector in selectors:
            try:
                node = page.locator(selector).first
                if await node.count():
                    raw_price = await node.inner_text()
                    candidate = _format_price(raw_price)
                    if candidate:
                        price = candidate
                        break
            except Exception:
                continue

    if not matched_ean or not nutri_grade:
        body = snapshot
        if not body:
            try:
                body = await page.content()
            except Exception:
                body = ""
        m = re.search(r"(?<!\d)(\d{13})(?!\d)", body or "")
        if m:
            matched_ean = m.group(1)
        if not nutri_grade:
            guess_grade, guess_image = extract_nutriscore_from_html(body, base_url=page.url)
            if guess_grade:
                nutri_grade = guess_grade
            if guess_image:
                nutri_image = guess_image

    if not quantity and isinstance(DESCRIPTOR, dict):
        quantity = DESCRIPTOR.get("quantity") or DESCRIPTOR.get("seed_primary_quantity")
        if isinstance(quantity, str):
            quantity = _normalize_space(quantity)

    unit_price = _compute_unit_price(price, quantity)
    return price, title, quantity, unit_price, matched_ean, nutri_grade, nutri_image


def build_note(store: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{timestamp} · {store}"


async def _collect_once(use_cdp: bool) -> Result:
    prev_cdp = os.environ.get("USE_CDP")
    os.environ["USE_CDP"] = "1" if use_cdp else "0"
    try:
        query = EAN or QUERY
        if not query:
            return Result(status="NO_QUERY", note="Query required")

        p, browser, context, page = await make_context(
            headless=HEADLESS,
            proxy=PROXY,
            storage_state_path=STATE_PATH,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        try:
            async def _block_cf_scripts(route, request):
                url = request.url
                if "cdn-cgi/challenge-platform" in url:
                    ctype = "application/javascript" if url.endswith(".js") else "text/plain"
                    await route.fulfill(status=204, body="", headers={"content-type": ctype})
                    return
                await route.continue_()

            await context.route("**/cdn-cgi/challenge-platform/**", _block_cf_scripts)
            await ensure_store(page)
            await refresh_home(page)

            if DIRECT_URL:
                direct_snapshot = None
                try:
                    await page.goto(DIRECT_URL, wait_until="commit")
                except PlaywrightTimeout:
                    pass
                await page.wait_for_timeout(200)
                direct_snapshot = await page.content()
                await accept_cookies(page)
                await close_overlays(page)
                price, title, quantity, unit_price, matched_ean, nutri_grade, nutri_image = await extract_product_data(page, direct_snapshot)
                final_note = build_note(STORE_NAME)
                if price:
                    result = Result(
                        status="OK",
                        price=price,
                        unit_price=unit_price,
                        quantity=quantity,
                        title=title,
                        url=page.url,
                        note=final_note,
                        store=STORE_NAME,
                        matched_ean=_final_matched_ean(matched_ean or (EAN if EAN and EAN in (page.url or "") else None)),
                        nutriscore_grade=nutri_grade,
                        nutriscore_image=nutri_image,
                    )
                    if EAN and page.url:
                        _store_courseu_hint(EAN, page.url)
                    return result
                if SKIP_SEARCH:
                    status = "CF_BLOCK" if await _is_cf_block(page) else "NO_PRICE"
                    return Result(
                        status=status,
                        title=title,
                        quantity=quantity,
                        url=page.url,
                        note=final_note,
                        store=STORE_NAME,
                        matched_ean=_final_matched_ean(matched_ean),
                        nutriscore_grade=nutri_grade,
                        nutriscore_image=nutri_image,
                    )

            search_term = EAN or query
            await perform_search(page, search_term)
            opened, snapshot = await open_best_result(page, search_term, EAN)
            if not opened and query and query != search_term:
                await perform_search(page, query)
                opened, snapshot = await open_best_result(page, query, EAN)
            if not opened:
                note = build_note(STORE_NAME)
                status = "CF_BLOCK" if await _is_cf_block(page) else "NO_RESULTS"
                return Result(
                    status=status,
                    note=note,
                    store=STORE_NAME,
                )

            price, title, quantity, unit_price, matched_ean, nutri_grade, nutri_image = await extract_product_data(page, snapshot)
            final_note = build_note(STORE_NAME)

            if price:
                result = Result(
                    status="OK",
                    price=price,
                    unit_price=unit_price,
                    quantity=quantity,
                    title=title,
                    url=page.url,
                    note=final_note,
                    store=STORE_NAME,
                    matched_ean=_final_matched_ean(matched_ean or (EAN if EAN and EAN in (page.url or "") else None)),
                    nutriscore_grade=nutri_grade,
                    nutriscore_image=nutri_image,
                )
                if EAN and page.url:
                    _store_courseu_hint(EAN, page.url)
                return result
            status = "CF_BLOCK" if await _is_cf_block(page) else "NO_PRICE"
            return Result(
                status=status,
                title=title,
                quantity=quantity,
                url=page.url,
                note=final_note,
                store=STORE_NAME,
                matched_ean=_final_matched_ean(matched_ean),
                nutriscore_grade=nutri_grade,
                nutriscore_image=nutri_image,
            )
        finally:
            try:
                await browser.close()
            except Exception:
                pass
            await p.stop()
    finally:
        if prev_cdp is None:
            os.environ.pop("USE_CDP", None)
        else:
            os.environ["USE_CDP"] = prev_cdp


async def run() -> Result:
    initial_cdp = os.environ.get("USE_CDP", "0") == "1"
    result = await _collect_once(initial_cdp)
    if result.status == "CF_BLOCK" and initial_cdp:
        _debug_log("CF_BLOCK detected with CDP; retrying with standalone Playwright browser")
        fallback = await _collect_once(False)
        return fallback
    return result


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result.__dict__, ensure_ascii=False))
