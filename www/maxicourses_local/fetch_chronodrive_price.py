#!/usr/bin/env python3
"""Fetcher Chronodrive conforme au mandat décrit dans collection_mandate."""
import asyncio
import json
import os
import re
import sys
import random
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
from seed_catalog import all_seeds  # noqa: E402
from pipeline.nutriscore import extract_nutriscore_from_html  # noqa: E402

EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
CHRONO_URL = os.environ.get("CHRONO_URL")
MANDATE = get_method("chronodrive")
DEFAULT_STORE_URL = "https://www.chronodrive.com/magasin/le-haillan-422"
STORE_URL = os.environ.get("STORE_URL") or DEFAULT_STORE_URL

CHRONO_SEARCH_API = "https://api.chronodrive.com/v1/search-suggestions"
CHRONO_PRODUCT_API = "https://api.chronodrive.com/v1/products/{product_id}"
CHRONO_API_SEARCH_KEY = "49a29e90-6842-4b90-8d09-07222f40b3ed"
CHRONO_API_PRODUCT_KEY = "34bfe4e1-82d1-458a-9a51-61198fff84b3"
CHRONO_SITE_ID = "1006"
CHRONO_SITE_MODE = "DRIVE"
CHRONO_DEVICE_TYPE = "WEB"

MANUAL_DESCRIPTOR: dict[str, typing.Any] = all_seeds()


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
    seen: set[str] = set()

    def add(term: typing.Optional[str]) -> None:
        if not term:
            return
        cleaned = " ".join(term.strip().split())
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        terms.append(cleaned)

    # Toujours commencer par la recherche EAN brute
    if EAN:
        add(EAN)

    descriptor_entry = MANUAL_DESCRIPTOR.get(EAN) if EAN else None

    if isinstance(descriptor_entry, dict):
        primary = descriptor_entry.get("primary_keywords")
        if isinstance(primary, (list, tuple)):
            for keyword in primary:
                add(keyword)

    if not terms:
        add(_descriptor_seed(EAN))
    if not terms:
        add(QUERY)

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
    nutriscore_grade: typing.Optional[str] = None
    nutriscore_image: typing.Optional[str] = None


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
                await page.wait_for_timeout(1000)
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
                text = await node.text_content(timeout=1000)
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


def _normalize_term_for_typing(term: str) -> str:
    term = term.replace('+', ' ').strip()
    term = re.sub(r"\s+", " ", term)
    return term


async def _type_search_query(page, term: str, submit: bool = True) -> bool:
    typed = _normalize_term_for_typing(term)
    if not typed:
        return False
    toggle_selectors = [
        "div[role='search'] button",
        "button[data-automation='search-toggle']",
        "button[aria-label*='Rechercher']",
    ]
    for sel in toggle_selectors:
        btn = page.locator(sel).first
        try:
            if await btn.count():
                try:
                    await btn.click()
                except Exception:
                    try:
                        await btn.click(force=True)
                    except Exception:
                        try:
                            await btn.evaluate("el => el.click()")
                        except Exception:
                            continue
                await page.wait_for_timeout(260)
                break
        except Exception:
            continue
    selectors = [
        "input#search-input",
        "input[name='search']",
        "input[type='search']",
        "input[data-automation='search-input']",
        "form[role='search'] input",
        "input[placeholder*='Je cherche']",
    ]
    target = None
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if await loc.count():
                target = loc
                break
        except Exception:
            continue
    if target is None:
        # force-open the header search if the DOM toggle failed
        try:
            await page.evaluate(
                "(() => { const root = document.querySelector('div.search');"
                " if (root) { root.classList.add('is-open'); }"
                " const form = document.querySelector('form.header-search');"
                " if (form) { form.classList.add('is-open'); } })()"
            )
        except Exception:
            pass
        target = page.locator("form.header-search input").first
        try:
            if target and await target.count():
                await target.evaluate(
                    "el => { el.style.opacity = '1'; el.style.maxWidth = '100%'; }"
                )
        except Exception:
            pass
        if target is None or not await target.count():
            return False
    try:
        try:
            await target.click()
        except Exception:
            await target.click(force=True)
        await target.fill("")
    except Exception:
        return False
    try:
        await page.evaluate(
            "(() => { const root = document.querySelector('div.search');"
            " if (root) { root.classList.add('is-open'); }"
            " const form = document.querySelector('form.header-search');"
            " if (form) { form.classList.add('is-open'); form.classList.add('-active'); } })()"
        )
    except Exception:
        pass
    for ch in typed:
        try:
            await target.type(ch, delay=random.randint(35, 75))
        except Exception:
            return False
    await page.wait_for_timeout(random.randint(200, 350))
    if not submit:
        return True
    submit_selectors = [
        "form[role='search'] button[type='submit']",
        "form[role='search'] .cta.-icon-only",
        "button[data-automation='search-submit']",
    ]
    pressed = False
    try:
        await target.press("Enter")
        pressed = True
    except Exception:
        pressed = False
    if not pressed:
        for sel in submit_selectors:
            btn = page.locator(sel).first
            try:
                if await btn.count():
                    await btn.click()
                    pressed = True
                    break
            except Exception:
                continue
    if not pressed:
        return False
    return True


