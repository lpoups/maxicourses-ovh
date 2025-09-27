#!/usr/bin/env python3
"""Fetcher Chronodrive conforme au mandat décrit dans collection_mandate."""
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
import typing
from pathlib import Path
from urllib.parse import quote

from rich import print
import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for
from playwright.async_api import TimeoutError as PlaywrightTimeout

from collection_mandate import get_method

EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
CHRONO_URL = os.environ.get("CHRONO_URL")
MANDATE = get_method("chronodrive")
DEFAULT_STORE_URL = "https://www.chronodrive.com/magasin/le-haillan-422"
STORE_URL = os.environ.get("STORE_URL") or DEFAULT_STORE_URL


MANUAL_DESCRIPTOR: dict[str, typing.Any] = {}
try:
    descriptor_path = Path(__file__).with_name("manual_descriptors.json")
    if descriptor_path.exists():
        MANUAL_DESCRIPTOR = json.loads(descriptor_path.read_text(encoding="utf-8"))
except Exception:
    MANUAL_DESCRIPTOR = {}


def _descriptor_seed(ean: str) -> typing.Optional[str]:
    if not ean:
        return None
    entry = MANUAL_DESCRIPTOR.get(ean)
    if not isinstance(entry, dict):
        return None
    value = entry.get("seed_query")
    if isinstance(value, str) and value.strip():
        return value.strip()
    pieces: list[str] = []
    for key in ("brand", "name", "quantity"):
        field = entry.get(key)
        if isinstance(field, str) and field.strip():
            pieces.append(field.strip())
    if pieces:
        seen: set[str] = set()
        ordered: list[str] = []
        for piece in pieces:
            lower = piece.lower()
            if lower in seen:
                continue
            seen.add(lower)
            ordered.append(piece)
        return " ".join(ordered)
    description = entry.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return None


def build_query_terms() -> list[str]:
    terms: list[str] = []

    def add(term: typing.Optional[str]) -> None:
        if not term:
            return
        candidate = term.strip()
        if not candidate:
            return
        if candidate not in terms:
            terms.append(candidate)

    add(_descriptor_seed(EAN))
    add(QUERY)
    add(EAN)

    return terms


@dataclass
class Result:
    status: str
    price: typing.Optional[str] = None
    title: typing.Optional[str] = None
    url: typing.Optional[str] = None
    note: typing.Optional[str] = None
    unit_price: typing.Optional[str] = None
    quantity: typing.Optional[str] = None
    store: typing.Optional[str] = None
    matched_ean: typing.Optional[str] = None


