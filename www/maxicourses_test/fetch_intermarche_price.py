#!/usr/bin/env python3
"""Fetcher Intermarché respectant le mandat de collecte."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import typing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from rich import print
import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for

from collection_mandate import get_method

EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
HOME_URL = os.environ.get("HOME_URL", "https://www.intermarche.com/")
MANDATE = get_method("intermarche")
DEBUG_INTERMARCHE = os.environ.get("DEBUG_INTERMARCHE") == "1"
DEBUG_DUMP_ROOT = os.environ.get("HUMAN_DEBUG_DIR") or os.environ.get("INTERMARCHE_DEBUG_DIR")

# Avoid hammering the same fallback terms twice in a row
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


def _looks_like_ean(term: typing.Optional[str]) -> bool:
    if not term:
        return False
    stripped = "".join(ch for ch in term.strip() if ch.isdigit())
    if not stripped:
        return False
    return stripped == term.strip().replace(" ", "") and 8 <= len(stripped) <= 14


def load_storage_state(path: typing.Optional[Path]) -> typing.Optional[dict]:
    if not path:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:
        return None


async def apply_storage_state(context, page, state: typing.Optional[dict]) -> None:
    if not state:
        return
    cookies = state.get("cookies") if isinstance(state, dict) else None
    if cookies:
        try:
            await context.add_cookies(cookies)
        except Exception:
            pass


def _debug_path(name: str) -> typing.Optional[Path]:
    if not DEBUG_DUMP_ROOT:
        return None
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    path = Path(DEBUG_DUMP_ROOT).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{safe}.html"


async def debug_dump(page, name: str) -> None:
    if not DEBUG_DUMP_ROOT:
        return
    try:
        html = await page.content()
    except Exception:
        return
    target = _debug_path(name)
    if not target:
        return
    try:
        target.write_text(html, encoding="utf-8")
        if DEBUG_INTERMARCHE:
            sys.stderr.write(f"[intermarche] debug dump -> {target}\n")
    except Exception:
        pass


async def debug_shot(page, name: str) -> None:
    if not DEBUG_DUMP_ROOT:
        return
    target = _debug_path(name)
    if not target:
        return
    png_path = target.with_suffix('.png')
    try:
        await page.screenshot(path=str(png_path))
        if DEBUG_INTERMARCHE:
            sys.stderr.write(f"[intermarche] debug screenshot -> {png_path}\n")
    except Exception:
        pass


def debug_json(name: str, payload: typing.Any) -> None:
    if not DEBUG_DUMP_ROOT or payload is None:
        return
    target = _debug_path(name)
    if not target:
        return
    json_path = target.with_suffix('.json')
    try:
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if DEBUG_INTERMARCHE:
            sys.stderr.write(f"[intermarche] debug json -> {json_path}\n")
    except Exception:
        pass


async def handle_404(page) -> bool:
    """Detect Intermarché 404 page and click the return button if present."""
    try:
        banner = page.locator("text='Vous êtes perdus dans nos rayons'").first
        if await banner.count():
            if DEBUG_INTERMARCHE:
                sys.stderr.write("[intermarche] 404 detected, returning to home\n")
            await debug_dump(page, "404-page")
            try:
                await page.get_by_role('button', name=lambda name: name and 'Revenir' in name).click()
            except Exception:
                await page.locator("button", has_text="Revenir à l'accueil").first.click()
            await page.wait_for_load_state('domcontentloaded')
            await page.wait_for_timeout(5000)
            return True
    except Exception:
        pass
    return False


def decode_store_label(raw: str) -> str:
    if not raw:
        return ''
    return unquote(unquote(raw)).strip()


async def get_store_metadata(context) -> typing.Optional[dict]:
    try:
        cookies = await context.cookies()
    except Exception:
        return None
    for cookie in cookies:
        if cookie.get('name') == 'itm_pdv':
            try:
                data = json.loads(unquote(cookie.get('value', '')))
            except Exception:
                return None
            data['decoded_name'] = decode_store_label(data.get('name', ''))
            data['decoded_city'] = decode_store_label(data.get('city', ''))
            return data
    return None


async def fetch_products_api(page, store_ref: str, keyword: str) -> list[dict]:
    if not store_ref or not keyword:
        return []
    payload = {
        'keyword': keyword,
        'page': 1,
        'limit': 40,
    }
    url = f"https://www.intermarche.com/api/service/produits/v4/pdvs/{store_ref}/products/byKeywordAndCategory"
    try:
        data = await page.evaluate(
            """
            async (endpoint, body) => {
              try {
                const res = await fetch(endpoint, {
                  method: 'POST',
                  credentials: 'include',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(body),
                });
                if (!res.ok) {
                  return { ok: false, status: res.status, body: await res.text() };
                }
                return { ok: true, json: await res.json() };
              } catch (err) {
                return { ok: false, error: err?.message || 'fetch_failed' };
              }
            }
            """,
            url,
            payload,
        )
    except Exception:
        data = None
    if not data or not data.get('ok'):
        if DEBUG_INTERMARCHE and data:
            sys.stderr.write(f"[intermarche] API call failed ({data.get('status')}) for {keyword}: {str(data.get('error') or '')[:120]}\n")
        return []
    payload = data.get('json') or {}
    products = payload.get('produits') or []
    if DEBUG_INTERMARCHE and not products:
        try:
            debug_json(f"api-empty-{keyword}", data)
        except Exception:
            pass
        try:
            snippet = json.dumps(data, ensure_ascii=False)[:400]
        except Exception:
            snippet = repr(data)[:400]
        sys.stderr.write(f"[intermarche] API empty payload raw: {snippet}\n")
        try:
            sys.stderr.flush()
        except Exception:
            pass
    return products if isinstance(products, list) else []


def _descriptor_seed(ean: str) -> typing.Optional[str]:
    """Compose the human search phrase stored in the manual descriptors table."""
    if not ean:
        return None
    entry = MANUAL_DESCRIPTOR.get(ean)
    if not isinstance(entry, dict):
        return None
    if entry.get("seed_query"):
        candidate = entry.get("seed_query").strip()
        if candidate and not _looks_like_ean(candidate):
            return candidate
    pieces = []
    for key in ("brand", "name", "quantity"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            pieces.append(value.strip())
    if pieces:
        candidate = " ".join(pieces)
        if candidate and not _looks_like_ean(candidate):
            return candidate
    if isinstance(entry.get("description"), str) and entry["description"].strip():
        candidate = entry["description"].strip()
        if candidate and not _looks_like_ean(candidate):
            return candidate
    return None


def tokens_for(term: str) -> list[str]:
    if not term:
        return []
    return [
        token
        for token in re.findall(r"[a-z0-9]+", term.lower())
        if len(token) >= 3 and not token.isdigit()
    ]


def _normalized_quantity_to_liters(quantity: typing.Optional[str]) -> typing.Optional[float]:
    if not isinstance(quantity, str):
        return None
    text = quantity.lower().replace(',', '.').replace(' ', '')
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(l|litre|litres|ml|millilitre|millilitres)", quantity.lower())
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit.startswith('ml') or 'milli' in unit:
        return value / 1000.0
    return value


def select_product(candidates: list[dict], *, tokens: list[str]) -> typing.Optional[dict]:
    if not candidates:
        return None
    best = None
    best_score = -1
    for candidate in candidates:
        label = f"{candidate.get('marque', '')} {candidate.get('libelle', '')}".lower()
        score = sum(1 for token in tokens if token and token in label)
        if EAN and candidate.get('produitEan13') == EAN:
            score += 5
        if score > best_score:
            best = candidate
            best_score = score
    return best or candidates[0]


def product_to_result(candidate: dict, store_label: typing.Optional[str]) -> Result:
    price_value = candidate.get('prix')
    price = None
    if isinstance(price_value, (int, float)):
        price = f"{float(price_value):.2f}".replace('.', ',')
    elif isinstance(price_value, str) and price_value.strip():
        try:
            price = f"{float(price_value.replace(',', '.')):.2f}".replace('.', ',')
        except Exception:
            price = price_value

    unit_price = None
    unit_data = candidate.get('prixUnitaire') or candidate.get('prixPar') or candidate.get('unitPrice')
    if isinstance(unit_data, (int, float)) and candidate.get('unitePrixVente'):
        unit_text = candidate['unitePrixVente']
        unit_price = f"{float(unit_data):.2f}".replace('.', ',') + f" € / {unit_text}"
    elif isinstance(unit_data, str) and unit_data.strip():
        unit_price = unit_data.replace('.', ',')

    quantity = candidate.get('conditionnement') or candidate.get('format') or candidate.get('volume')
    if isinstance(quantity, (int, float)):
        quantity = f"{quantity}"

    libelle = candidate.get('libelle') or ''
    marque = candidate.get('marque') or ''
    title = libelle
    if marque and marque.lower() not in title.lower():
        title = f"{marque} {title}".strip()

    slug = re.sub(r"[^a-z0-9-]", '-', title.lower())
    slug = re.sub(r"-+", '-', slug).strip('-') or 'produit'
    ean = candidate.get('produitEan13') or candidate.get('ean') or EAN or ''
    url = f"https://www.intermarche.com/produit/{slug}/{ean}" if ean else None

    return Result(
        status="OK",
        price=price,
        title=title or libelle,
        url=url,
        note=f"Intermarché · {store_label}" if store_label else "Intermarché (API)",
        matched_ean=ean or None,
        unit_price=unit_price,
        quantity=quantity,
        store=store_label,
    )


def build_query_terms() -> list[str]:
    """Return textual search terms sorted by relevance (never the raw EAN)."""
    terms: list[str] = []

    def add(term: typing.Optional[str]) -> None:
        if not term:
            return
        candidate = " ".join(term.split()).strip()
        if not candidate or _looks_like_ean(candidate):
            return
        if candidate not in terms:
            terms.append(candidate)

    descriptor = MANUAL_DESCRIPTOR.get(EAN) if EAN else None

    if isinstance(descriptor, dict):
        primary = descriptor.get("primary_keywords")
        if isinstance(primary, (list, tuple)):
            for item in primary:
                add(item)

    if not terms:
        add(_descriptor_seed(EAN))
    if not terms:
        add(QUERY)
    if not terms and isinstance(descriptor, dict):
        fallback = " ".join(
            part.strip()
            for part in [descriptor.get("brand", ""), descriptor.get("name", ""), descriptor.get("quantity", "")]
            if isinstance(part, str) and part.strip()
        )
        add(fallback)

    return terms


@dataclass
class Result:
    status: str
    price: typing.Optional[str] = None
    title: typing.Optional[str] = None
    url: typing.Optional[str] = None
    note: typing.Optional[str] = None
    matched_ean: typing.Optional[str] = None
    unit_price: typing.Optional[str] = None
    quantity: typing.Optional[str] = None
    store: typing.Optional[str] = None


COOKIE_SELECTORS = [
    "button:has-text('Tout accepter')",
    "button:has-text('Accepter')",
    "button:has-text(\"J'accepte\")",
    "#onetrust-accept-btn-handler",
    "#didomi-notice-agree-button",
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
                await page.wait_for_timeout(5000)
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
                await page.wait_for_timeout(5000)
                return True
    except Exception:
        pass
    return False


async def perform_search(page, term: str) -> bool:
    """Submit a search query via the top search field."""
    field = page.locator("input[placeholder='Lait, oeuf, pain...']").first
    try:
        if not await field.count():
            return False
        await field.click()
        try:
            await field.fill('')
        except Exception:
            await page.evaluate("(sel)=>{const el=document.querySelector(sel); if(el){el.value='';}}", "input[placeholder='Lait, oeuf, pain...']")
        await page.wait_for_timeout(5000)
        await field.type(term, delay=40)
        await field.press('Enter')
        try:
            await page.wait_for_load_state('networkidle')
        except Exception:
            await page.wait_for_load_state('domcontentloaded')
        await page.wait_for_timeout(5000)
        return True
    except Exception:
        return False


async def collect_product_links(page) -> list[dict]:
    """Extract product anchors from the current search results page."""
    results = []
    try:
        anchors = page.locator("a[href*='/produit/']")
        count = await anchors.count()
    except Exception:
        count = 0
    for idx in range(min(count, 20)):
        try:
            link = anchors.nth(idx)
            href = await link.get_attribute('href')
            if not href:
                continue
            text = await link.inner_text(timeout=2000)
            results.append({'href': href, 'text': text})
        except Exception:
            continue
    return results


async def run() -> Result:
    storage_state_path = state_path_for('intermarche')
    p, browser, context, page = await make_context(
        headless=HEADLESS,
        proxy=PROXY,
        storage_state_path=storage_state_path if os.environ.get('USE_CDP') != '1' else None,
        user_agent=DEFAULT_UA,
    )
    async def _adopt_new_page(new_page):
        nonlocal page
        try:
            await new_page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
        old_page = page
        page = new_page
        try:
            await new_page.bring_to_front()
        except Exception:
            pass
        if old_page and old_page != new_page:
            try:
                await old_page.close()
            except Exception:
                pass

    context.on("page", lambda new_page: asyncio.create_task(_adopt_new_page(new_page)))

    state_data = load_storage_state(Path(storage_state_path) if storage_state_path else None)
    if state_data:
        await apply_storage_state(context, page, state_data)

    use_cdp = os.environ.get("USE_CDP") == "1"
    if use_cdp:
        preferred_page = None
        for existing in context.pages:
            try:
                url = existing.url
            except Exception:
                url = ""
            if url and "intermarche.com" in url and not url.startswith("about:"):
                preferred_page = existing
                break
        if not preferred_page and context.pages:
            preferred_page = context.pages[0]
        if preferred_page:
            if page != preferred_page:
                try:
                    await page.close()
                except Exception:
                    pass
            page = preferred_page
        try:
            await page.bring_to_front()
        except Exception:
            pass

    try:
        await context.set_extra_http_headers(DEFAULT_HEADERS)
    except Exception:
        pass

    home_url = HOME_URL or "https://www.intermarche.com/"
    if not page.url or "intermarche.com" not in page.url:
        try:
            await page.goto("about:blank")
            await page.wait_for_timeout(5000)
        except Exception:
            pass
        try:
            await page.goto(home_url, wait_until="domcontentloaded")
        except Exception:
            pass
    else:
        try:
            await page.reload(wait_until="domcontentloaded")
        except Exception:
            pass
    try:
        await page.wait_for_timeout(5000)
        await page.mouse.move(200, 200, steps=15)
        await page.wait_for_timeout(5000)
    except Exception:
        pass
    if DEBUG_INTERMARCHE:
        sys.stderr.write(f"[intermarche] landed on {page.url}\n")
    if await ensure_home(page):
        await ensure_home(page)  # second chance if redirected twice
    await accept_cookies(page)
    await ensure_store_selected(page)

    store_metadata = await get_store_metadata(context)
    store_ref = None
    store_label_initial = None
    if isinstance(store_metadata, dict):
        store_ref = store_metadata.get('ref') or store_metadata.get('code')
        store_label_initial = store_metadata.get('decoded_name') or store_metadata.get('name') or None
    if DEBUG_INTERMARCHE:
        sys.stderr.write(f"[intermarche] store metadata ref={store_ref} label={store_label_initial}\n")

    descriptor_entry = MANUAL_DESCRIPTOR.get(EAN) if EAN else None
    descriptor_tokens: list[str] = []
    if isinstance(descriptor_entry, dict):
        for part in [descriptor_entry.get('brand'), descriptor_entry.get('name'), descriptor_entry.get('quantity')]:
            if isinstance(part, str):
                descriptor_tokens.extend(tokens_for(part))
    descriptor_tokens = list(dict.fromkeys(descriptor_tokens))

    # Build search terms: prefer descriptor seed then manual query text
    terms = build_query_terms()
    if not terms:
        await browser.close(); await p.stop()
        return Result(status="NO_QUERY")

    price = None
    title = None
    pdp = None
    matched_ean = None
    unit_price = None
    quantity_text = descriptor_entry.get('quantity') if isinstance(descriptor_entry, dict) else None
    store_label = store_label_initial
    normalized_query_tokens: list[str] = []
    api_candidate_url = None
    api_candidate_price = None
    api_candidate_title = None
    api_candidate_unit = None
    api_candidate_quantity = None
    api_candidate_ean = None
    seen_terms: set[str] = set()
    unique_terms: list[str] = []
    for term in terms:
        if not term:
            continue
        canonical_term = " ".join(term.lower().split())
        if canonical_term in seen_terms:
            continue
        seen_terms.add(canonical_term)
        unique_terms.append(term)
    for term in unique_terms:
        candidate_tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", term.lower())
            if len(token) >= 3 and not token.isdigit()
        ]
        if candidate_tokens:
            normalized_query_tokens = candidate_tokens
            break
    for term in unique_terms:
        # Try to run the actual site search workflow (SPA)
        tokens_current = tokens_for(term)
        api_keyword = " ".join(tokens_current) if tokens_current else term
        if store_ref:
            try:
                api_products = await fetch_products_api(page, store_ref, api_keyword)
            except Exception:
                api_products = []
            if DEBUG_INTERMARCHE:
                sys.stderr.write(f"[intermarche] API products for '{term}': {len(api_products)}\n")
                if api_products:
                    debug_json(f"api-{term}", {"products": api_products})
            if api_products:
                tokens = normalized_query_tokens or tokens_current
                if not tokens:
                    tokens = tokens_for(term)
                candidate = select_product(api_products, tokens=tokens)
                if candidate:
                    api_result = product_to_result(candidate, store_label or store_label_initial)
                    if api_result.price:
                        api_candidate_price = api_result.price
                    if api_result.unit_price:
                        api_candidate_unit = api_result.unit_price
                    if api_result.quantity:
                        api_candidate_quantity = api_result.quantity
                    if api_result.title:
                        api_candidate_title = api_result.title
                    if api_result.url:
                        api_candidate_url = api_result.url
                    if api_result.matched_ean:
                        api_candidate_ean = api_result.matched_ean
                    if api_result.store:
                        store_label = api_result.store
                    if api_result.matched_ean and api_result.matched_ean == EAN and api_result.price:
                        await browser.close(); await p.stop()
                        return api_result

        await page.goto(home_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        await accept_cookies(page)
        await ensure_store_selected(page)
        await accept_cookies(page)
        performed = await perform_search(page, term)
        if not performed:
            if DEBUG_INTERMARCHE:
                sys.stderr.write(f"[intermarche] search field not available for term '{term}'\n")
            continue
        await debug_dump(page, f"search-{term}")
        await debug_shot(page, f"search-{term}")
        await page.wait_for_timeout(5000)
        if await handle_404(page):
            if DEBUG_INTERMARCHE:
                sys.stderr.write(f"[intermarche] 404 after search '{term}', retrying next term\n")
            continue
        candidates_info = await collect_product_links(page)
        if api_candidate_url:
            candidates_info.insert(0, {'href': api_candidate_url, 'text': api_candidate_title or ''})

        def score_candidate(info: dict) -> int:
            href = info.get('href') or ''
            text = (info.get('text') or '').lower()
            score = 0
            if EAN and href and EAN in href:
                score += 100
            for token in descriptor_tokens:
                if token and token in text:
                    score += 8
            if 'original' in text:
                score += 6
            if '950' in text:
                score += 4
            for token in normalized_query_tokens:
                if token and token in text:
                    score += 4
            return score

        candidates_info.sort(key=score_candidate, reverse=True)
        if DEBUG_INTERMARCHE:
            sys.stderr.write(f"[intermarche] candidates for term '{term}': {[c.get('href') for c in candidates_info]}\n")

        pdp = None
        candidates: list[str] = []
        for info in candidates_info:
            href = info.get('href')
            if not href:
                continue
            if href.startswith('/'):
                href = f"https://www.intermarche.com{href}"
            if href not in candidates:
                candidates.append(href)

        matched_href = None
        fallback_href = None
        for idx, href in enumerate(candidates):
            try:
                await page.goto(href, wait_until='domcontentloaded')
                await page.wait_for_timeout(5000)
                try:
                    await page.wait_for_selector("[data-testid='product-price'], .product-price", timeout=6000)
                except Exception:
                    pass
                if await handle_404(page):
                    await ensure_home(page)
                    continue
                html = await page.content()
                if DEBUG_INTERMARCHE:
                    sys.stderr.write(f"[intermarche] inspecting {page.url}\n")
                await debug_dump(page, f"pdp-{idx}")
                await debug_shot(page, f"pdp-{idx}")
                if not fallback_href:
                    fallback_href = href
                if EAN and (EAN in href or EAN in html):
                    matched_href = href
                    matched_ean = EAN
                    break
            except Exception:
                continue
        pdp = matched_href or fallback_href
        if not pdp:
            continue
        # ensure we are on the product page corresponding to pdp
        if page.url != pdp:
            try:
                await page.goto(pdp, wait_until='domcontentloaded')
                await page.wait_for_timeout(5000)
                try:
                    await page.wait_for_selector("[data-testid='product-price'], .product-price", timeout=6000)
                except Exception:
                    pass
            except Exception:
                pass
        await accept_cookies(page)
        await ensure_store_selected(page)
        await accept_cookies(page)
        await ensure_store_selected(page)

        page_html = await page.content()
        if not price:
            try:
                ld_scripts = await page.locator("script[type='application/ld+json']").all_text_contents()
            except Exception:
                ld_scripts = []
            for raw in ld_scripts:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("@type") != "Product":
                        continue
                    price_info = item.get("price")
                    if isinstance(price_info, dict):
                        value = price_info.get("value")
                        if value is not None and price is None:
                            try:
                                price = f"{float(value):.2f}".replace('.', ',')
                            except Exception:
                                price = str(value)
                    if not title:
                        maybe_title = item.get("name")
                        if isinstance(maybe_title, str) and maybe_title.strip():
                            title = maybe_title.strip()
        # Enforce secondary keywords on PDP and reject packs/lots
        try:
            lowered = page_html.lower()
            banned = any(x in lowered for x in [" pack ", " lot ", " mini ", "canettes", "canette"]) or bool(re.search(r"\b\d+\s*(x|×)\s*\d+\b", lowered))
            secondary = []
            if isinstance(descriptor_entry, dict):
                sec_raw = descriptor_entry.get('secondary_keywords') or []
                if isinstance(sec_raw, list):
                    secondary = [str(tok).lower() for tok in sec_raw if isinstance(tok, str)]
            if banned:
                continue
            if secondary and not all(tok in lowered for tok in secondary):
                continue
        except Exception:
            pass
        if not unit_price and page_html:
            match = re.search(r"(\d+[\.,]\d{2})\s*€\s*/\s*([a-zA-ZéÉ/]+)", page_html)
            if match:
                amount = match.group(1).replace('.', ',')
                unit = match.group(2).strip().upper()
                unit_price = f"{amount} € / {unit}"
        if not quantity_text:
            try:
                qty_candidate = await page.locator(
                    "[data-testid='product-packaging'], .product__weight, .product__capacity, .product-details__weight"
                ).first.text_content(timeout=2000)
                if qty_candidate:
                    quantity_text = " ".join(qty_candidate.split())
            except Exception:
                pass
        has_identifier_match = False
        # Try schema.org
        try:
            for i in range(await page.locator("script[type='application/ld+json']").count()):
                raw = await page.locator("script[type='application/ld+json']").nth(i).text_content()
                data = json.loads(raw)
                items = data if isinstance(data, list) else [data]
                for it in items:
                    if isinstance(it, dict) and it.get("@type") in ("Product",):
                        gtin = it.get("gtin13") or it.get("gtin") or it.get("gtin14")
                        if gtin:
                            gtin_str = str(gtin).strip()
                            if gtin_str:
                                if EAN and gtin_str == EAN:
                                    matched_ean = gtin_str
                                    has_identifier_match = True
                                elif not EAN:
                                    matched_ean = matched_ean or gtin_str
                                    has_identifier_match = True
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
            has_ean = (canonical and EAN in canonical) or (EAN in pdp if pdp else False) or False
            if not has_ean and page_html:
                has_ean = EAN in page_html
            if has_ean:
                matched_ean = EAN
                has_identifier_match = True

        if not has_identifier_match and page_html:
            digits = re.findall(r"\b\d{13}\b", page_html)
            if digits:
                if EAN and EAN in digits:
                    matched_ean = EAN
                    has_identifier_match = True
                elif not EAN:
                    matched_ean = matched_ean or digits[0]
                    has_identifier_match = True

        if not heuristics_ok and not has_identifier_match:
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

    if not price and api_candidate_price:
        price = api_candidate_price.replace(',', '.').replace(' ', '')
        pdp = api_candidate_url or pdp
        title = title or api_candidate_title
        unit_price = unit_price or api_candidate_unit
        quantity_text = quantity_text or api_candidate_quantity
        matched_ean = matched_ean or api_candidate_ean

    if not store_label:
        try:
            metadata = await get_store_metadata(context)
        except Exception:
            metadata = None
        if isinstance(metadata, dict):
            store_label = metadata.get('decoded_name') or metadata.get('name') or None

    await browser.close(); await p.stop()
    if price and pdp:
        try:
            price = f"{float(str(price).replace(',', '.')):.2f}"
        except Exception:
            price = str(price)
        price = price.replace('.', ',')
        if isinstance(descriptor_entry, dict):
            title = title or descriptor_entry.get('name') or descriptor_entry.get('description')
        final_quantity = quantity_text or (descriptor_entry.get('quantity') if isinstance(descriptor_entry, dict) else None)
        if not unit_price:
            liters = _normalized_quantity_to_liters(final_quantity)
            try:
                if liters and liters > 0:
                    unit_value = float(price.replace(',', '.')) / liters
                    unit_price = f"{unit_value:.2f}".replace('.', ',') + " € / L"
            except Exception:
                pass
        if unit_price:
            amount, sep, tail = unit_price.partition(' €')
            if amount:
                unit_price = amount.replace('.', ',') + sep + tail
        note = None
        if store_label:
            note = f"Intermarché · {store_label}"
        else:
            note = "Intermarché (CDP)"
        return Result(
            status="OK",
            price=price,
            title=title,
            url=pdp,
            note=note,
            matched_ean=matched_ean,
            unit_price=unit_price,
            quantity=final_quantity,
            store=store_label,
        )
    if pdp:
        return Result(
            status="NO_PRICE",
            title=title,
            url=pdp,
            note=None,
            matched_ean=matched_ean,
            unit_price=None,
            quantity=None,
            store=store_label,
        )
    return Result(status="NO_RESULTS")


if __name__ == "__main__":
    res = asyncio.run(run())
    print(json.dumps(res.__dict__, ensure_ascii=False))