async def _click_best_suggestion(page, term_tokens: list[str], descriptor_tokens: list[str]) -> bool:
    links = page.locator("#site-search a")
    count = 0
    for _ in range(8):
        try:
            count = await links.count()
        except Exception:
            count = 0
        if count:
            break
        await page.wait_for_timeout(350)
    if not count:
        try:
            html = await page.evaluate("() => document.querySelector('#site-search')?.innerHTML || ''")
            Path('chronodrive_suggestion_debug.html').write_text(html, encoding='utf-8')
        except Exception:
            pass
        sys.stderr.write("[CHRONO_DEBUG] suggestions-timeout\n")
        return False
    sys.stderr.write(f"[CHRONO_DEBUG] suggestions={count}\n")
    GENERIC_TOKENS = {"boisson", "gazeuse", "ajouter", "panier", "frais"}
    best_idx = None
    best_score = -999
    for idx in range(count):
        link = links.nth(idx)
        try:
            href = await link.get_attribute("href") or ""
        except Exception:
            href = ""
        if not href or href.startswith("/search"):
            continue
        text = ""
        try:
            text = await link.inner_text(timeout=800)
        except Exception:
            text = ""
        haystack = f"{href} {text}".lower()
        score = 0
        if EAN and EAN in haystack:
            score += 200
        for tok in term_tokens:
            if tok and tok not in GENERIC_TOKENS and tok in haystack:
                score += 8
        for tok in descriptor_tokens:
            if tok and tok not in GENERIC_TOKENS and tok in haystack:
                score += 4
        if "original" in haystack:
            score += 6
        if "zero" in haystack or "sans sucre" in haystack:
            score -= 50
        if best_idx is None or score > best_score:
            best_idx = idx
            best_score = score
    if best_idx is None:
        return False
    sys.stderr.write(f"[CHRONO_DEBUG] suggestion_choice idx={best_idx} score={best_score}\n")
    try:
        await links.nth(best_idx).click()
    except Exception:
        try:
            await links.nth(best_idx).click(force=True)
        except Exception:
            return False
    try:
        await page.wait_for_load_state("domcontentloaded")
    except PlaywrightTimeout:
        pass
    await page.wait_for_timeout(900)
    return True


async def _submit_search(page) -> bool:
    try:
        await page.keyboard.press("Enter")
        return True
    except Exception:
        pass
    submit_selectors = [
        "form[role='search'] button[type='submit']",
        "form[role='search'] .cta.-icon-only",
        "button[data-automation='search-submit']",
    ]
    for sel in submit_selectors:
        btn = page.locator(sel).first
        try:
            if await btn.count():
                await btn.click()
                return True
        except Exception:
            continue
    return False