async def accept_cookies(page) -> None:
    """Dismiss consent banners that may overlay the page."""
    selectors = [
        "#didomi-notice-agree-button",
        "#onetrust-accept-btn-handler",
        "button:has-text('Tout accepter')",
        "button:has-text('Accepter')",
        "button:has-text(\"J'accepte\")",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count():
                await btn.click()
                await page.wait_for_timeout(600)
                break
        except Exception:
            continue


async def extract_store_label(page) -> typing.Optional[str]:
    candidates = [
        "button.upper-header-cta span.label",
        "button.upper-header-cta",
        ".upper-header-info",
    ]
    for sel in candidates:
        try:
            node = page.locator(sel).first
            if await node.count():
                text = await node.text_content(timeout=2000)
                if text:
                    return text.strip()
        except Exception:
            continue
    return None


async def ensure_store_selected(page) -> None:
    if not STORE_URL:
        return
    try:
        await page.goto(STORE_URL, wait_until='domcontentloaded')
        await accept_cookies(page)
        await page.wait_for_timeout(1200)
    except Exception:
        return

    # Mimic the human steps captured in traces: open the header store CTA then
    # close the retailer overlay so the store cookie is persisted.
    try:
        header_btn = page.locator('button.upper-header-cta').first
        if await header_btn.count():
            await header_btn.click()
            await page.wait_for_timeout(600)
            close_btn = page.locator('div.overlay-modal button.ui-cta.overlap-cta').first
            if await close_btn.count():
                await close_btn.click()
                await page.wait_for_timeout(800)
    except Exception:
        pass


async def extract_price_from_page(page) -> tuple[
    typing.Optional[str],
    typing.Optional[str],
    typing.Optional[str],
    typing.Optional[str],
    typing.Optional[str],
]:
    title = None
    price = None
    unit_price = None
    quantity = None
    matched_ean = None

    try:
        title = await page.locator('h1').first.text_content(timeout=6000)
        if title:
            title = re.sub(r'\s+', ' ', title).strip()
            if not quantity:
                m_title = re.search(r'(\d+[\.,]?\d*)\s*(L|KG|G|ML|CL)', title, re.IGNORECASE)
                if m_title:
                    qty_val = m_title.group(1).replace('.', ',')
                    quantity = f"{qty_val} {m_title.group(2).upper()}"
    except Exception:
        pass

    try:
        scripts = page.locator("script[type='application/ld+json']")
        for i in range(await scripts.count()):
            raw = await scripts.nth(i).text_content()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict) and it.get("@type") in ("Product",):
                    if not title and it.get("name"):
                        title = it.get("name")
                    offers = it.get("offers")
                    if isinstance(offers, dict):
                        p = offers.get("price")
                        if p:
                            price = p
                    elif isinstance(offers, list):
                        for of in offers:
                            if isinstance(of, dict) and of.get("price"):
                                price = of.get("price")
                                break
                    quantity = quantity or it.get("size") or it.get("weight")
                    gtin = it.get("gtin13") or it.get("gtin") or it.get("gtin14")
                    if gtin:
                        matched_ean = str(gtin).strip()
    except Exception:
        pass

    html = None
    if not price or not unit_price or not quantity or not matched_ean:
        try:
            html = await page.content()
        except Exception:
            html = None

    if html:
        if not price:
            m_price = re.search(r'"price"\s*:\s*"([0-9.,]+)"', html)
            if m_price:
                price = m_price.group(1)
        if not unit_price:
            m_unit = re.search(r'([0-9.,]+\s*€\s*/\s*(?:l|kg|g|cl|ml))', html, re.IGNORECASE)
            if m_unit:
                unit_price = m_unit.group(1).replace('\xa0', ' ').replace(' /', ' / ')
        if not quantity:
            m_qty = re.search(r'(\d+[\.,]?\d*)\s*(L|KG|G|ML|CL)', html, re.IGNORECASE)
            if m_qty:
                qty_val = m_qty.group(1).replace('.', ',')
                quantity = f"{qty_val} {m_qty.group(2).upper()}"
        if not matched_ean and EAN and EAN in html:
            matched_ean = EAN

    if price:
        price = str(price).replace(',', '.')
        try:
            price = f"{float(price):.2f}".replace('.', ',')
        except Exception:
            price = price.replace('.', ',')

    if unit_price:
        unit_price = (unit_price
                      .replace('\xa0', ' ')
                      .replace('€/l', '€ / L')
                      .replace('€/kg', '€ / KG')
                      .replace('€/g', '€ / G')
                      .replace('€/cl', '€ / CL')
                      .replace('€/ml', '€ / ML')
                      .replace('€/', '€ / '))
        if '€' in unit_price and ' €' not in unit_price:
            unit_price = unit_price.replace('€', ' €', 1)

    if not unit_price and price and quantity:
        m_qty = re.match(r'(\d+[\.,]?\d*)\s*(L|KG)', quantity, re.IGNORECASE)
        if m_qty:
            try:
                value = float(m_qty.group(1).replace(',', '.'))
                if value > 0:
                    unit = 'L' if m_qty.group(2).upper() == 'L' else 'KG'
                    per_unit = float(price.replace(',', '.')) / value
                    per_unit_str = f"{per_unit:.2f}".replace('.', ',')
                    unit_price = f"{per_unit_str} € / {unit}"
            except Exception:
                pass

    return title, price, unit_price, quantity, matched_ean


