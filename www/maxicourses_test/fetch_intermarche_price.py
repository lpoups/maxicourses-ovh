#!/usr/bin/env python3
"""Fetcher Intermarché respectant le mandat de collecte."""
import asyncio
import json
import os
import re
import sys
import typing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from rich import print
import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for

from collection_mandate import get_method

EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
HOME_URL = os.environ.get("HOME_URL", "https://www.intermarche.com/accueil")
MANDATE = get_method("intermarche")

DEFAULT_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.120 Safari/537.36"
DEFAULT_HEADERS = {
    "sec-ch-ua": '"Chromium";v="127", "Not(A:Brand";v="24", "Google Chrome";v="127"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "upgrade-insecure-requests": "1",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.5",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
}

MANUAL_DESCRIPTOR = {}
try:
    descriptor_path = Path(__file__).with_name("manual_descriptors.json")
    if descriptor_path.exists():
        MANUAL_DESCRIPTOR = json.loads(descriptor_path.read_text(encoding="utf-8"))
except Exception:
    MANUAL_DESCRIPTOR = {}


def _descriptor_seed(ean: str) -> typing.Optional[str]:
    """Compose the human search phrase stored in the manual descriptors table."""
    if not ean:
        return None
    entry = MANUAL_DESCRIPTOR.get(ean)
    if not isinstance(entry, dict):
        return None
    if entry.get("seed_query"):
        return entry.get("seed_query").strip() or None
    pieces = []
    for key in ("brand", "name", "quantity"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            pieces.append(value.strip())
    if pieces:
        return " ".join(pieces)
    if isinstance(entry.get("description"), str) and entry["description"].strip():
        return entry["description"].strip()
    return None


def build_query_terms() -> list[str]:
    """Return search terms in priority order (descriptor first, EAN last)."""
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
    if QUERY and QUERY != EAN:
        add(QUERY)

    descriptor = MANUAL_DESCRIPTOR.get(EAN) if EAN else None
    if isinstance(descriptor, dict):
        extras = descriptor.get("alternate_queries")
        if isinstance(extras, (list, tuple)):
            for extra in extras:
                if isinstance(extra, str):
                    add(extra)

    if not terms and QUERY:
        add(QUERY)  # fallback even if it equals the EAN
    if not terms and EAN:
        add(EAN)

    return terms


@dataclass
class Result:
    status: str
    price: typing.Optional[str] = None
    title: typing.Optional[str] = None
    url: typing.Optional[str] = None
    note: typing.Optional[str] = None
    matched_ean: typing.Optional[str] = None


COOKIE_SELECTORS = [
    "button:has-text('Tout accepter')",
    "button:has-text('Accepter')",
    "button:has-text(\"J'accepte\")",
    "#onetrust-accept-btn-handler",
    "#didomi-notice-agree-button",
]


PRODUCT_LINK_SELECTORS = [
    "a[href*='/produit/']",
    "a[href*='/product/']",
    "a[href*='/catalogue/']",
    "a[href*='/p/']",
]


async def click_first(page, selectors: typing.Sequence[str]) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1500):
                await loc.click()
                return True
        except Exception:
            continue
    return False


async def perform_site_search(page, term: str) -> bool:
    """Try to perform a search via the site search box instead of direct navigation."""
    search_selectors = [
        "input[type='search']",
        "input[name='search']",
        "input[placeholder*='Rechercher']",
        "input[aria-label*='Rechercher']",
    ]
    for sel in search_selectors:
        try:
            field = page.locator(sel).first
            if await field.is_visible(timeout=2000):
                await field.fill(term)
                await field.press('Enter')
                await page.wait_for_load_state('domcontentloaded')
                await page.wait_for_timeout(1200)
                return True
        except Exception:
            continue
    return False


async def accept_cookies(page) -> None:
    for sel in COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                return
        except Exception:
            pass
    try:
        await page.evaluate(
            """
            (() => {
              const labels = ['tout accepter', 'accepter', "j'accepte", 'ok'];
              const buttons = [...document.querySelectorAll('button')];
              for (const b of buttons) {
                const txt = (b.innerText || '').trim().toLowerCase();
                if (labels.some(l => txt.includes(l))) {
                  b.click();
                  return;
                }
              }
            })();
            """
        )
    except Exception:
        pass


async def ensure_store_selected(page) -> None:
    try:
        # Depending on the flow Intermarché may show a store selection modal
        if await page.locator("[data-testid='store-modal']").is_visible(timeout=2000):
            await click_first(page, [
                "[data-testid='store-modal'] button:has-text('Valider')",
                "[data-testid='store-modal'] button:has-text('Sélectionner')",
                "[data-testid='store-modal'] button:has-text('Choisir ce magasin')",
            ])
            await page.wait_for_load_state('domcontentloaded')
            return
    except Exception:
        pass
    try:
        await click_first(page, [
            "button:has-text('Choisir mon magasin')",
            "button:has-text('Mon magasin')",
            "button:has-text('Choisir ce magasin')",
            "button:has-text('Sélectionner ce magasin')",
        ])
    except Exception:
        pass