def _product_score(product: dict, term_tokens: list[str], descriptor_tokens: list[str], negatives: set[str]) -> int:
    score = 0
    eans = product.get("eans") or []
    labels = product.get("labels") or {}
    haystack_parts = [
        " ".join(eans),
        labels.get("productLabel", ""),
        labels.get("brandLabel", ""),
        labels.get("brandLineLabel", ""),
        labels.get("ticketLabel", ""),
    ]
    haystack = " ".join(haystack_parts).lower()
    if EAN and any(EAN in ean for ean in eans):
        score += 500
    for tok in term_tokens:
        if tok and tok in haystack:
            score += 15
    for tok in descriptor_tokens:
        if tok and tok in haystack:
            score += 8
    for neg in negatives:
        if neg and neg in haystack:
            score -= 120
    if "zero" in haystack or "sans sucre" in haystack:
        score -= 200
    return score


async def _resolve_product_url_via_api(page, typed_term: str, term_tokens: list[str], descriptor_tokens: list[str], negatives: set[str]) -> typing.Optional[str]:
    try:
        response = await page.request.get(
            CHRONO_SEARCH_API,
            params={"searchTerm": typed_term},
            headers=_search_headers(),
        )
    except Exception as exc:
        sys.stderr.write(f"[CHRONO_DEBUG] api_search_error={exc}\n")
        return None
    if response.status != 200:
        sys.stderr.write(f"[CHRONO_DEBUG] api_search_status={response.status}\n")
        return None
    try:
        payload = await response.json()
    except Exception:
        return None
    products = payload.get("products") or []
    if not products:
        return None
    best_product = None
    best_score = -9999
    for product in products:
        if not isinstance(product, dict):
            continue
        score = _product_score(product, term_tokens, descriptor_tokens, negatives)
        if best_product is None or score > best_score:
            best_product = product
            best_score = score
    if not best_product:
        return None
    product_id = best_product.get("id")
    if not product_id:
        return None
    try:
        detail_resp = await page.request.get(
            CHRONO_PRODUCT_API.format(product_id=product_id),
            headers=_product_headers(),
        )
    except Exception as exc:
        sys.stderr.write(f"[CHRONO_DEBUG] api_product_error={exc}\n")
        return None
    if detail_resp.status != 200:
        sys.stderr.write(f"[CHRONO_DEBUG] api_product_status={detail_resp.status}\n")
        return None
    try:
        detail = await detail_resp.json()
    except Exception:
        return None
    seo = detail.get("seo") or {}
    canonical = seo.get("canonicalUrl")
    if not canonical:
        return None
    if not canonical.startswith("http"):
        canonical = f"https://www.chronodrive.com{canonical}"
    return canonical


def _search_headers() -> dict[str, str]:
    return {
        "x-api-key": CHRONO_API_SEARCH_KEY,
        "x-chronodrive-site-id": CHRONO_SITE_ID,
        "x-device-type": CHRONO_DEVICE_TYPE,
        "x-chronodrive-site-mode": CHRONO_SITE_MODE,
        "referer": "https://www.chronodrive.com/",
    }


def _product_headers() -> dict[str, str]:
    return {
        "x-api-key": CHRONO_API_PRODUCT_KEY,
        "x-chronodrive-site-id": CHRONO_SITE_ID,
        "x-device-type": CHRONO_DEVICE_TYPE,
        "x-chronodrive-site-mode": CHRONO_SITE_MODE,
        "referer": "https://www.chronodrive.com/",
    }


