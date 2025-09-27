#!/usr/bin/env python3
"""Fetcher Auchan conforme au mandat centralisé (collection_mandate)."""
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
import typing
from pathlib import Path

# Keep Rich pretty print for local debugging but default to stderr logging so
# stdout remains valid JSON for the pipeline consumer.
from rich import print
import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for
from playwright.async_api import TimeoutError as PlaywrightTimeout
from urllib.parse import urljoin

from collection_mandate import get_method

EAN = os.environ.get("EAN", "7613035676497").strip()
QUERY = os.environ.get("QUERY")
AUCHAN_URL = os.environ.get("AUCHAN_URL")  # direct PDP url if known
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
HOME_URL = os.environ.get("HOME_URL", "https://www.auchan.fr")
MANDATE = get_method("auchan")

MANUAL_DESCRIPTOR = {}
try:
    descriptor_path = Path(__file__).with_name("manual_descriptors.json")
    if descriptor_path.exists():
        MANUAL_DESCRIPTOR = json.loads(descriptor_path.read_text(encoding="utf-8"))
except Exception:
    MANUAL_DESCRIPTOR = {}


@dataclass
class Result:
    status: str
    price: typing.Optional[str] = None
    title: typing.Optional[str] = None
    url: typing.Optional[str] = None
    note: typing.Optional[str] = None
    unit_price: typing.Optional[str] = None
    quantity: typing.Optional[str] = None
    matched_ean: typing.Optional[str] = None
    image: typing.Optional[str] = None


def log(message: str) -> None:
    """Emit debug information on stderr so stdout stays JSON."""
    try:
        sys.stderr.write(f"[auchan] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


async def accept_cookies(page) -> None:
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
                await page.wait_for_timeout(800)
                break
        except Exception:
            continue


async def _extract_from_pdp(page) -> typing.Optional[Result]:
    title = None
    price = None
    matched_ean = None
    unit_price = None
    quantity = None
    image_url = None

    try:
        title = await page.locator('h1').first.text_content(timeout=5000)
    except Exception:
        pass

    try:
        scripts = page.locator("script[type='application/ld+json']")
        for i in range(await scripts.count()):
            raw = await scripts.nth(i).text_content()
            try:
                data = json.loads(raw)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict) and it.get('@type') == 'Product':
                    offers = it.get('offers')
                    if isinstance(offers, dict) and offers.get('price'):
                        price = offers.get('price')
                    elif isinstance(offers, list):
                        for of in offers:
                            if isinstance(of, dict) and of.get('price'):
                                price = price or of.get('price')
                    gtin = it.get('gtin13') or it.get('gtin') or it.get('gtin14')
                    if gtin:
                        matched_ean = gtin.strip()
                    quantity = it.get('size') or it.get('weight') or quantity
                    if not image_url and it.get('image'):
                        image_data = it.get('image')
                        if isinstance(image_data, list) and image_data:
                            image_url = image_data[0]
                        elif isinstance(image_data, str):
                            image_url = image_data
    except Exception:
        pass

    html = None
    if price is None or unit_price is None or quantity is None:
        try:
            html = await page.content()
        except Exception:
            html = None

    if price is None and html:
        for pattern in [r"(\d+[\.,]\d{2})\s*€", r"price\"\s*:\s*\"?(\d+[\.,]\d{2})"]:
            m = re.search(pattern, html)
            if m:
                price = m.group(1).replace(',', '.')
                break

    if html:
        if matched_ean is None and EAN and EAN in html:
            matched_ean = EAN
        if quantity is None:
            mqty = re.search(r"(\d+[\.,]?\d*)\s*(L|l|KG|kg|G|g|CL|cl|ML|ml)", html)
            if mqty:
                quantity = f"{mqty.group(1).replace(',', '.')} {mqty.group(2).upper()}"
        if unit_price is None:
            munit = re.search(r"(\d+[\.,]\d{2})\s*€\s*/\s*(?:L|l|kg|KG|G|g)", html)
            if munit:
                value = munit.group(1).replace(',', '.')
                unit = munit.group(0).split('/')[-1].strip().upper()
                unit_price = value + f" € / {unit}"

    if html and not image_url:
        m_img = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
        if m_img:
            image_url = m_img.group(1)

    if not price:
        return None

    try:
        price = f"{float(str(price).replace(',', '.')):.2f}"
    except Exception:
        price = str(price)

    if unit_price is None and quantity:
        qty_match = re.match(r"(\d+[\.,]?\d*)\s*(L|KG|G)", quantity, re.IGNORECASE)
        if qty_match:
            try:
                raw_value = float(qty_match.group(1).replace(',', '.'))
                unit = qty_match.group(2).upper()
                if raw_value > 0:
                    if unit == 'L':
                        unit_price = f"{float(price) / raw_value:.2f} € / L"
                    elif unit == 'KG':
                        unit_price = f"{float(price) / raw_value:.2f} € / KG"
                    elif unit == 'G':
                        kg = raw_value / 1000
                        if kg > 0:
                            unit_price = f"{float(price) / kg:.2f} € / KG"
            except Exception:
                pass

    manual = MANUAL_DESCRIPTOR.get(EAN)
    if manual:
        quantity = manual.get('quantity') or quantity

    price_out = price.replace('.', ',') if price else price
    unit_out = unit_price
    if unit_price and '€' in unit_price:
        amount, sep, tail = unit_price.partition(' €')
        if amount:
            unit_out = amount.replace('.', ',') + sep + tail

    return Result(
        status="OK",
        price=price_out,
        title=title,
        url=page.url,
        note="Auchan (CDP)",
        unit_price=unit_out,
        quantity=quantity,
        matched_ean=matched_ean or (EAN if EAN and EAN in page.url else None),
        image=image_url,
    )