async def ensure_home(page) -> bool:
    """If a 404 / lost page is shown, click the button to return home."""
    try:
        lost = page.locator("text=Vous êtes perdus dans nos rayons")
        if await lost.count():
            btn = page.locator("button:has-text(\"Revenir à l'accueil\")")
            if await btn.count():
                await btn.click()
                await page.wait_for_load_state('domcontentloaded')
                await page.wait_for_timeout(800)
                return True
    except Exception:
        pass
    return False


async def open_search_ui(page) -> bool:
    """Try to open the search box if it is hidden behind a button."""
    candidates = [
        "button[aria-label*='Recher']",
        "button:has-text('Rechercher')",
        "button:has-text('Recherche')",
        "[data-testid='search-button']",
        "[class*='search'] button",
    ]
    for sel in candidates:
        try:
            btn = page.locator(sel).first
            if await btn.count() and await btn.is_enabled():
                await btn.click()
                await page.wait_for_timeout(400)
                inputs = await page.locator("input[type='search']").count()
                if inputs:
                    return True
        except Exception:
            continue
    # Search input sometimes already visible
    if await page.locator("input[type='search']").count():
        return True
    if await page.locator("input[placeholder*='Lait']").count():
        return True
    return False


async def perform_search(page, term: str) -> bool:
    """Drive the real site search instead of hitting endpoints directly."""
    search_selectors = [
        "input[type='search']",
        "input[name='search']",
        "input[placeholder*='Rechercher']",
        "input[aria-label*='Rechercher']",
        "input[placeholder*='Lait']",
    ]

    for sel in search_selectors:
        try:
            field = page.locator(sel).first
            if await field.count():
                try:
                    await field.fill('', timeout=2000)
                except Exception:
                    await page.evaluate("(sel)=>{const el=document.querySelector(sel); if(el){el.value='';}}", sel)
                await page.wait_for_timeout(80)
                try:
                    await field.type(term, delay=35, timeout=2000)
                except Exception:
                    await page.evaluate(
                        "(sel,val)=>{const el=document.querySelector(sel); if(el){el.value=val; el.dispatchEvent(new Event('input',{bubbles:true}));}}",
                        sel,
                        term,
                    )
                await page.wait_for_timeout(400)
                await page.keyboard.press('Enter')
                try:
                    await page.wait_for_load_state('networkidle')
                except Exception:
                    await page.wait_for_load_state('domcontentloaded')
                await page.wait_for_timeout(1500)
                return True
        except Exception:
            continue
    return False


