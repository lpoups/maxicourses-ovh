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
from urllib.parse import quote_plus, urljoin

from rich import print  # noqa: T201
from playwright.async_api import TimeoutError as PlaywrightTimeout

import sys as _sys, os as _os  # noqa: E402
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for  # noqa: E402
from collection_mandate import get_method  # noqa: E402


EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
STORE_URL = (os.environ.get("STORE_URL") or "https://www.coursesu.com/drive-superu-eysines").rstrip("/")
HOME_URL = STORE_URL
STORE_NAME = os.environ.get("STORE_NAME") or "Super U Eysines"
MANDATE = get_method("courseu")

STATE_PATH = state_path_for("courseu")

MANUAL_DESCRIPTOR: dict[str, typing.Any] = {}
try:
    descriptor_path = Path(__file__).with_name("manual_descriptors.json")
    if descriptor_path.exists():
        MANUAL_DESCRIPTOR = json.loads(descriptor_path.read_text(encoding="utf-8"))
except Exception:
    MANUAL_DESCRIPTOR = {}

COURSEU_BASE_URL = "https://www.coursesu.com"


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
            value.replace("€", "")
            .replace("EUR", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .replace(",", ".")
        )
        try:
            return float(cleaned)
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


def _descriptor_tokens(ean: str) -> list[str]:
    tokens: list[str] = []
    entry = MANUAL_DESCRIPTOR.get(ean)
    if isinstance(entry, dict):
        for key in ("brand", "name", "description", "quantity", "seed_query"):
            value = entry.get(key)
            if isinstance(value, str):
                tokens.extend(re.findall(r"[0-9a-zà-öø-ÿ]+", value.lower()))
    return list(dict.fromkeys(tokens))


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
    ]
    for selector in selectors:
        try:
            node = page.locator(selector).first
            if await node.count():
                await node.click()
                await page.wait_for_timeout(300)
        except Exception:
            continue


async def ensure_store(page) -> None:
    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded")
    except PlaywrightTimeout:
        pass
    await accept_cookies(page)
    await close_overlays(page)
    await page.wait_for_timeout(800)


async def perform_search(page, term: str) -> None:
    selectors = [
        "input[type='search'][name*='search']",
        "input[type='search']",
        "input[placeholder*='Rechercher']",
        "input[name='q']",
    ]
    for selector in selectors:
        try:
            input_box = page.locator(selector).first
            if await input_box.count() and await input_box.is_visible():
                await input_box.click()
                await input_box.fill("")
                await input_box.type(term, delay=60)
                await page.keyboard.press("Enter")
                try:
                    await page.wait_for_load_state("networkidle", timeout=12000)
                except PlaywrightTimeout:
                    pass
                await page.wait_for_timeout(1500)
                await accept_cookies(page)
                return
        except Exception:
            continue

    search_url = f"{HOME_URL}/recherche?q={quote_plus(term)}"
    try:
        await page.goto(search_url, wait_until="domcontentloaded")
    except PlaywrightTimeout:
        pass
    await page.wait_for_timeout(1500)
    await accept_cookies(page)


async def open_best_result(page, term: str, ean: str) -> bool:
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
        return False

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, href, link = candidates[0]
    target = href or ""
    if not target:
        try:
            await link.click()
            await page.wait_for_timeout(1200)
            return True
        except Exception:
            return False

    if not target.startswith("http"):
        target = urljoin(COURSEU_BASE_URL, target)
    try:
        await page.goto(target, wait_until="domcontentloaded")
    except PlaywrightTimeout:
        pass
    await page.wait_for_timeout(1200)
    await accept_cookies(page)
    return True


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


async def extract_product_data(page) -> tuple[typing.Optional[str], typing.Optional[str], typing.Optional[str], typing.Optional[str], typing.Optional[str]]:
    price = None
    title = None
    quantity = None
    matched_ean = None

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

    if not matched_ean:
        try:
            body = await page.content()
        except Exception:
            body = ""
        m = re.search(r"(?<!\d)(\d{13})(?!\d)", body or "")
        if m:
            matched_ean = m.group(1)

    if not quantity:
        descriptor = MANUAL_DESCRIPTOR.get(EAN or "")
        if isinstance(descriptor, dict):
            quantity = descriptor.get("quantity") or descriptor.get("seed_primary_quantity")
            if isinstance(quantity, str):
                quantity = _normalize_space(quantity)

    unit_price = _compute_unit_price(price, quantity)
    return price, title, quantity, unit_price, matched_ean


def build_note(store: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{timestamp} · {store}"


async def run() -> Result:
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
        await ensure_store(page)
        await perform_search(page, query)
        opened = await open_best_result(page, query, EAN)
        if not opened:
            note = build_note(STORE_NAME)
            return Result(
                status="NO_RESULTS",
                note=note,
                store=STORE_NAME,
            )

        price, title, quantity, unit_price, matched_ean = await extract_product_data(page)
        final_note = build_note(STORE_NAME)

        if price:
            return Result(
                status="OK",
                price=price,
                unit_price=unit_price,
                quantity=quantity,
                title=title,
                url=page.url,
                note=final_note,
                store=STORE_NAME,
                matched_ean=matched_ean or (EAN if EAN and EAN in (page.url or "") else None),
            )
        return Result(
            status="NO_PRICE",
            title=title,
            quantity=quantity,
            url=page.url,
            note=final_note,
            store=STORE_NAME,
            matched_ean=matched_ean,
        )
    finally:
        try:
            await browser.close()
        except Exception:
            pass
        await p.stop()


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result.__dict__, ensure_ascii=False))
