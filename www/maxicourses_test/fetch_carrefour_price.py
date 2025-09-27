#!/usr/bin/env python3
"""Carrefour core fetcher (City/Market) respectant le mandat de collecte."""
import asyncio
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

from rich import print
import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    from playwright_stealth import stealth_async
except Exception as e:
    print(f"ERR_IMPORT: {e}")
    sys.exit(2)


EAN = os.environ.get("EAN", "7613035676497").strip()
STORE_QUERY = os.environ.get("STORE_QUERY", "Bordeaux City")  # e.g. "Bordeaux Market" / "Bordeaux City"
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")  # e.g. socks5://user:pass@host:port
HOME_URL = os.environ.get("HOME_URL", "https://www.carrefour.fr/courses")
QUERY = (os.environ.get("QUERY") or EAN).strip()
HUMAN_DEBUG_DIR = os.environ.get("HUMAN_DEBUG_DIR")
STATE_VARIANT = os.environ.get("CARREFOUR_STATE_VARIANT", "carrefour")
USING_CDP = os.environ.get("USE_CDP", "0") == "1"


@dataclass
class Result:
    status: str
    price: Optional[str] = None
    store: Optional[str] = None
    url: Optional[str] = None
    note: Optional[str] = None
    unit_price: Optional[str] = None
    quantity: Optional[str] = None
    title: Optional[str] = None
    matched_ean: Optional[str] = None
    image: Optional[str] = None
    nutriscore_grade: Optional[str] = None
    nutriscore_image: Optional[str] = None


def _debug_path(name: str) -> Optional[Path]:
    if not HUMAN_DEBUG_DIR:
        return None
    path = Path(HUMAN_DEBUG_DIR)
    path.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return path / f"{safe}.png"


async def snapshot(page, name: str) -> None:
    path = _debug_path(name)
    if not path:
        return
    try:
        await page.screenshot(path=str(path), full_page=True)
    except Exception:
        pass


async def human_wait(page, ms: int = 800) -> None:
    try:
        await page.wait_for_timeout(ms)
    except Exception:
        pass


async def human_pause(page, base: int = 900, jitter: int = 700) -> None:
    delay = base + random.randint(0, jitter)
    await human_wait(page, delay)


async def gentle_move(page, x: float, y: float) -> None:
    try:
        mouse = page.mouse
        await mouse.move(x + random.uniform(-5, 5), y + random.uniform(-5, 5), steps=15)
    except Exception:
        pass


async def gentle_scroll(page, pixels: int = 400) -> None:
    try:
        await page.mouse.wheel(0, pixels + random.randint(-80, 80))
        await human_pause(page, 500, 500)
    except Exception:
        pass


async def dump_html(page, name: str) -> None:
    if not HUMAN_DEBUG_DIR:
        return
    try:
        html = await page.content()
    except Exception:
        return
    debug_dir = Path(HUMAN_DEBUG_DIR)
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"{re.sub(r'[^A-Za-z0-9._-]', '_', name)}.html"
    try:
        path.write_text(html, encoding="utf-8")
    except Exception:
        pass