async def run() -> Result:
    storage_state = state_path_for('intermarche')
    p, browser, context, page = await make_context(
        headless=HEADLESS, proxy=PROXY, storage_state_path=storage_state,
        user_agent=DEFAULT_UA,
    )

    try:
        await context.set_extra_http_headers(DEFAULT_HEADERS)
    except Exception:
        pass

    home_url = HOME_URL or "https://www.intermarche.com/"
    try:
        await page.goto(home_url, wait_until="networkidle")
    except Exception:
        try:
            await page.goto(home_url, wait_until="domcontentloaded")
        except Exception:
            pass
    if await ensure_home(page):
        await ensure_home(page)  # second chance if redirected twice
    await accept_cookies(page)
    await ensure_store_selected(page)

    # Build search terms: prefer QUERY text
    terms = build_query_terms()
    if not terms:
        await browser.close(); await p.stop()
        return Result(status="NO_QUERY")

    price = None
    title = None
    pdp = None
    matched_ean = None
    normalized_query_tokens: list[str] = []
    for term in terms:
        candidate_tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", term.lower())
            if len(token) >= 3 and not token.isdigit()
        ]
        if candidate_tokens:
            normalized_query_tokens = candidate_tokens
            break
    for term in terms:
        # Try to run the actual site search workflow (SPA)
        await ensure_home(page)
        await open_search_ui(page)
        performed = await perform_search(page, term)
        if not performed:
            # Fallback: navigate via /recherche endpoints (may trigger Datadome)
            search_candidates = [
                f"https://www.intermarche.com/recherche/{quote(term)}",
                f"https://www.intermarche.com/recherche?text={quote(term)}",
                f"https://www.intermarche.com/recherche?text={quote(term)}&trier=relevance",
            ]
            search_url = None
            for candidate in search_candidates:
                try:
                    resp = await page.goto(candidate, wait_until="domcontentloaded")
                except Exception:
                    continue
                search_url = candidate
                await page.wait_for_timeout(1000)
                html = (await page.content()).lower()
                if 'captcha-delivery.com' in html or 'datadome' in html or (resp and resp.status == 403):
                    continue
                has_product = False
                for sel in PRODUCT_LINK_SELECTORS:
                    try:
                        if await page.locator(sel).count() > 0:
                            has_product = True
                            break
                    except Exception:
                        continue
                if has_product:
                    break
                search_url = None
            if not search_url:
                continue

        pdp = None
        candidates: list[str] = []
        for sel in PRODUCT_LINK_SELECTORS:
            try:
                items = page.locator(sel)
                count = await items.count()
                for idx in range(min(count, 8)):
                    href = await items.nth(idx).get_attribute('href')
                    if not href:
                        continue
                    if href.startswith('/'):
                        href = f"https://www.intermarche.com{href}"
                    if href not in candidates:
                        candidates.append(href)
            except Exception:
                continue

        if EAN:
            preferred = [href for href in candidates if EAN in href]
            if preferred:
                others = [href for href in candidates if href not in preferred]
                candidates = preferred + others

        matched_href = None
        fallback_href = None
        for href in candidates:
            try:
                await page.goto(href, wait_until='domcontentloaded')
                await page.wait_for_timeout(800)
                html = await page.content()
                if EAN and (EAN in href or EAN in html):
                    matched_href = href
                    break
                if not fallback_href:
                    fallback_href = href
            except Exception:
                continue
        pdp = matched_href or fallback_href
        if not pdp:
            continue
        # ensure we are on the product page corresponding to pdp
        if page.url != pdp:
            try:
                await page.goto(pdp, wait_until='domcontentloaded')
                await page.wait_for_timeout(500)
            except Exception:
                pass
        await accept_cookies(page)
        await ensure_store_selected(page)
        await accept_cookies(page)
        await ensure_store_selected(page)

        matched_gtin = False
        # Try schema.org
        try:
            for i in range(await page.locator("script[type='application/ld+json']").count()):
                raw = await page.locator("script[type='application/ld+json']").nth(i).text_content()
                data = json.loads(raw)
                items = data if isinstance(data, list) else [data]
                for it in items:
                    if isinstance(it, dict) and it.get("@type") in ("Product",):
                        gtin = it.get("gtin13") or it.get("gtin") or it.get("gtin14")
                        if EAN and gtin and str(gtin).strip() == EAN:
                            matched_gtin = True
                            matched_ean = str(gtin).strip()
                        if EAN and gtin and str(gtin).strip() != EAN:
                            continue
                        title = it.get("name") or title
                        offers = it.get("offers")
                        if isinstance(offers, dict):
                            price = price or offers.get("price")
                        elif isinstance(offers, list):
                            for of in offers:
                                if isinstance(of, dict):
                                    price = price or of.get("price")
                        if EAN and gtin and str(gtin).strip() == EAN:
                            matched_href = pdp
        except Exception:
            pass

        heuristics_ok = False
        if title and normalized_query_tokens:
            normalized_title = re.sub(r"\s+", " ", title.lower())
            hits = sum(1 for token in normalized_query_tokens if token in normalized_title)
            if hits >= max(1, len(normalized_query_tokens) // 2):
                heuristics_ok = True

        if EAN:
            canonical = None
            try:
                canonical = await page.locator("link[rel='canonical']").first.get_attribute('href')
            except Exception:
                canonical = None
            html = await page.content()
            has_ean = (canonical and EAN in canonical) or (EAN in pdp if pdp else False) or False
            if not has_ean:
                has_ean = EAN in html
            if has_ean:
                matched_ean = EAN
            if not matched_gtin and not has_ean and not heuristics_ok:
                price = None
                title = None
                pdp = None
                continue

        # Try to read price from dedicated data attributes
        if not price:
            try:
                data_price_node = page.locator("[data-testid='product-price'], [data-test='product-price']").first
                price_text = await data_price_node.text_content(timeout=5000)
                if price_text:
                    price_text = price_text.strip().replace('\xa0', ' ')
                    m = re.search(r"(\d+[\.,]\d{2})", price_text)
                    if m:
                        price = m.group(1).replace(',', '.')
            except Exception:
                pass

        # Fallback DOM
        if not price:
            try:
                txt = await page.locator("*[class*='price'], [data-testid*='price']").first.text_content(timeout=6000)
                if txt:
                    txt = txt.strip().replace('\xa0', ' ')
                    m = re.search(r"(\d+[\.,]\d{2})\s*€", txt)
                    if m:
                        price = m.group(1).replace(',', '.')
            except Exception:
                pass

        if price:
            break

    await browser.close(); await p.stop()
    if price and pdp:
        try:
            price = f"{float(str(price).replace(',', '.')):.2f}"
        except Exception:
            price = str(price)
        price = price.replace('.', ',')
        manual = MANUAL_DESCRIPTOR.get(EAN)
        quantity = None
        if manual:
            quantity = manual.get('quantity')
        return Result(status="OK", price=price, title=title, url=pdp, note=None, matched_ean=matched_ean,)
    if pdp:
        return Result(status="NO_PRICE", title=title, url=pdp, matched_ean=matched_ean)
    return Result(status="NO_RESULTS")


if __name__ == "__main__":
    res = asyncio.run(run())
    print(json.dumps(res.__dict__, ensure_ascii=False))