async def extract_price_from_page(page) -> tuple[
    typing.Optional[str],
    typing.Optional[str],
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
    nutri_grade = None
    nutri_image = None

    try:
        title = await page.locator('h1').first.text_content(timeout=6000)
        if title:
            title = re.sub(r'\s+', ' ', title).strip()
    except Exception:
        title = None

    def normalize_text(value: typing.Optional[str]) -> typing.Optional[str]:
        if not value:
            return None
        return re.sub(r'\s+', ' ', value).strip()

    try:
        price_text = await page.locator('.product-actions-value').first.text_content(timeout=4000)
        price_text = normalize_text(price_text)
        if price_text:
            price_text = price_text.replace('€', '').replace(',', '.').strip()
            price_value = float(price_text)
            price = f"{price_value:.2f}".replace('.', ',')
    except Exception:
        price = None

    try:
        unit_text = await page.locator('.info-price').first.text_content(timeout=4000)
        unit_price = normalize_text(unit_text)
    except Exception:
        unit_price = None

    for selector in ['.card-metadata', '.info .label + b', '.info b']:
        try:
            node = page.locator(selector).first
            if await node.count():
                candidate = normalize_text(await node.text_content())
                if candidate and any(ch.isdigit() for ch in candidate):
                    quantity = candidate
                    break
        except Exception:
            continue

    try:
        html = await page.content()
        if html:
            if not matched_ean and EAN and EAN in html:
                matched_ean = EAN
            if not price:
                m_price = re.search(r'"price"\s*:\s*"([0-9.,]+)"', html)
                if m_price:
                    price_val = m_price.group(1).replace(',', '.').strip()
                    try:
                        price = f"{float(price_val):.2f}".replace('.', ',')
                    except Exception:
                        price = price_val.replace('.', ',')
            if not unit_price:
                m_unit = re.search(r'([0-9.,]+\s*€\s*/\s*(?:l|kg|g|cl|ml))', html, re.IGNORECASE)
                if m_unit:
                    unit_price = m_unit.group(1).replace('\xa0', ' ')
            if not quantity:
                m_qty = re.search(r'(\d+[\.,]?\d*)\s*(L|KG|G|ML|CL)', html, re.IGNORECASE)
                if m_qty:
                    qty_val = m_qty.group(1).replace('.', ',')
                    quantity = f"{qty_val} {m_qty.group(2).upper()}"
            guess_grade, guess_image = extract_nutriscore_from_html(html, base_url=page.url)
            if guess_grade and not nutri_grade:
                nutri_grade = guess_grade
            if guess_image and not nutri_image:
                nutri_image = guess_image
    except Exception:
        pass

    if price:
        price = price.replace('.', ',')

    if unit_price:
        # Some PDPs prepend "Prix au kg ou au litre :"; keep only the numeric segment.
        match_segment = re.search(r'([0-9][0-9.,]*\s*€\s*/\s*(?:L|KG|G|CL|ML))', unit_price, re.IGNORECASE)
        if match_segment:
            unit_price = match_segment.group(1)
        else:
            # Fallback: drop text before the last colon if present.
            if ':' in unit_price:
                unit_price = unit_price.split(':')[-1]
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
                    unit_price = f"{per_unit:.2f}".replace('.', ',') + f" € / {unit}"
            except Exception:
                pass

    return title, price, unit_price, quantity, matched_ean, nutri_grade, nutri_image


async def run() -> Result:
    storage_state = state_path_for('chronodrive')
    p, browser, context, page = await make_context(
        headless=HEADLESS, proxy=PROXY, storage_state_path=storage_state,
        user_agent=None,
    )
    async def _close_extra(new_page):
        try:
            await new_page.close()
        except Exception:
            pass

    context.on("page", lambda page_obj: asyncio.create_task(_close_extra(page_obj)))

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
        title, price, unit_price, quantity, matched_ean, nutri_grade, nutri_image = await extract_price_from_page(page)
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
                nutriscore_grade=nutri_grade,
                nutriscore_image=nutri_image,
            )
        return Result(status='NO_PRICE', title=title, url=page.url, note=store_label, store=store_label)

    # Otherwise search by terms
    terms = build_query_terms()
    if not terms:
        await browser.close(); await p.stop()
        return Result(status='NO_QUERY')

    descriptor_tokens: list[str] = []
    descriptor_entry = MANUAL_DESCRIPTOR.get(EAN) if EAN else None
    if isinstance(descriptor_entry, dict):
        for key in ("brand", "name", "description", "quantity"):
            raw = descriptor_entry.get(key)
            if isinstance(raw, str):
                descriptor_tokens.extend(re.split(r"[^a-z0-9]+", raw.lower()))
        extras = descriptor_entry.get('alternate_queries')
        if isinstance(extras, (list, tuple)):
            for extra in extras:
                if isinstance(extra, str):
                    descriptor_tokens.extend(re.split(r"[^a-z0-9]+", extra.lower()))
    descriptor_tokens = sorted(set(tok for tok in descriptor_tokens if len(tok) >= 3))
    descriptor_negatives: set[str] = set()
    if isinstance(descriptor_entry, dict):
        neg_map = descriptor_entry.get("negatives")
        if isinstance(neg_map, dict):
            for values in neg_map.values():
                if isinstance(values, (list, tuple)):
                    for item in values:
                        if isinstance(item, str):
                            descriptor_negatives.add(item.lower())
    descriptor_negatives.update({"zero", "sans sucre", "light", "zéro", "sugar free"})

    # Visit a store to set location if provided
    await ensure_store_selected(page)
    try:
        store_debug = await extract_store_label(page)
        if store_debug:
            sys.stderr.write(f"[CHRONO_DEBUG] store_label='{store_debug}'\n")
    except Exception:
        pass

    store_search_base = None
    if STORE_URL:
        store_search_base = STORE_URL.rstrip('/') + "/recherche?text={}"
    search_base = store_search_base or "https://www.chronodrive.com/recherche?text={}"

    for term in terms:
        typed_term = _normalize_term_for_typing(term)
        sys.stderr.write(f"[CHRONO_DEBUG] term='{typed_term}'\n")
        term_tokens = [t for t in re.split(r"[^a-z0-9]+", typed_term.lower()) if t]
        api_url = await _resolve_product_url_via_api(page, typed_term, term_tokens, descriptor_tokens, descriptor_negatives)
        if api_url:
            sys.stderr.write(f"[CHRONO_DEBUG] api_url={api_url}\n")
            try:
                await page.goto(api_url, wait_until='domcontentloaded')
            except PlaywrightTimeout:
                continue
            await accept_cookies(page)
            await page.wait_for_timeout(1000)
            title, price, unit_price, quantity, matched_ean, nutri_grade, nutri_image = await extract_price_from_page(page)
            store_label = await extract_store_label(page) or 'Chronodrive Le Haillan'
            if matched_ean is None and EAN and EAN in (page.url or ''):
                matched_ean = EAN
            if price:
                await browser.close(); await p.stop()
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
                    nutriscore_grade=nutri_grade,
                    nutriscore_image=nutri_image,
                )
            continue

        try:
            await page.goto(STORE_URL, wait_until='domcontentloaded')
        except PlaywrightTimeout:
            continue

        await accept_cookies(page)
        await page.wait_for_timeout(800)

        typed = await _type_search_query(page, typed_term, submit=False)
        sys.stderr.write(f"[CHRONO_DEBUG] typed={typed}\n")
        suggestion_clicked = False
        if typed:
            try:
                await page.wait_for_timeout(600)
                suggestion_clicked = await _click_best_suggestion(page, term_tokens, descriptor_tokens)
            except Exception as exc:
                sys.stderr.write(f"[CHRONO_DEBUG] suggestion_error={exc}\n")
                suggestion_clicked = False
        if suggestion_clicked:
            title, price, unit_price, quantity, matched_ean, nutri_grade, nutri_image = await extract_price_from_page(page)
            store_label = await extract_store_label(page) or 'Chronodrive Le Haillan'
            if matched_ean is None and EAN and EAN in (page.url or ''):
                matched_ean = EAN

            if price:
                await browser.close(); await p.stop()
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
                    nutriscore_grade=nutri_grade,
                    nutriscore_image=nutri_image,
                )
            # If PDP opened but no price, fall back to next term
            continue
        if typed:
            typed = await _submit_search(page)
            sys.stderr.write(f"[CHRONO_DEBUG] submit-triggered={typed}\n")
        if not typed:
            encoded_term = quote(typed_term, safe="")
            search_url = search_base.format(encoded_term.replace('%2B', '%20'))
            sys.stderr.write(f"[CHRONO_DEBUG] fallback search URL {search_url}\n")
            try:
                await page.goto(search_url, wait_until='domcontentloaded')
            except PlaywrightTimeout:
                continue
            await accept_cookies(page)

        await page.wait_for_load_state('domcontentloaded')
        sys.stderr.write(f"[CHRONO_DEBUG] URL after search: {page.url}\n")

        is_ean_term = EAN and typed_term.strip().replace(' ', '') == EAN.replace(' ', '')
        if not is_ean_term:
            await page.wait_for_timeout(1200)

        if not page.url or page.url.rstrip('/') == STORE_URL.rstrip('/'):
            encoded_term = quote(typed_term, safe="")
            search_url = search_base.format(encoded_term.replace('%2B', '%20'))
            sys.stderr.write(f"[CHRONO_DEBUG] forced search URL {search_url}\n")
            try:
                await page.goto(search_url, wait_until='domcontentloaded')
                await accept_cookies(page)
                await page.wait_for_timeout(1500)
            except PlaywrightTimeout:
                continue

        try:
            await page.wait_for_selector('article.product-card', timeout=1000)
        except PlaywrightTimeout:
            html = await page.content()
            debug_path = Path('chronodrive_debug.html')
            try:
                debug_path.write_text(html, encoding='utf-8')
            except Exception:
                pass
            sys.stderr.write("[CHRONO_DEBUG] no product cards; snapshot snippet:\n" + html[:800] + "\n")
            continue

        cards = page.locator('article.product-card')
        count = await cards.count()
        if count == 0:
            continue

        best_idx = None
        best_score = -1

        GENERIC_TOKENS = {
            'gel', 'douche', 'creme', 'cream', 'surgras', 'lait', 'peau', 'peaux',
            'format', 'flacon', 'bouteille', 'lot', 'pack', 'ml', 'kg', 'l', 'cadum', 'bio'
        }
        required_tokens = [tok for tok in descriptor_tokens if len(tok) >= 5 and tok not in GENERIC_TOKENS]

        for idx in range(count):
            card = cards.nth(idx)
            link = card.locator('a.card-extra-link').first
            href = (await link.get_attribute('href')) or ''
            card_title = ''
            for selector in ['.card-label-name', '.card-label', 'h2', '.card-title']:
                try:
                    node = card.locator(selector).first
                    if await node.count():
                        card_title = await node.inner_text(timeout=1000)
                        if card_title:
                            break
                except Exception:
                    continue
            if not card_title:
                try:
                    card_title = await link.inner_text()
                except Exception:
                    card_title = ''
            haystack = f"{href} {card_title}".lower()

            if required_tokens and not any(tok in haystack for tok in required_tokens):
                continue

            score = 0
            if EAN and EAN in haystack:
                score += 100
            for tok in term_tokens:
                if tok in haystack:
                    score += 1
            descriptor_hits = sum(1 for tok in descriptor_tokens if tok in haystack)
            descriptor_misses = sum(1 for tok in required_tokens if tok not in haystack)
            score += descriptor_hits * 4
            score -= descriptor_misses * 8

            if best_idx is None or score > best_score:
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

        title, price, unit_price, quantity, matched_ean, nutri_grade, nutri_image = await extract_price_from_page(page)
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
                nutriscore_grade=nutri_grade,
                nutriscore_image=nutri_image,
            )
        return Result(
            status='NO_PRICE',
            title=title,
            url=page.url,
            note=store_label,
            store=store_label,
            matched_ean=matched_ean,
            nutriscore_grade=nutri_grade,
            nutriscore_image=nutri_image,
        )

    await browser.close(); await p.stop()
    return Result(status='NO_RESULTS')


if __name__ == '__main__':
    res = asyncio.run(run())
    print(json.dumps(res.__dict__, ensure_ascii=False))