async def run() -> Result:
    storage_state = state_path_for('chronodrive')
    p, browser, context, page = await make_context(
        headless=HEADLESS, proxy=PROXY, storage_state_path=storage_state,
        user_agent=None,
    )

    # If direct PDP URL provided
    if CHRONO_URL:
        try:
            await page.goto(CHRONO_URL, wait_until='domcontentloaded')
        except PlaywrightTimeout:
            await browser.close(); await p.stop()
            return Result(status='TIMEOUT')
        # Accept cookies
        try:
            for sel in ["#onetrust-accept-btn-handler", "button:has-text('Tout accepter')", "button:has-text('Accepter')"]:
                await page.locator(sel).first.click(timeout=1500)
        except Exception:
            pass
        title, price, unit_price, quantity, matched_ean = await extract_price_from_page(page)
        await browser.close(); await p.stop()
        store_label = 'Chronodrive Le Haillan'
        if price:
            return Result(
                status='OK',
                price=price,
                title=title,
                url=page.url,
                note=store_label,
                unit_price=unit_price,
                quantity=quantity,
                store=store_label,
                matched_ean=matched_ean,
            )
        return Result(status='NO_PRICE', title=title, url=page.url, note=store_label, store=store_label)

    # Otherwise search by terms
    terms = build_query_terms()
    if not terms:
        await browser.close(); await p.stop()
        return Result(status='NO_QUERY')

    # Visit a store to set location if provided
    await ensure_store_selected(page)

    search_base = "https://www.chronodrive.com/search/{}"

    for term in terms:
        encoded_term = quote(term, safe="")
        search_url = search_base.format(encoded_term)

        try:
            await page.goto(search_url, wait_until='domcontentloaded')
        except PlaywrightTimeout:
            continue

        await accept_cookies(page)
        await page.wait_for_timeout(800)

        try:
            await page.wait_for_selector('article.product-card', timeout=12000)
        except PlaywrightTimeout:
            continue

        cards = page.locator('article.product-card')
        count = await cards.count()
        if count == 0:
            continue

        term_tokens = [t for t in re.split(r"[^a-z0-9]+", term.lower()) if t]
        best_idx = None
        best_score = -1

        for idx in range(count):
            card = cards.nth(idx)
            link = card.locator('a.card-extra-link').first
            href = (await link.get_attribute('href')) or ''
            try:
                card_title = await card.locator('.card-title').first.inner_text(timeout=1000)
            except Exception:
                try:
                    card_title = await link.inner_text()
                except Exception:
                    card_title = ''
            haystack = f"{href} {card_title}".lower()

            score = 0
            if EAN and EAN in haystack:
                score += 100
            for tok in term_tokens:
                if tok in haystack:
                    score += 1

            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx is None:
            continue

        try:
            target_link = cards.nth(best_idx).locator('a.card-extra-link').first
            href = await target_link.get_attribute('href') or ''
            if not href:
                continue
            target = href if href.startswith('http') else f"https://www.chronodrive.com{href}"
            await page.goto(target, wait_until='domcontentloaded')
            await accept_cookies(page)
            await page.wait_for_timeout(1200)
        except Exception:
            continue

        title, price, unit_price, quantity, matched_ean = await extract_price_from_page(page)
        store_label = await extract_store_label(page) or 'Chronodrive Le Haillan'

        if matched_ean is None and EAN and EAN in (page.url or ''):
            matched_ean = EAN

        if not quantity and matched_ean == EAN and re.search(r'1[\.,]?75', term):
            quantity = '1,75 L'

        await browser.close(); await p.stop()
        if price:
            return Result(
                status='OK',
                price=price,
                title=title,
                url=page.url,
                note=store_label,
                unit_price=unit_price,
                quantity=quantity,
                store=store_label,
                matched_ean=matched_ean,
            )
        return Result(status='NO_PRICE', title=title, url=page.url, note=store_label, store=store_label, matched_ean=matched_ean)

    await browser.close(); await p.stop()
    return Result(status='NO_RESULTS')


if __name__ == '__main__':
    res = asyncio.run(run())
    print(json.dumps(res.__dict__, ensure_ascii=False))