def clean_spaces(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    import unicodedata
    normalized = unicodedata.normalize('NFKC', value)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_store_name(value: Optional[str]) -> str:
    return (clean_spaces(value) or "").lower()


def store_matches(store_name: Optional[str], target: Optional[str]) -> bool:
    if not target:
        return True
    normalized_name = normalize_store_name(store_name)
    normalized_target = normalize_store_name(target)
    tokens = [tok for tok in re.split(r"\s+", normalized_target) if tok]
    return all(tok in normalized_name for tok in tokens)


async def accept_cookies(page) -> None:
    selectors = [
        "button:has-text('Tout accepter')",
        "button:has-text('Accepter')",
        "button:has-text(\"J'accepte\")",
        "#onetrust-accept-btn-handler",
        "#didomi-notice-agree-button",
    ]
    for idx, sel in enumerate(selectors):
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                try:
                    box = await btn.bounding_box()
                    if box:
                        await gentle_move(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                except Exception:
                    pass
                await snapshot(page, f"cookies-{idx}")
                await human_pause(page, 600, 400)
                await btn.click()
                await human_pause(page, 800, 600)
                return
        except Exception:
            continue
    try:
        await page.evaluate(
            """
            (()=>{const labels=['tout accepter','accepter','j\'accepte','ok'];
            const btns=[...document.querySelectorAll('button')];
            for(const b of btns){const t=(b.innerText||'').trim().toLowerCase();
                if(labels.some(l=>t.includes(l))){b.click();return true;}}
            return false;})()
            """
        )
    except Exception:
        pass


async def open_store_modal(page) -> bool:
    selectors = [
        "button:has-text('Choisir mon magasin')",
        "button:has-text('Mon magasin')",
        "button[data-testid='store-selector']",
        "button[aria-label*='magasin']",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                try:
                    box = await btn.bounding_box()
                    if box:
                        await gentle_move(page, box['x'] + box['width']/2, box['y'] + box['height']/2)
                except Exception:
                    pass
                await snapshot(page, 'store-modal-open')
                await human_pause(page, 400, 300)
                await btn.click()
                await human_pause(page, 600, 400)
                return True
        except Exception:
            continue
    return False


async def choose_store_from_modal(page, target: str) -> bool:
    try:
        dialog = page.locator("[role='dialog']").first
        if not await dialog.count():
            return False

        # Sometimes the modal has a "Changer de drive" button before search
        for sel in ["button:has-text('Changer de drive')", "a:has-text('Changer de drive')"]:
            try:
                btn = dialog.locator(sel).first
                if await btn.count():
                    await btn.click()
                    await human_pause(page, 500, 400)
                    break
            except Exception:
                pass

        search = dialog.locator("input[type='search'], input[placeholder*='Rechercher'], input[placeholder*='magasin']").first
        if await search.is_visible(timeout=1500):
            await search.click()
            await search.fill('')
            await human_pause(page, 250, 200)
            target_norm = clean_spaces(target) or target
            for ch in target_norm:
                await search.type(ch, delay=120 + random.randint(-30, 60))
            await human_pause(page, 900, 400)

        normalized_target = clean_spaces(target) or target
        pattern = re.escape(normalized_target)
        option = dialog.locator(f"text=/{pattern}/i").first
        if not await option.count():
            first_token = normalized_target.split(' ')[0]
            option = dialog.locator(f"text=/{re.escape(first_token)}/i").first
        if await option.count():
            try:
                await option.scroll_into_view_if_needed()
                box = await option.bounding_box()
                if box:
                    await gentle_move(page, box['x'] + box['width']/2, box['y'] + box['height']/2)
            except Exception:
                pass
            await human_pause(page, 300, 200)
            await option.click()
            await human_pause(page, 700, 400)

        # Confirm selection if there is a button
        for sel in [
            "button:has-text('Choisir ce magasin')",
            "button:has-text('Sélectionner ce magasin')",
            "button:has-text('Valider ce magasin')",
            "button:has-text('Choisir ce drive')",
        ]:
            try:
                confirm = dialog.locator(sel).first
                if await confirm.count():
                    await human_pause(page, 400, 250)
                    await confirm.click()
                    await human_pause(page, 900, 400)
                    return True
            except Exception:
                continue

        # some flows close automatically when clicking the list entry
        return True
    except Exception:
        return False


def _normalize_store_label(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = clean_spaces(raw)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    match = re.search(r"drive\s+([^\n]+)", cleaned, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1)
        candidate = re.split(r"(?:livraison|changer|vos courses|votre plein)", candidate, flags=re.IGNORECASE)[0]
        candidate = clean_spaces(candidate)
        if candidate:
            return candidate
    if lowered.startswith("drive "):
        cleaned = cleaned[len("drive "):].strip()
    if cleaned.lower().startswith("drive "):
        cleaned = cleaned.split(" ", 1)[1].strip()
    tokens = cleaned.split(" ")
    if tokens and tokens[0].lower() == "drive":
        cleaned = " ".join(tokens[1:]).strip()
    return cleaned or None


async def read_current_store(page) -> Optional[str]:
    selectors = [
        "[data-testid='store-switcher__current-store']",
        "button[data-testid='store-switcher__current-store']",
        "button[data-testid*='store-switcher']",
        "[data-testid='current-store']",
        "button:has-text('Mon magasin')",
        "button[aria-label*='magasin']",
    ]
    for sel in selectors:
        try:
            node = page.locator(sel).first
            if not await node.count():
                continue
            try:
                await node.wait_for(state='visible', timeout=2000)
            except Exception:
                pass
            try:
                text = await node.inner_text()
            except Exception:
                text = await node.text_content()
            label = _normalize_store_label(text)
            if label:
                await snapshot(page, 'store-selected')
                return label
        except Exception:
            continue
    # JavaScript fallback grabbing the header component explicitly
    try:
        raw = await page.evaluate(
            """
(() => {
  const picker = document.querySelector('[data-testid=\'store-switcher__current-store\']');
  if (picker) return picker.innerText || picker.textContent || '';
  const driveBtn = Array.from(document.querySelectorAll('button')).find(btn =>
    /Drive/gi.test(btn.innerText || btn.textContent || '') && /Bordeaux|City|Market/i.test(btn.innerText || ''));
  if (driveBtn) return driveBtn.innerText || driveBtn.textContent || '';
  const header = document.querySelector('header');
  if (header) return header.innerText || header.textContent || '';
  return document.body ? document.body.innerText || '' : '';
})()
"""
        )
        label = _normalize_store_label(raw)
        if label:
            await snapshot(page, 'store-selected')
            return label
    except Exception:
        pass
    try:
        body_text = await page.evaluate("document.body ? document.body.innerText || '' : ''")
    except Exception:
        body_text = ""
    if body_text:
        label = _normalize_store_label(body_text)
        if label:
            await snapshot(page, 'store-selected')
            return label
    return None


async def ensure_expected_store(page, target: Optional[str], attempts: int = 3) -> Optional[str]:
    expected = clean_spaces(target)
    if not expected:
        current = await read_current_store(page)
        if current:
            return current
        opened = await open_store_modal(page)
        if opened:
            await human_pause(page, 700, 400)
        return await read_current_store(page)
    for attempt in range(attempts):
        current = await read_current_store(page)
        if store_matches(current, expected):
            return clean_spaces(current)
        if current is None:
            # Le bandeau n'est peut-être pas encore chargé : attendre avant d'ouvrir la modale
            await human_pause(page, 900, 600)
            continue
        opened = await open_store_modal(page)
        if opened:
            success = await choose_store_from_modal(page, expected)
            await human_pause(page, 900, 500)
            if success:
                current = await read_current_store(page)
                if store_matches(current, expected):
                    return clean_spaces(current)
                return expected
        else:
            await human_pause(page, 400, 250)
    current = await read_current_store(page)
    if not current:
        try:
            body_text = await page.evaluate("document.body ? document.body.innerText || '' : ''")
        except Exception:
            body_text = ""
        if body_text and expected and expected.lower() in body_text.lower():
            return expected
    return clean_spaces(current)


async def perform_search(page, term: str) -> bool:
    await open_search_ui(page)
    search_selectors = [
        "input[type='search']",
        "input[name='search']",
        "input[name='q']",
        "input[placeholder*='Recherchez']",
    ]
    for sel in search_selectors:
        try:
            box = page.locator(sel).first
            if await box.is_visible(timeout=2000):
                bbox = await box.bounding_box()
                if bbox:
                    await gentle_move(page, bbox["x"] + bbox["width"] / 2, bbox["y"] + bbox["height"] / 2)
                await human_pause(page, 400, 400)
                await box.click()
                await human_pause(page, 250, 250)
                await box.fill("")
                await human_pause(page, 300, 200)
                for ch in term:
                    await box.type(ch, delay=140 + random.randint(-40, 80))
                await snapshot(page, "search-query")
                await human_pause(page, 600, 600)
                await page.keyboard.press('Enter')
                await human_pause(page, 1700, 900)
                return True
        except Exception:
            continue
    return False


async def open_search_ui(page) -> bool:
    toggles = [
        "button[aria-label*='Rechercher']",
        "button:has-text('Rechercher')",
        "button[data-testid='header-search-button']",
        "button[data-testid='search-button']",
        "button[class*='search']",
    ]
    for sel in toggles:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.hover()
                await human_pause(page, 400, 300)
                await btn.click()
                await human_pause(page, 500, 300)
        except Exception:
            continue

    try:
        count = await page.locator("input[type='search'], input[name='search'], input[name='q']").count()
        return count > 0
    except Exception:
        return False


async def run() -> Result:
    launch_kwargs = {"headless": HEADLESS, "timeout": 60000}
    if PROXY:
        launch_kwargs["proxy"] = {"server": PROXY}

    # Try using saved state if present
    storage_state = (
        state_path_for(STATE_VARIANT)
        or state_path_for('carrefour')
        or state_path_for('courses-carrefour')
    )
    p, browser, context, page = await make_context(
        headless=HEADLESS, proxy=PROXY, storage_state_path=storage_state,
        user_agent=None,
    )

    async def acquire_carrefour_tab() -> Optional[Any]:
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if pg.is_closed():
                    continue
                current_url = pg.url or ""
                if "carrefour.fr" in current_url:
                    try:
                        await pg.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    return pg
        return None

    existing_page = await acquire_carrefour_tab()
    if existing_page and existing_page != page:
        try:
            await page.close()
        except Exception:
            pass
        page = existing_page
    else:
        try:
            await page.goto(HOME_URL, wait_until="domcontentloaded")
        except Exception:
            pass

    try:
        await page.bring_to_front()
    except Exception:
        pass

    store_name = None
    expected_store = clean_spaces(STORE_QUERY)
    try:
        await snapshot(page, "home")
        await dump_html(page, "home")
    except Exception:
        pass

    await human_pause(page, 900, 700)
    await accept_cookies(page)
    store_name = await ensure_expected_store(page, STORE_QUERY, attempts=3)

    search_terms = [EAN]
    if QUERY and QUERY != EAN:
        search_terms.append(QUERY)

    pdp_url = None
    title_text = None
    price_text = None
    unit_text = None
    quantity_text = None
    matched_ean = None
    image_url = None
    nutriscore_grade = None
    nutriscore_image = None

    for term in search_terms:
        performed = await perform_search(page, term)
        store_name = await ensure_expected_store(page, STORE_QUERY, attempts=3)
        if not performed:
            # fallback: direct navigation to search results
            search_url = f"https://www.carrefour.fr/s?q={term}"
            try:
                resp = await page.goto(search_url, wait_until="domcontentloaded")
            except PlaywrightTimeout:
                continue
            title_check = await page.title()
            if "Just a moment" in title_check or (resp and resp.status == 403):
                await snapshot(page, "cf-block")
                await dump_html(page, "cf-block")
                if not USING_CDP:
                    await browser.close()
                await p.stop()
                return Result(status="CF_BLOCK", url=search_url)
        await human_pause(page, 1200, 800)
        safe_term = re.sub(r"[^A-Za-z0-9]", "_", term)[:20]
        await snapshot(page, f"results-{safe_term}")
        await dump_html(page, f"results-{safe_term}")

        cards = page.locator("a[href^='/p/']")
        count = await cards.count()
        if count == 0:
            continue

        for idx in range(min(count, 6)):
            try:
                card = cards.nth(idx)
                await card.scroll_into_view_if_needed()
                await gentle_scroll(page, 250)
                await snapshot(page, f"result-card-{idx}")
                await card.click(timeout=8000)
                await page.wait_for_load_state('domcontentloaded')
                await human_pause(page, 1300, 900)
                await snapshot(page, f"pdp-candidate-{idx}")
                await dump_html(page, f"pdp-candidate-{idx}")
            except Exception:
                continue

            pdp_url = page.url
            try:
                html = await page.content()
            except Exception:
                html = ""

            store_name = await ensure_expected_store(page, STORE_QUERY, attempts=3)

            if EAN and (EAN in pdp_url or EAN in html):
                matched_ean = EAN
            elif EAN:
                # Not the right product, go back and try another
                try:
                    await page.go_back()
                    await page.wait_for_load_state('domcontentloaded')
                    await human_pause(page, 900, 600)
                    continue
                except Exception:
                    continue

            # ensure store is set on PDP as well
            store_name = await ensure_expected_store(page, STORE_QUERY, attempts=3)

            try:
                title_text = await page.locator('h1').first.text_content(timeout=6000)
                if title_text:
                    title_text = clean_spaces(title_text)
            except Exception:
                pass

            try:
                price_locator = page.locator("[data-testid='pdp-price'] span, [data-testid='pdp-price'], .product-price, [class*='price']").first
                raw_price = await price_locator.text_content(timeout=6000)
                if raw_price:
                    raw_price = clean_spaces(raw_price.replace('\xa0', ' '))
                    normalized = re.sub(r"[^0-9,\.]", "", raw_price)
                    m = re.search(r"(\d+[\.,]\d{2})", normalized)
                    if m:
                        price_value = m.group(1).replace(',', '.').strip()
                        try:
                            price_text = f"{float(price_value):.2f}"
                        except ValueError:
                            price_text = price_value
                    else:
                        price_text = raw_price
            except Exception:
                pass

            try:
                unit_locator = page.locator("[data-testid*='unit-price'], [class*='unit-price'], text=/€\s*\/\s*(?:l|kg)/i")
                if await unit_locator.count():
                    txt = await unit_locator.first.text_content(timeout=4000)
                    if txt:
                        unit_text = clean_spaces(txt.replace('\xa0', ' ')).replace(' / ', '/').replace(' ', '')
            except Exception:
                pass

            try:
                ld_scripts = page.locator("script[type='application/ld+json']")
                for i in range(await ld_scripts.count()):
                    raw_ld = await ld_scripts.nth(i).text_content()
                    if not raw_ld:
                        continue
                    try:
                        data_ld = json.loads(raw_ld)
                    except Exception:
                        continue
                    items_ld = data_ld if isinstance(data_ld, list) else [data_ld]
                    for item_ld in items_ld:
                        if not isinstance(item_ld, dict):
                            continue
                        if item_ld.get('@type') != 'Product':
                            continue
                        if not title_text and item_ld.get('name'):
                            title_text = clean_spaces(str(item_ld.get('name')))
                        if not image_url and item_ld.get('image'):
                            image_data = item_ld.get('image')
                            if isinstance(image_data, list) and image_data:
                                image_url = image_data[0]
                            elif isinstance(image_data, str):
                                image_url = image_data
                        nutrition = item_ld.get('nutrition')
                        if isinstance(nutrition, dict):
                            grade = nutrition.get('nutriscoreGrade') or nutrition.get('nutriScore') or nutrition.get('nutriscore')
                            if grade and isinstance(grade, str):
                                nutriscore_grade = grade.strip().lower()[:1]
                            icon = nutrition.get('nutriscoreUrl') or nutrition.get('nutriscoreImage')
                            if icon and isinstance(icon, str):
                                nutriscore_image = icon
                        if not quantity_text and item_ld.get('size'):
                            quantity_text = clean_spaces(str(item_ld.get('size')))
            except Exception:
                pass

            if not quantity_text:
                search_fields = []
                try:
                    info_section = page.locator("section, div").filter(has_text=re.compile(r"EAN|\d"))
                    for i in range(min(await info_section.count(), 6)):
                        txt = await info_section.nth(i).text_content(timeout=1000)
                        if txt:
                            search_fields.append(txt)
                except Exception:
                    pass
                search_fields.append(title_text or "")
                blob = "\n".join(search_fields)
                mqty = re.search(r"(\d+[\.,]?\d*)\s*(ml|l|cl|kg|g)\b", blob, flags=re.IGNORECASE)
                if mqty:
                    val, unit = mqty.groups()
                    quantity_text = clean_spaces(f"{val} {unit.upper()}")

            if price_text:
                break

        if price_text:
            break

        # if we reached here, price not found; go back to results for next term
        try:
            await page.go_back()
            await page.wait_for_load_state('domcontentloaded')
            await human_pause(page, 900, 600)
        except Exception:
            pass

    if not USING_CDP:
        await browser.close()
    await p.stop()

    if not price_text or not pdp_url:
        return Result(status="NO_PRICE", url=pdp_url, store=store_name, title=title_text)

    price_text = clean_spaces(price_text)
    if re.match(r"^\d+\.\d{2}$", price_text):
        price_text = price_text.replace('.', ',')
    unit_text = clean_spaces(unit_text)
    if unit_text and '€' in unit_text:
        amount, sep, tail = unit_text.partition('€')
        if amount:
            unit_text = amount.replace('.', ',') + sep + tail
    quantity_text = clean_spaces(quantity_text)
    cleaned_store = clean_spaces(store_name)
    expected_clean = clean_spaces(expected_store)

    note_text = None
    if expected_clean:
        if not cleaned_store:
            note_text = f"store_unreadable expected={expected_clean}"
        elif not store_matches(cleaned_store, expected_clean):
            note_text = f"store_mismatch current={cleaned_store} expected={expected_clean}"

    final_store = cleaned_store or expected_clean

    return Result(
        status="OK",
        price=price_text,
        store=final_store,
        url=pdp_url,
        unit_price=unit_text,
        quantity=quantity_text,
        title=title_text,
        matched_ean=matched_ean,
        note=note_text,
        image=image_url,
        nutriscore_grade=nutriscore_grade,
        nutriscore_image=nutriscore_image,
    )


if __name__ == "__main__":
    try:
        res = asyncio.run(run())
    except KeyboardInterrupt:
        print("ABORT")
        sys.exit(130)
    payload = json.dumps(res.__dict__, ensure_ascii=False)
    payload = payload.replace("\\r", "\\u000d").replace("\\n", "\\u000a")
    print(payload)
