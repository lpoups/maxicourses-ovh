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
from urllib.parse import urljoin, urlparse, parse_qs

from rich import print
import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for
import json

print(f"[DEBUG] Loaded local fetch_carrefour_price.py from {_os.path.abspath(__file__)}", file=_sys.stderr)

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
DIRECT_URL = (os.environ.get("DIRECT_URL") or "").strip()
SKIP_SEARCH = (os.environ.get("SKIP_SEARCH") or "0").lower() in {"1", "true", "yes"}


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


def extract_image_url(image_data):
    """Return a clean URL from Carrefour ld+json image payloads."""
    if not image_data:
        return None
    if isinstance(image_data, str):
        cleaned = clean_spaces(image_data)
        return cleaned or None
    if isinstance(image_data, dict):
        for key in (
            "url",
            "contentUrl",
            "contentURL",
            "content_url",
            "thumbnailUrl",
            "thumbnail",
        ):
            value = image_data.get(key)
            if isinstance(value, str):
                cleaned = clean_spaces(value)
                if cleaned:
                    return cleaned
        for nested_key in ("image", "images", "@list", "@value"):
            nested = image_data.get(nested_key)
            if nested:
                candidate = extract_image_url(nested)
                if candidate:
                    return candidate
        return None
    if isinstance(image_data, (list, tuple, set)):
        for item in image_data:
            candidate = extract_image_url(item)
            if candidate:
                return candidate
    return None


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
            (()=>{const labels=['tout accepter','accepter','j\\'accepte','ok'];
            const btns=[...document.querySelectorAll('button')];
            for(const b of btns){const t=(b.innerText||'').trim().toLowerCase();
                if(labels.some(l=>t.includes(l))){b.click();return true;}}
            return false;})()
            """
        )
    except Exception:
        pass


async def handle_turnstile(page) -> None:
    """Detect and click Cloudflare Turnstile checkboxes."""
    print("Checking for Turnstile/Cloudflare challenge...")
    try:
        await page.wait_for_timeout(2000)
        # 1. Check iframes
        frames = page.frames
        for frame in frames:
            try:
                # Common Turnstile checkbox
                checkbox = frame.locator("input[type='checkbox']").first
                if await checkbox.count() > 0 and await checkbox.is_visible():
                    print("Found Turnstile checkbox! Clicking...")
                    await checkbox.click(force=True)
                    await page.wait_for_timeout(2000)
                    return
                # Cloudflare Challenge Stage
                cf_btn = frame.locator("#challenge-stage").first
                if await cf_btn.count() > 0:
                    print("Found Cloudflare challenge stage! Clicking center...")
                    box = await cf_btn.bounding_box()
                    if box:
                        await gentle_move(page, box["x"] + 10, box["y"] + 10)
                        await page.mouse.down()
                        await page.wait_for_timeout(100)
                        await page.mouse.up()
                        await page.wait_for_timeout(2000)
                        return
            except Exception:
                pass
    except Exception as e:
        print(f"Turnstile error: {e}")


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
    if os.environ.get("CARREFOUR_FRONTAL_STORE") and target:
        return clean_spaces(target)
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


def try_parse_json_state(html_content: str, target_ean: str):
    """
    Attempts to parse window.__INITIAL_STATE__ from HTML and extract product data 
    for the target EAN.
    Returns a dict with extracted fields or None.
    """
    try:
        marker = 'window.__INITIAL_STATE__='
        start_idx = html_content.find(marker)
        if start_idx == -1:
            return None
        start_idx += len(marker)
        end_idx = html_content.find('</script>', start_idx)
        if end_idx == -1:
            return None
        
        json_str = html_content[start_idx:end_idx].strip()
        if json_str.endswith(';'):
            json_str = json_str[:-1]
            
        data = json.loads(json_str)
        route_data_str = data.get('routeData')
        if not route_data_str:
            return None
            
        flat_list = json.loads(route_data_str)
        
        def resolve(idx):
            if isinstance(idx, int) and 0 <= idx < len(flat_list):
                return flat_list[idx]
            return idx

        # Find product object matching EAN
        product_obj = None
        for item in flat_list:
            if isinstance(item, dict):
                # We look for an object that has 'ean' property
                # The 'ean' property might be an index pointing to the EAN string
                raw_ean = item.get('ean')
                if raw_ean:
                    val_ean = resolve(raw_ean)
                    if str(val_ean) == str(target_ean):
                        product_obj = item
                        break
        
        if not product_obj:
            return None

        # Extract fields
        title = resolve(product_obj.get('title'))
        qty_label = resolve(product_obj.get('format')) # e.g. "6x33cL"
        
        # Extract image URL
        image_url = None
        for img_key in ('image', 'images', 'thumbnailUrl', 'thumbnail', 'mainImage'):
            raw_img = product_obj.get(img_key)
            if raw_img:
                resolved_img = resolve(raw_img)
                if isinstance(resolved_img, str) and resolved_img.startswith('http'):
                    image_url = resolved_img
                    break
                elif isinstance(resolved_img, list) and len(resolved_img) > 0:
                    first_img = resolve(resolved_img[0])
                    if isinstance(first_img, str) and first_img.startswith('http'):
                        image_url = first_img
                        break
                    elif isinstance(first_img, dict):
                        img_candidate = first_img.get('url') or first_img.get('contentUrl')
                        if img_candidate:
                            image_url = resolve(img_candidate)
                            break
        
        # Price is usually nested in offers -> ean -> ... -> attributes -> price
        price_val = None
        unit_price_label = None
        
        # Try to find offers
        offers_map = resolve(product_obj.get('offers'))
        if isinstance(offers_map, dict):
            # offers_map keys are EANs, values are indices to offer maps
            offer_ptr = offers_map.get(str(target_ean))
            # If not found, try raw_ean index?
            if not offer_ptr and 'ean' in product_obj:
                 offer_ptr = offers_map.get(str(product_obj['ean']))
                 
            offer_ids = resolve(offer_ptr) # This is a dict of store_id -> offer_node_index
            
            if isinstance(offer_ids, dict):
                # Pick the first one? Or look for current store?
                if len(offer_ids) > 0:
                     first_offer_idx = list(offer_ids.values())[0]
                     offer_node = resolve(first_offer_idx)
                     attrs = resolve(offer_node.get('attributes'))
                     if isinstance(attrs, dict):
                         # Fixed logic: 'price' in attributes points to a price INFO object, not the value directly
                         price_info = resolve(attrs.get('price'))
                         if isinstance(price_info, dict):
                             if 'price' in price_info:
                                 price_val = resolve(price_info.get('price'))
                             
                             # Unit price is often in this same price info object
                             per_unit_lbl = resolve(price_info.get('perUnitLabel'))
                             if per_unit_lbl:
                                 unit_price_label = per_unit_lbl
                         else:
                             # Fallback: maybe it is the value?
                             price_val = price_info
                         
                         # Sometimes it might be in attrs? (Legacy case or different store)
                         if not unit_price_label:
                             per_unit_lbl = resolve(attrs.get('perUnitLabel'))
                             if per_unit_lbl:
                                 unit_price_label = per_unit_lbl

        # Debug Log to file
        with open("debug_json_carrefour.log", "a") as f:
            f.write(f"Parsed EAN {target_ean}: Price={price_val} Qty={qty_label} Unit={unit_price_label}\n")

        return {
            "title": title,
            "quantity": qty_label,
            "price": price_val,
            "unit_price": unit_price_label,
            "image": image_url
        }

    except Exception as e:
        with open("debug_json_carrefour.log", "a") as f:
            f.write(f"JSON Parse Error: {e}\n")
        print(f"[WARN] JSON Parsing failed: {e}")
        return None


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
    residential_proxy = os.environ.get("CARREFOUR_RESIDENTIAL_PROXY")
    # CDP / Turnstile Fix
    p = await async_playwright().start()
    browser = None
    context = None
    page = None

    if USING_CDP and os.environ.get("CDP_URL"):
        # Clean CDP Connection (Bypassing make_context to avoid stealth detection)
        cdp_url = os.environ.get("CDP_URL")
        print(f"Connecting to CDP: {cdp_url}")
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            # Manual Stealth: Hide webdriver property
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
        except Exception as e:
            print(f"CDP Connection Failed: {e}")
            sys.exit(1)
    else:
        # Standard connection (Headless/Stealth)
        p, browser, context, page = await make_context(
            headless=HEADLESS, proxy=PROXY, residential_proxy=residential_proxy,
            storage_state_path=storage_state,
            user_agent=None,
        )

    async def _close_extra(new_page):
        try:
            await new_page.close()
        except Exception:
            pass

    context.on("page", lambda pg: asyncio.create_task(_close_extra(pg)))

    frontal_store_id = os.environ.get("CARREFOUR_FRONTAL_STORE")
    if frontal_store_id:
        try:
            await context.add_cookies([
                {
                    "name": "FRONTAL_STORE",
                    "value": frontal_store_id,
                    "domain": ".carrefour.fr",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ])
        except Exception:
            pass

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
            # Turnstile / Cloudflare Check
            await handle_turnstile(page)
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

    if os.environ.get("CARREFOUR_FRONTAL_STORE") and expected_store:
        store_name = expected_store
    else:
        if os.environ.get("CARREFOUR_FRONTAL_STORE") and expected_store:
            store_name = expected_store
        else:
            store_name = await ensure_expected_store(page, STORE_QUERY, attempts=3)

    async def capture_current_product(allow_back: bool) -> bool:
        nonlocal pdp_url, title_text, price_text, unit_text, quantity_text, matched_ean, image_url, nutriscore_grade, nutriscore_image, store_name
        pdp_url = None
        title_text = None
        price_text = None
        unit_text = None
        quantity_text = None
        matched_ean = None
        image_url = None
        nutriscore_grade = None
        nutriscore_image = None

        pdp_url = page.url
        try:
            html = await page.content()
        except Exception:
            html = ""

        if os.environ.get("CARREFOUR_FRONTAL_STORE") and expected_store:
            store_name = expected_store
        else:
            store_name = await ensure_expected_store(page, STORE_QUERY, attempts=3)

        if EAN and (EAN in (pdp_url or "") or (EAN in html)):
            matched_ean = EAN
        elif EAN:
            if allow_back:
                try:
                    await page.go_back()
                    await page.wait_for_load_state('domcontentloaded')
                    await human_pause(page, 900, 600)
                except Exception:
                    pass
            return False

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
            unit_selectors = [
                "[data-testid='price-per-unit']",
                "[data-testid*='unit-price']",
                "[class*='unit-price']",
            ]
            for sel in unit_selectors:
                locator = page.locator(sel)
                if await locator.count():
                    candidate = await locator.first.text_content(timeout=4000)
                    if candidate:
                        unit_text = clean_spaces(candidate.replace('\xa0', ' '))
                        break
            if not unit_text:
                unit_text = await page.evaluate(
                    """
                    () => {
                      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                      const patterns = /(€\\s*\\/\\s*(?:kg|l|pi.?ce|lavage|unité))/i;
                      while (walker.nextNode()) {
                        const txt = (walker.currentNode.textContent || '').trim();
                        if (!txt) continue;
                        if (patterns.test(txt)) {
                          return txt;
                        }
                      }
                      return null;
                    }
                    """
                )
                if unit_text:
                    unit_text = clean_spaces(str(unit_text))
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
                        image_candidate = extract_image_url(item_ld.get('image'))
                        if image_candidate:
                            image_url = image_candidate
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

        if not nutriscore_grade or not nutriscore_image:
            try:
                dom_nutri = await page.evaluate(
                    """
                    () => {
                      const selectors = [
                        "[data-testid='nutri-score']",
                        "[data-testid='nutrition-nutriscore']",
                        "[class*='nutri-score']",
                        "[class*='NutriScore']"
                      ];
                      let root = null;
                      for (const sel of selectors) {
                        const found = document.querySelector(sel);
                        if (found) { root = found; break; }
                      }
                      let img = root ? root.querySelector('img') : null;
                      if (!img) {
                        img = document.querySelector("img[alt*='Nutri']") || document.querySelector("img[src*='nutri']");
                      }
                      const label =
                        (root && (root.getAttribute('aria-label') || root.getAttribute('data-value'))) ||
                        (img ? img.getAttribute('alt') : null) ||
                        (root ? root.textContent : null);
                      const src = img ? img.getAttribute('src') : null;
                      if (!label && !src) {
                        return null;
                      }
                        return { label, src };
                    }
                    """
                )
            except Exception:
                dom_nutri = None
            if isinstance(dom_nutri, dict):
                label = dom_nutri.get("label") or ""
                dom_src = dom_nutri.get("src")
                candidate_grade: Optional[str] = None
                if isinstance(label, str):
                    cleaned_label = clean_spaces(label) or ""
                    if cleaned_label:
                        match = re.search(r"nutri[- ]?score[^A-E]*([A-E])", cleaned_label, flags=re.IGNORECASE)
                        if not match:
                            match = re.search(r"\b([A-E])\b", cleaned_label, flags=re.IGNORECASE)
                        if match:
                            candidate_grade = match.group(1).lower()
                if isinstance(dom_src, str):
                    cand = clean_spaces(dom_src)
                    if cand:
                        if not cand.lower().startswith("http"):
                            cand = urljoin(page.url, cand)
                        nutriscore_image = cand
                        match = re.search(r"nutri(?:score)?[-_]?([a-e])", cand, flags=re.IGNORECASE)
                        if match:
                            candidate_grade = match.group(1).lower()
                if candidate_grade:
                    nutriscore_grade = candidate_grade

        if not image_url:
            try:
                og_image = await page.locator("meta[property='og:image']").first.get_attribute('content')
                og_image = clean_spaces(og_image) if og_image else None
                if og_image:
                    image_url = og_image
            except Exception:
                pass

        # 1. Try tc_vars (TrustCommander) - often reliable for price/category
        try:
            tc_match = re.search(r"var\s+tc_vars\s*=\s*Object\.assign\([^,]+,\s*(\{.*?\})\)", html, re.DOTALL)
            if tc_match:
                tc_json = tc_match.group(1)
                # Cleanup simple keys if needed or parse loosely
                try:
                    tc_data = json.loads(tc_json)
                    if tc_data.get("product_price"):
                         # tc_vars price is often a float
                         p_val = float(tc_data.get("product_price"))
                         if p_val > 0:
                             price_text = f"{p_val:.2f}"
                    if not matched_ean and tc_data.get("product_EAN"):
                        matched_ean = str(tc_data.get("product_EAN"))
                except Exception:
                    # Fallback regex for tc_vars fields if JSON fails
                    pass
        except Exception:
            pass

        if not quantity_text:
            search_fields = []
            try:
                # 1. Restrict search to likely main product container if possible
                # But 'info_section' strategy is broad. 
                # Let's try to parse Title "Lot de X" first
                if title_text:
                    m_lot = re.search(r"\blot\s+de\s+(\d+)", title_text, flags=re.IGNORECASE)
                    if m_lot:
                         lot_count = int(m_lot.group(1))
                         # Now look for "33cl" or volume in title or blob
                         # Try to find volume ONLY (e.g. 33cl) and multiply
                         pass
            except Exception:
                pass

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
            
            # IMPROVED REGEX: Negative lookbehind to avoid "pour 100ml" (nutrition)
            # Matches: "6x33cl", "1.5L", "500g" but NOT "pour 100 ml"
            mqty = re.search(r"(?<!pour\s)(?<!per\s)(?<!\d\s)\b(\d+(?:[\.,]\d+)?)\s*(ml|cl|dl|l|g|kg)\b", blob, flags=re.IGNORECASE)
            
            # Special case for "NxVV cl" (e.g. 6x33cl) and "Lot de X ... Y cl"
            m_pack = re.search(r"\b(\d+)\s*x\s*(\d+(?:[\.,]\d+)?)?\s*(ml|cl|dl|l|g|kg)\b", blob, flags=re.IGNORECASE)
            
            if m_pack:
                count = float(m_pack.group(1))
                vol = float(m_pack.group(2).replace(',', '.'))
                # Fix: If bad regex detected "6.0x20.0CL" but it should match "6x33", check if 20 is suspicious
                # But let's trust regex unless verified.
                unit = m_pack.group(3).lower()
                quantity_text = f"{count}x{vol}{unit.upper()}"
            elif mqty:
                # If we found "lot de X" in title, maybe apply it?
                m_lot = re.search(r"\blot\s+de\s+(\d+)", title_text or "", flags=re.IGNORECASE)
                val = float(mqty.group(1).replace(',', '.'))
                unit = mqty.group(2)
                if m_lot:
                     count = int(m_lot.group(1))
                     # If val is small (e.g. 33cl), multiply?
                     # heuristic: if val < 10 (L) or < 2000 (ml), it's likely one unit
                     quantity_text = f"{count}x{val}{unit.upper()}"
                else:
                    quantity_text = clean_spaces(f"{val} {unit.upper()}")

        # Math Sanity Check (Implied Quantity)
        calculated_quantity = None
        if price_text and unit_text:
             try:
                 p_clean = float(price_text.replace(',', '.').replace('€', '').strip())
                 # Parse unit price (e.g. "3.12 € / L")
                 u_match = re.search(r"(\d+[\.,]\d+)", unit_text)
                 if u_match:
                     u_val = float(u_match.group(1).replace(',', '.'))
                     if u_val > 0:
                         implied = p_clean / u_val
                         # Detection based on unit text unit
                         if "/ l" in unit_text.lower() or "/l" in unit_text.lower():
                             calculated_quantity = f"{implied:.2f}L"
                         elif "/ kg" in unit_text.lower():
                             calculated_quantity = f"{implied:.2f}KG"
             except Exception:
                 pass
        
        # Override decision: 
        # If calculated quantity exists, it is usually authoritative for the Price/Unit Price ratio.
        # If extracted qty is "100 ML" (junk) OR seems to mismatch significantly, use calculated.
        # "6x33cl" = 1.98L. Calculated "2.68 €/L" -> 1.98L. Perfect match.
        # If we got "6x20cl" (1.2L) vs Calculated (1.98L), we should PREFER Calculated.
        
        if calculated_quantity:
             quantity_text = calculated_quantity # Trust Math for now as regex is flaky on standard text for this site.



        if price_text:
            return True

        if allow_back:
            try:
                await page.go_back()
                await page.wait_for_load_state('domcontentloaded')
                await human_pause(page, 900, 600)
            except Exception:
                pass
        return False

    # MANDATE: Strict EAN Search. Do not fallback to keywords if EAN is known.
    if EAN:
        search_terms = [EAN]
    else:
        search_terms = ([QUERY] if QUERY else [])

    pdp_url = None
    title_text = None
    price_text = None
    unit_text = None
    quantity_text = None
    matched_ean = None
    image_url = None
    nutriscore_grade = None
    nutriscore_image = None

    if DIRECT_URL:
        direct_ok = False
        try:
            await page.goto(DIRECT_URL, wait_until="domcontentloaded")
            await human_pause(page, 1200, 800)
            safe_direct = re.sub(r"[^A-Za-z0-9]", "_", "direct")
            await snapshot(page, f"results-{safe_direct}")
            await dump_html(page, f"results-{safe_direct}")
            direct_ok = await capture_current_product(False)
        except PlaywrightTimeout:
            direct_ok = False
        except Exception:
            direct_ok = False

        if direct_ok:
            search_terms = []
        elif SKIP_SEARCH:
            return Result(status="NO_PRICE", url=DIRECT_URL, store=store_name)

    skip_search_ui = False
    current_url = page.url or ""
    # Relaxed condition: If EAN is in URL (Search or PDP), we optimize.
    if EAN in current_url:
        log_msg = f"[INFO] Context optimization: Page (PDP/Search) matches {EAN}. Reloading to refresh store..."
        print(log_msg, file=sys.stderr)
        try:
             await page.reload(wait_until="domcontentloaded")
             await human_pause(page, 1500, 500)
             skip_search_ui = True
        except Exception:
             pass

    for term in search_terms:
        performed = False
        if skip_search_ui and term == EAN:
             performed = True
        else:
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
            if "Just a moment" in title_check or "Un instant" in title_check or (resp and resp.status == 403):
                print(f"[WARN] Cloudflare challenge detected (Title: {title_check}). Attempting to solve...", file=sys.stderr)
                await snapshot(page, "cf-challenge-start")
                
                # Attempt to solve challenge by waiting and moving mouse
                try:
                    # Wait up to 20s for challenge to resolve
                    for i in range(10):
                        await human_pause(page, 1000, 500)
                        await gentle_move(page, random.randint(100, 800), random.randint(100, 600))
                        
                        # Check if passed
                        new_title = await page.title()
                        if "Just a moment" not in new_title and "Un instant" not in new_title:
                            print(f"[INFO] Challenge passed! New title: {new_title}", file=sys.stderr)
                            await snapshot(page, "cf-challenge-passed")
                            break
                    else:
                        print("[ERROR] Challenge failed after 15s", file=sys.stderr)
                        await snapshot(page, "cf-challenge-failed")
                        await dump_html(page, "cf-challenge-failed")
                        if not USING_CDP:
                            await browser.close()
                        await p.stop()
                        return Result(status="CF_BLOCK", url=search_url)
                except Exception as e:
                    print(f"[ERROR] Error solving challenge: {e}", file=sys.stderr)
                    return Result(status="CF_BLOCK", url=search_url)
        await human_pause(page, 1200, 800)
        safe_term = re.sub(r"[^A-Za-z0-9]", "_", term)[:20]
        await snapshot(page, f"results-{safe_term}")
        await dump_html(page, f"results-{safe_term}")

        # NEW: Try to parse JSON state directly
        try:
             page_content = await page.content()
             json_data = try_parse_json_state(page_content, EAN)
             if json_data and json_data.get('price'):
                 print(f"[INFO] Successfully extracted data from JSON State: {json_data}", file=sys.stderr)
                 
                 price_text = str(json_data.get('price')).replace('.', ',')
                 
                 u_text = json_data.get('unit_price')
                 if u_text:
                     unit_text = u_text.replace('.', ',')
                     
                 q_text = json_data.get('quantity')
                 if q_text:
                     quantity_text = q_text
                     
                 t_text = json_data.get('title')
                 if t_text:
                     title_text = t_text
                     
                 matched_ean = EAN
                 pdp_url = page.url # We are on search page, but effectively we found the product
                 
                 # Utiliser l'image du JSON State en priorité
                 json_img = json_data.get('image')
                 if json_img and isinstance(json_img, str) and json_img.startswith('http'):
                     image_url = json_img
                 else:
                     # FALLBACK: Naviguer vers la PDP pour récupérer l'image
                     print(f"[INFO] JSON State has no image, navigating to PDP...", file=sys.stderr)
                     try:
                         # Trouver et cliquer sur le premier produit
                         product_link = page.locator("a[href^='/p/']").first
                         if await product_link.count() > 0:
                             await product_link.click()
                             await page.wait_for_load_state("domcontentloaded")
                             await human_pause(page, 1000, 500)
                             pdp_url = page.url
                             print(f"[INFO] Now on PDP: {pdp_url}", file=sys.stderr)
                             
                             # Extraire l'image de la PDP
                             # 1. Essayer og:image
                             try:
                                 og_image = await page.locator("meta[property='og:image']").first.get_attribute('content')
                                 if og_image and 'generic' not in og_image.lower() and og_image.startswith('http'):
                                     image_url = clean_spaces(og_image)
                                     print(f"[INFO] Got image from PDP og:image: {image_url[:60]}...", file=sys.stderr)
                             except Exception:
                                 pass
                             
                             # 2. Essayer ld+json si og:image a échoué
                             if not image_url:
                                 try:
                                     html = await page.content()
                                     ld_scripts = page.locator("script[type='application/ld+json']")
                                     for i in range(await ld_scripts.count()):
                                         raw_ld = await ld_scripts.nth(i).text_content()
                                         if not raw_ld:
                                             continue
                                         try:
                                             import json
                                             data_ld = json.loads(raw_ld)
                                             items_ld = data_ld if isinstance(data_ld, list) else [data_ld]
                                             for item_ld in items_ld:
                                                 if isinstance(item_ld, dict) and item_ld.get('@type') == 'Product':
                                                     img_data = item_ld.get('image')
                                                     img_candidate = extract_image_url(img_data)
                                                     if img_candidate:
                                                         image_url = img_candidate
                                                         print(f"[INFO] Got image from PDP ld+json: {image_url[:60]}...", file=sys.stderr)
                                                         break
                                         except Exception:
                                             continue
                                         if image_url:
                                             break
                                 except Exception:
                                     pass
                     except Exception as e:
                         print(f"[WARN] Failed to navigate to PDP for image: {e}", file=sys.stderr)
                 
                 # IMPORTANT: If we found data, we can return immediately or break loop
                 # Returning Result immediately is cleaner
                 
                 cleaned_store = clean_spaces(store_name)
                 expected_clean = clean_spaces(expected_store)
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
                    note="json_state_extraction", # Mark as JSON extracted
                    image=image_url,
                    nutriscore_grade=nutriscore_grade,
                    nutriscore_image=nutriscore_image,
                )
        except Exception as e:
             print(f"[WARN] Error in JSON State extraction: {e}", file=sys.stderr)

        # Optimization Fallback: If we skipped search, we might be on PDP. 
        # If JSON failed, try DOM extraction immediately.
        if skip_search_ui:
             print("[INFO] Optimization active: Attempting direct DOM extraction.", file=sys.stderr)
             dom_success = await capture_current_product(allow_back=False)
             if dom_success:
                 # Helper to return formatted result from captured variables
                 # Refactor: We should ideally unify return logic, but for now reuse the variables set by capture_current_product
                 if price_text:
                     return Result(
                        status="OK",
                        price=price_text,
                        store=store_name,
                        url=pdp_url,
                        unit_price=unit_text,
                        quantity=quantity_text,
                        title=title_text,
                        matched_ean=matched_ean,
                        note="optimized_dom_extraction",
                        image=image_url,
                        nutriscore_grade=nutriscore_grade,
                        nutriscore_image=nutriscore_image,
                    )
        
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

            success = await capture_current_product(True)
            if success:
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
            amount_clean = clean_spaces(amount).replace('.', ',')
            tail_clean = clean_spaces(tail)
            if tail_clean and not tail_clean.startswith('/'):
                tail_clean = f"/ {tail_clean}"
            unit_text = f"{amount_clean} {sep} {tail_clean}".strip()
    quantity_text = clean_spaces(quantity_text)

    if (not unit_text) and quantity_text and price_text:
        qty_match = re.match(r"([0-9]+[\.,]?[0-9]*)\s*(ml|l|cl|g|kg)", quantity_text, re.IGNORECASE)
        if qty_match:
            raw_qty = qty_match.group(1).replace(',', '.').strip()
            unit = qty_match.group(2).lower()
            try:
                qty_value = float(raw_qty)
                price_value = float(price_text.replace(',', '.'))
            except ValueError:
                qty_value = None
                price_value = None
            if qty_value and price_value:
                base_unit = unit
                if unit == 'g':
                    qty_value /= 1000.0
                    base_unit = 'kg'
                elif unit == 'ml':
                    qty_value /= 1000.0
                    base_unit = 'l'
                elif unit == 'cl':
                    qty_value /= 100.0
                    base_unit = 'l'
                if qty_value > 0:
                    unit_price_value = price_value / qty_value
                    unit_text = f"{unit_price_value:.2f} € / {base_unit.upper()}"
                    unit_text = unit_text.replace('.', ',')

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