async def run_via_playwright() -> typing.Optional[Result]:
    search_terms = [t for t in [QUERY, EAN] if t]
    if not search_terms:
        return Result(status="NO_QUERY")

    storage_state = state_path_for('auchan')
    p, browser, context, page = await make_context(
        headless=HEADLESS,
        proxy=PROXY,
        storage_state_path=None if os.environ.get('USE_CDP') == '1' else storage_state,
        user_agent=None,
    )

    try:
        try:
            await page.goto(HOME_URL, wait_until='domcontentloaded')
        except Exception:
            pass
        await page.wait_for_timeout(1500)
        await accept_cookies(page)

        for term in search_terms:
            log(f"recherche '{term}'")
            # locate search input
            search_input = page.locator("form#search input.header-search__input").first
            if not await search_input.count():
                continue
            try:
                await search_input.click()
                await search_input.fill('')
                await page.wait_for_timeout(200)
                await search_input.type(term, delay=80)
                await page.wait_for_timeout(100)
                search_btn = page.locator("form#search button[type='submit']").first
                if await search_btn.count():
                    await search_btn.click()
                else:
                    await page.keyboard.press('Enter')
            except Exception:
                continue

            try:
                await page.wait_for_load_state('domcontentloaded')
            except PlaywrightTimeout:
                pass
            await page.wait_for_timeout(3000)

            # iterate results
            try:
                hrefs = await page.eval_on_selector_all(
                    "a[href*='/produit'], a[href*='/pr-']",
                    "els => els.map(el => el.getAttribute('href'))"
                )
            except Exception:
                hrefs = []
            hrefs = [h.strip() for h in hrefs if h]
            log(f"résultats trouvés: {len(hrefs)}")
            for href in hrefs[:8]:
                if ('/pr-' not in href) and ('/pr/' not in href) and ('/produit/' not in href):
                    continue
                if href.startswith('/'):
                    href = urljoin('https://www.auchan.fr', href)
                try:
                    await page.goto(href, wait_until='domcontentloaded')
                    await page.wait_for_timeout(3000)
                except Exception:
                    continue

                log(f"ouverture {href}")

                html = await page.content()
                if EAN and EAN not in href and EAN not in html:
                    continue

                result = await _extract_from_pdp(page)
                if result:
                    await browser.close()
                    await p.stop()
                    return result

            # si aucune fiche valide, revenir home
            try:
                await page.goto(HOME_URL, wait_until='domcontentloaded')
                await page.wait_for_timeout(1500)
                await accept_cookies(page)
            except Exception:
                pass
    finally:
        try:
            await browser.close()
            await p.stop()
        except Exception:
            pass

    return None


async def run_http() -> Result:
    storage_state = state_path_for('auchan')
    p, browser, context, page = await make_context(
        headless=HEADLESS, proxy=PROXY, storage_state_path=storage_state,
        user_agent=None,
    )
    try:
        if AUCHAN_URL:
            try:
                await page.goto(AUCHAN_URL, wait_until='domcontentloaded')
            except PlaywrightTimeout:
                return Result(status="TIMEOUT")
            except Exception:
                return Result(status="ERROR")

            try:
                for sel in [
                    "#didomi-notice-agree-button",
                    "#onetrust-accept-btn-handler",
                    "button:has-text('Tout accepter')",
                    "button:has-text('Accepter')",
                    "button:has-text(\"J'accepte\")",
                ]:
                    await page.locator(sel).first.click(timeout=1500)
            except Exception:
                pass

            title = None
            price = None
            try:
                title = await page.locator('h1').first.text_content(timeout=6000)
            except Exception:
                pass
            try:
                for i in range(await page.locator("script[type='application/ld+json']").count()):
                    raw = await page.locator("script[type='application/ld+json']").nth(i).text_content()
                    data = json.loads(raw)
                    items = data if isinstance(data, list) else [data]
                    for it in items:
                        if isinstance(it, dict) and it.get("@type") in ("Product",):
                            offers = it.get("offers")
                            if isinstance(offers, dict):
                                price = price or offers.get("price")
                            elif isinstance(offers, list):
                                for of in offers:
                                    if isinstance(of, dict):
                                        price = price or of.get("price")
            except Exception:
                pass
            if not price:
                try:
                    html = await page.content()
                    m = re.search(r"(\d+[\.,]\d{2})\s*€", html or '')
                    if m:
                        price = m.group(1).replace(',', '.')
                except Exception:
                    pass
            if price:
                try:
                    price = f"{float(price):.2f}"
                except Exception:
                    price = str(price)
                return Result(status="OK", price=price, title=title, url=page.url)
            return Result(status="NO_PRICE", title=title, url=page.url)

        return Result(status="NO_RESULTS")
    finally:
        try:
            await browser.close()
            await p.stop()
        except Exception:
            pass


async def run() -> Result:
    prefer_playwright = (
        os.environ.get('USE_CDP') == '1'
        or os.environ.get('AUCHAN_USE_PLAYWRIGHT') == '1'
        or not HEADLESS
    )

    if prefer_playwright:
        result = await run_via_playwright()
        if result:
            return result

    return await run_http()


if __name__ == "__main__":
    res = asyncio.run(run())
    print(json.dumps(res.__dict__, ensure_ascii=False))
