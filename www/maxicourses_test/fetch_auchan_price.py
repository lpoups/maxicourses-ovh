#!/usr/bin/env python3
"""
CRITICAL: DO NOT MODIFY THIS FILE WITHOUT EXPLICIT USER APPROVAL.
THIS FILE CONTAINS STRICTLY VALIDATED LOGIC FOR AUCHAN COLLECTION.
ANY CHANGE CAN BREAK THE COLLECTION PROCESS.
RESTORED FROM PATCHES: cookies, disable_fallback, sanitization.
"""
"""Auchan Talence fetcher — minimal flow: load store page, search EAN, open PDP."""
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import unicodedata

from rich import print

import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for
from seed_catalog import all_seeds

EAN = (os.environ.get("EAN") or os.environ.get("QUERY") or "").strip()
# FORCE DEBUG for diagnosis
os.environ["AUCHAN_DEBUG"] = "1"
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
DIRECT_URL = (os.environ.get("DIRECT_URL") or "").strip()
SKIP_SEARCH = (os.environ.get("SKIP_SEARCH") or "0").lower() in {"1", "true", "yes"}
STORE_ID = os.environ.get("AUCHAN_STORE_ID", "6117")
STORE_SLUG = os.environ.get(
    "AUCHAN_STORE_SLUG", "auchan-drive-supermarche-talence-gallieni"
).strip("/")
STORE_URL = os.environ.get(
    "AUCHAN_STORE_URL",
    f"https://www.auchan.fr/magasins/drive/{STORE_SLUG}/s-{STORE_ID}",
)
STORE_LABEL = os.environ.get(
    "AUCHAN_STORE_LABEL", "Auchan Drive Supermarché Talence-Gallieni"
)
DEFAULT_USER_AGENT = os.environ.get(
    "AUCHAN_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
)

SEED_DATA = all_seeds()
DESCRIPTOR_ENTRY = SEED_DATA.get(EAN) if (EAN and EAN in SEED_DATA) else None


@dataclass
class Result:
    status: str
    price: Optional[str] = None
    unit_price: Optional[str] = None
    quantity: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    matched_ean: Optional[str] = None
    store: Optional[str] = None
    note: Optional[str] = None
    image: Optional[str] = None


def log(message: str) -> None:
    try:
        sys.stderr.write(f"[auchan] {message}\n")
    except Exception:
        pass


async def accept_cookies(page) -> None:
    try:
        # Strategy 1: TrustCommander / OneTrust Standard Buttons
        # Use localized text search first as it is robust against obfuscated classes
        button_texts = [
            "Accepter et fermer", 
            "Tout accepter", 
            "Accepter", 
            "J'accepte", 
            "Continuer sans accepter"
        ]
        
        for text in button_texts:
            # Look for button or link with exact or partial text, notably inside consent modals
            # We use a broad selector to catch it
            try:
                # Use a broad selector for buttons and links containing the text
                btn = page.locator(f"button:has-text('{text}'), a:has-text('{text}')").first
                if await btn.count() > 0 and await btn.is_visible():
                    log(f"Found cookie button with text: {text}")
                    await btn.click(timeout=3000)
                    await page.wait_for_timeout(1000)
                    return
            except Exception:
                pass

        # Strategy 2: Common Consent ID selectors
        selectors = [
             "#onetrust-accept-btn-handler",
             "#onetrust-banner-sdk button#onetrust-accept-btn-handler",
             "button#didomi-notice-agree-button",
             "button[id*='cookie-accept']",
             "button[class*='cookie-accept']",
             "#popin_tc_privacy_button_2", # TrustCommander specific?
             ".tc-reset-css button" # Generic TrustCommander
        ]
        
        for sel in selectors:
            try:
                elem = page.locator(sel).first
                if await elem.count() > 0 and await elem.is_visible():
                     log(f"Found cookie button via selector: {sel}")
                     await elem.click(timeout=3000)
                     await page.wait_for_timeout(1000)
                     return
            except Exception:
                pass

    except Exception as e:
        log(f"Cookie acceptance warning: {e}")


async def close_delivery_modal(page) -> None:
    selectors = [
        "#journey-update-modal button.layer__close",
        "#journey-update-modal button[data-testid='journey-update-modal-close']",
        "#journey-update-modal button:has-text('Fermer')",
    ]
    for selector in selectors:
        button = page.locator(selector).first
        try:
            if await button.count():
                await button.click()
                await page.wait_for_timeout(200)
                break
        except Exception:
            continue


async def choose_drive(page) -> None:
    """
    Selects the store if the 'Choisir ce drive' button is present.
    """
    selectors = [
        "button:has-text('Choisir ce Drive')",
        "button:has-text('Choisir ce magasin')",
        "button.journey-button",
    ]
    
    log("Checking for 'Choisir ce drive' button...")
    
    try:
        # Wait for network to be idle to ensure button is interactive
        try:
             await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
             pass

        target_button = None
        for selector in selectors:
            btn = page.locator(selector).first
            if await btn.count() and await btn.is_visible():
                target_button = btn
                log(f"Found visible button: {selector}")
                break
        
        if not target_button:
            log("No 'Choisir ce drive' button found. Maybe already selected?")
            return

        button_text = await target_button.text_content()
        log(f"Found 'Choisir ce drive' button. Text: '{button_text.strip() if button_text else ''}'")

        # Hammer Click Strategy: Retry clicking until Toast appears
        max_click_attempts = 5
        for click_attempt in range(max_click_attempts):
            log(f"Clicking 'Choisir ce drive' (Attempt {click_attempt + 1}/{max_click_attempts})...")
            try:
                await target_button.scroll_into_view_if_needed()
                
                # Human-like click simulation with randomization
                box = await target_button.bounding_box()
                if box:
                    import random
                    # Add random offset to avoid dead-center detection
                    offset_x = random.uniform(-5, 5)
                    offset_y = random.uniform(-5, 5)
                    target_x = box["x"] + box["width"] / 2 + offset_x
                    target_y = box["y"] + box["height"] / 2 + offset_y
                    
                    await page.mouse.move(target_x, target_y)
                    await page.wait_for_timeout(random.randint(150, 300)) # Variable hover
                    await page.mouse.down()
                    await page.wait_for_timeout(random.randint(80, 150)) # Variable press
                    await page.mouse.up()
                else:
                    # Fallback if no box
                    await target_button.click(force=True, timeout=1000)

            except Exception as e:
                log(f"Click failed: {e}")

            log("Waiting for 'C'est noté' popup...")
            try:
                toast = page.locator("div:has-text(\"C'est noté\")").first
                # Short wait to see if this click worked
                await toast.wait_for(state="visible", timeout=3000)
                log("✅ Toast 'C'est noté' APPEARED.")
                
                log("Waiting for 'C'est noté' popup to DISAPPEAR (User Requirement)...")
                await toast.wait_for(state="hidden", timeout=15000)
                log("✅ Toast DISAPPEARED. Proceeding to search.")
                return 
            except Exception:
                log("⚠️ Toast did not appear yet. Retrying click...")
                await page.wait_for_timeout(500)

        log("❌ FATAL: Toast never appeared after multiple clicks. Falling back to blind wait.")
        await page.wait_for_timeout(4000)

    except Exception as e:
        log(f"Error in choose_drive: {e}")


async def prepare_store_page(page) -> None:
    log(f"goto store page {STORE_URL}")
    await page.goto(STORE_URL, wait_until="domcontentloaded")
    await accept_cookies(page)
    await close_delivery_modal(page)
    await choose_drive(page)


async def focus_search_input(page):
    selectors = [
        "input[placeholder*='Rechercher']",
        "input[data-testid='search-input']",
        "input[type='search']",
    ]
    for selector in selectors:
        field = page.locator(selector).first
        try:
            # Add wait to handle slow loading pages (especially if browser is busy)
            await field.wait_for(state="visible", timeout=5000)
            if await field.count():
                await field.click()
                return field
        except Exception:
            continue
    return None


async def search_ean(page, ean: str) -> tuple[bool, Optional[str]]:
    """
    Searches for EAN and returns (success, price_from_search_results).
    The price appears on search results page BEFORE clicking the product.
    """
    if not (ean and ean.isdigit()):
        return False, None
    result_cards = page.locator(
        "article.product-thumbnail a[href*='/pr-'], "
        "a[href*='/produit/'], a[href*='/pr-']"
    )

    for attempt in range(2):
        if attempt == 0:
            input_node = await focus_search_input(page)
            if not input_node:
                log("search input not found")
                continue
            try:
                await input_node.fill("")
                await page.wait_for_timeout(200)
                await input_node.type(ean, delay=40)
                await page.wait_for_timeout(150)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1200)
            except Exception as exc:
                log(f"search typing failed: {exc}")
                continue
        else:
            # USER STRICT INSTRUCTION: NO REFRESH / NO GOTO
            log("Search typing failed, but fallback (refresh) is DISABLE per user request.")
            return False, None

        try:
            await result_cards.first.wait_for(timeout=8000)
            log("results visible, extracting price from search results")
            break
        except Exception:
            log("results not visible")
    else:
        return False, None

    # Extract price from the FIRST search result card (before clicking)
    price_from_search = None
    try:
        # Try multiple selectors for price in search results
        first_card = result_cards.first
        price_selectors = [
            ".product-thumbnail__price",
            "[data-testid='product-price']",
            ".product-price",
            "[class*='price']"
        ]
        for selector in price_selectors:
            price_node = first_card.locator(selector).first
            if await price_node.count():
                price_text = await price_node.text_content()
                price_from_search = clean_price(price_text)
                if price_from_search:
                    log(f"price from search results: {price_from_search}")
                    break
    except Exception as e:
        log(f"failed to extract price from search results: {e}")

    # Now click to go to PDP for other details
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=12000):
            await result_cards.first.click()
        await accept_cookies(page)
        await page.wait_for_timeout(800)
        return True, price_from_search
    except Exception as exc:
        log(f"candidate click failed: {exc}")
        return False, price_from_search


async def reveal_price(page) -> None:
    selectors = [
        "button:has-text(\"Afficher le prix\")",
        "button:has-text(\"Voir le prix\")",
        "button.price-unavailable__button",
        "button.product-unavailable__button",
    ]
    log(f"Attempting to reveal price (clicking 'Afficher le prix')...")
    for _ in range(3):
        button_found = False
        for selector in selectors:
            button = page.locator(selector).first
            try:
                if await button.count() and await button.is_visible():
                    log(f"Found reveal price button: {selector}")
                    await button.scroll_into_view_if_needed()
                    await button.click(force=True)
                    log("Clicked reveal button.")
                    await page.wait_for_timeout(800)
                    button_found = True
                    break
            except Exception as e:
                log(f"Error clicking reveal button {selector}: {e}")
                continue
        
        # Check if price appeared
        price_node = page.locator("[data-testid='product-price'], .product-price").first
        if await price_node.count():
            log("Price revealed!")
            return
        
        if not button_found:
             log("No reveal price button found on this attempt.")
        
        await page.wait_for_timeout(400)
    log("Failed to reveal price after retries.")


def clean_price(text: Optional[str], *, require_currency: bool = True) -> Optional[str]:
    if not text:
        return None
    normalized = text.replace("\xa0", " ")
    if require_currency:
        currency_patterns = [
            r"(\d+[\.,]\d{2})\s*(?:€|&euro;)",
            r"(?:€|&euro;)\s*(\d+[\.,]\d{2})",
        ]
        for pattern in currency_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                value = match.group(1) or match.group(2)
                if value:
                    return value.replace(",", ".")
        return None
    match = re.search(r"(\d+[\.,]\d{2})", normalized)
    if not match:
        return None
    return match.group(1).replace(",", ".")


def _normalize_token(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.strip().lower()


UNIT_ALIASES = {
    "ml": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "cl": "cl",
    "centilitre": "cl",
    "centilitres": "cl",
    "l": "l",
    "litre": "l",
    "litres": "l",
    "g": "g",
    "gramme": "g",
    "grammes": "g",
    "kg": "kg",
    "kilogramme": "kg",
    "kilogrammes": "kg",
    "capsule": "caps",
    "capsules": "caps",
    "caps": "caps",
    "dose": "dose",
    "doses": "dose",
    "piece": "piece",
    "pieces": "piece",
    "pièce": "piece",
    "pièces": "piece",
    "unite": "piece",
    "unites": "piece",
    "unité": "piece",
    "unités": "piece",
}

UNIT_DEFINITIONS = {
    "ml": {"factor": 0.001, "unit_label": "L", "display_unit": "L"},
    "cl": {"factor": 0.01, "unit_label": "L", "display_unit": "L"},
    "l": {"factor": 1.0, "unit_label": "L", "display_unit": "L"},
    "g": {"factor": 0.001, "unit_label": "KG", "display_unit": "KG"},
    "kg": {"factor": 1.0, "unit_label": "KG", "display_unit": "KG"},
    "caps": {"factor": 1.0, "unit_label": "CAPSULE", "display_unit": "CAPSULES"},
    "dose": {"factor": 1.0, "unit_label": "DOSE", "display_unit": "DOSES"},
    "piece": {"factor": 1.0, "unit_label": "PIECE", "display_unit": "PIÈCES"},
}

QUANTITY_PATTERN = re.compile(
    r"(\d+(?:[\.,]\d+)?)\s*(ml|millilitres?|cl|centilitres?|l|litres?|g|grammes?|kg|kilogrammes?|caps(?:ules?)?|doses?|pi(?:è|e)ces?|unit(?:é|e)s?)",
    re.IGNORECASE,
)
UNIT_PRICE_PATTERN = re.compile(
    r"(\d+[\.,]\d{2})\s*€\s*/\s*([A-Za-zéèêîûôäâôïüç]+)",
    re.IGNORECASE,
)


def _unit_info(raw_unit: str) -> Optional[dict]:
    key = UNIT_ALIASES.get(_normalize_token(raw_unit))
    if not key:
        return None
    return UNIT_DEFINITIONS.get(key)


def _format_decimal(value: float, digits: int = 3) -> str:
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if text else "0"


def _format_quantity_text(value: float, display_unit: str) -> str:
    if display_unit in {"CAPSULES", "DOSES", "PIÈCES"}:
        if abs(value - round(value)) < 1e-6:
            qty_str = str(int(round(value)))
        else:
            qty_str = _format_decimal(value, digits=3)
    else:
        qty_str = _format_decimal(value, digits=3)
    return f"{qty_str} {display_unit}"


def _parse_quantity_components(text: Optional[str]) -> Optional[tuple[float, str, str]]:
    if not text:
        return None
    match = QUANTITY_PATTERN.search(text)
    if not match:
        return None
    raw_value = match.group(1).replace(",", ".")
    try:
        numeric_value = float(raw_value)
    except ValueError:
        return None
    info = _unit_info(match.group(2))
    if not info:
        return None
    converted = numeric_value * info["factor"]
    return converted, info["unit_label"], info["display_unit"]


def normalize_quantity_string(value: Optional[str]) -> Optional[str]:
    # SANITIZATION PATCH: Return raw value if it looks like a pack or simple quantity
    # Do NOT convert to total Liters/Kg.
    if not value:
        return None
    
    val = value.strip()
    
    # If it looks like "6x33cl" or "6 x 33 cl", keep it!
    # Normalize spaces only.
    if 'x' in val.lower() or '*' in val:
         # Standardize " x " and units casing
         val = re.sub(r"\s*[xX*]\s*", "x", val)
         return val
    
    # If it is simple quantity "1.5L", keep it (maybe normalize decimal separator)
    # Avoid calling _parse_quantity_components which does conversion math.

    # Basic cleanup: 1,5L -> 1.5L. Remove spaces around unit.
    # regex capture number and unit
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s*([a-zA-Z]+)$", val)
    if m:
        qty, unit = m.groups()
        return f"{qty.replace(',', '.')} {unit.upper()}"

    return val


def extract_quantity(html: str) -> Optional[str]:
    components = _parse_quantity_components(html)
    if not components:
        return None
    amount, _, display_unit = components
    return _format_quantity_text(amount, display_unit)


def seed_quantity() -> Optional[str]:
    entry = DESCRIPTOR_ENTRY
    if not isinstance(entry, dict):
        return None
    for key in ("quantity", "seed_primary_quantity"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            normalized = normalize_quantity_string(value)
            return normalized or value.strip()
    return None


def env_quantity() -> Optional[str]:
    raw = os.environ.get("AUCHAN_QUANTITY")
    if not raw:
        return None
    normalized = normalize_quantity_string(raw)
    return normalized or raw.strip()


def parse_quantity_value_for_price(value: Optional[str]) -> Optional[tuple[float, str]]:
    components = _parse_quantity_components(value)
    if not components:
        return None
    amount, unit_label, _ = components
    if amount <= 0:
        return None
    return amount, unit_label


def compute_unit_price_from_quantity(price_value: float, quantity_text: Optional[str]) -> Optional[str]:
    parsed = parse_quantity_value_for_price(quantity_text)
    if not parsed:
        return None
    amount, unit_label = parsed
    if amount <= 0:
        return None
    unit_mapping = {
        "L": "L",
        "KG": "KG",
        "CAPSULE": "CAPSULE",
        "DOSE": "DOSE",
        "PIECE": "PIÈCE",
    }
    label = unit_mapping.get(unit_label, unit_label)
    unit_value = price_value / amount
    return f"{unit_value:.2f}".replace(".", ",") + f" € / {label}"


def normalize_unit_price_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    match = UNIT_PRICE_PATTERN.search(text)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    info = _unit_info(match.group(2))
    if info:
        label = info["unit_label"]
    else:
        label = match.group(2).strip().upper()
    return f"{value:.2f}".replace(".", ",") + f" € / {label}"



async def extract_from_pdp(page) -> Optional[Result]:
    # Retry loop for price extraction (handle missing store selection)
    max_retries = 3
    for attempt in range(max_retries):
        await reveal_price(page)
        if os.environ.get("AUCHAN_DEBUG") == "1":
            try:
                await page.screenshot(path=f"auchan_debug_{attempt}.png", full_page=True)
            except Exception:
                pass
        html = await page.content()
        
        title = None
        try:
            title = await page.locator("h1").first.text_content(timeout=4000)
        except Exception:
            pass

        price_text = None
        price_node = page.locator("[data-testid='product-price'], .product-price").first
        if await price_node.count():
            try:
                price_text = await price_node.text_content()
            except Exception:
                price_text = None
        
        # Enforce currency check as per guide
        if not price_text:
            price_text = clean_price(html, require_currency=True)
        
        price_value = clean_price(price_text, require_currency=True)
        
        if os.environ.get("AUCHAN_DEBUG") == "1":
            log(f"Attempt {attempt+1}: price_text={price_text!r} value={price_value!r}")
            if not price_value:
                # Smart Dump: Find any element with '€'
                log("--- DEBUG: Smart Price Scan ---")
                try:
                    # Find elements containing '€' text
                    elements = await page.locator("*:has-text('€')").all()
                    for i, el in enumerate(elements[:10]): # Limit to first 10 matches
                        try:
                            tag = await el.evaluate("el => el.tagName")
                            cls = await el.get_attribute("class") or ""
                            text = (await el.text_content() or "").strip()
                            if len(text) < 50: # Only interesting if short text
                                log(f"Match {i}: <{tag} class='{cls}'>{text}</{tag}>")
                        except Exception:
                            pass
                    
                    # Also dump body text snippet
                    body_text = await page.inner_text("body")
                    log(f"Body Text Snippet: {body_text[:500]!r}")
                    
                    # Dump Cookies and LocalStorage
                    cookies = await page.context.cookies()
                    log(f"Cookies: {[c['name'] + '=' + c['value'][:10] + '...' for c in cookies]}")
                    
                    ls = await page.evaluate("() => JSON.stringify(localStorage)")
                    log(f"LocalStorage: {ls}")
                    
                except Exception as e:
                    log(f"Smart scan failed: {e}")
                log("------------------------------")
            
        if price_value:
            break
            
        # If no price, maybe store not selected? Try choosing drive again.
        log(f"⚠️ No valid price found (Attempt {attempt+1}/{max_retries}). Retrying store selection...")
        await choose_drive(page)
        await page.wait_for_timeout(2000)
        
    if not price_value:
        return None

    quantity = env_quantity() or seed_quantity()

    unit_price = None
    unit_node = page.locator(".product-price__unit-price").first
    if await unit_node.count():
        try:
            text = await unit_node.text_content()
            unit_price = normalize_unit_price_text(text)
        except Exception:
            pass

    matched_ean = None
    try:
        scripts = page.locator("script[type='application/ld+json']")
        for i in range(await scripts.count()):
            raw = await scripts.nth(i).text_content()
            data = json.loads(raw)
            payloads = data if isinstance(data, list) else [data]
            for payload in payloads:
                if isinstance(payload, dict) and payload.get("@type") == "Product":
                    gtin = payload.get("gtin13") or payload.get("gtin")
                    if gtin:
                        matched_ean = str(gtin).strip()
                    if not quantity:
                        q = payload.get("size") or payload.get("weight")
                        if isinstance(q, str):
                            normalized_q = normalize_quantity_string(q)
                            if normalized_q:
                                quantity = normalized_q
    except Exception:
        pass
    # if not quantity:
    #     quantity = extract_quantity(html) # DISABLED: Too risky (matches "5 L" randomly)
    if not unit_price:
        unit_price = normalize_unit_price_text(html)
    if not matched_ean and EAN and EAN in (page.url or ""):
        matched_ean = EAN

    image = None
    match_img = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
    if match_img:
        image = match_img.group(1)

    try:
        price_amount = float(price_value)
    except ValueError:
        return None
    output_price = f"{price_amount:.2f}".replace(".", ",")
    if not unit_price:
        unit_price = compute_unit_price_from_quantity(price_amount, quantity)

    final_status = "OK"
    try:
        # Check for unavailability indicators
        # 1. "Indisponible" text
        # 2. "Bientôt disponible" text
        # 3. Disabled "Ajouter" button
        if await page.locator("text=Indisponible").count() > 0 or \
           await page.locator("text=Bientôt disponible").count() > 0 or \
           await page.locator("button[disabled]:has-text('Ajouter')").count() > 0:
            log("Product appears unavailable (button disabled or text found). Setting status to INDISPONIBLE.")
            final_status = "INDISPONIBLE"
    except Exception:
        pass

    return Result(
        status=final_status,
        price=output_price,
        unit_price=unit_price,
        quantity=quantity,
        title=title,
        url=page.url,
        matched_ean=matched_ean or EAN or None,
        store=STORE_LABEL,
        note="Auchan Talence",
        image=image,
    )


async def run() -> Result:
    if not EAN:
        return Result(status="NO_EAN", note="EAN required", store=STORE_LABEL)

    # Bypassing scraper.engine.make_context to avoid 'stealth_async' and other hidden scripts
    # This aligns with the user's request to remove "blocking functions"
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    
    cdp_url = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
    log(f"Connecting to CDP (No Stealth): {cdp_url}")
    
    try:
        browser = await p.chromium.connect_over_cdp(cdp_url)
    except Exception as e:
        log(f"CDP Connection failed: {e}")
        return Result(status="ERROR", note="CDP Connection Failed", store=STORE_LABEL)

    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    if context.pages:
        page = context.pages[0]
        log("Attached to existing page (avoiding Captcha).")
    else:
        page = await context.new_page()
        log("Created new page.")
    
    try:
        # Force clear state
        await page.goto("about:blank")
        await page.wait_for_timeout(500)
    except:
        pass
        
    start_url = page.url
    if "auchan.fr" in start_url:
        log("Page already on Auchan, checking if reload needed.")
        if "google" in start_url: # Anti-pattern check
             pass

    # storage_state = state_path_for("auchan") # Ignored in Direct CDP usually unless we load it explicitly
    # But since we use persistent context of CDP, we rely on browser state.


    # Clear cookies to remove corrupt state/overlays
    try:
        await context.clear_cookies()
        log("Cookies cleared to force fresh session.")
    except Exception:
        pass

    # Debug: Log Console and Network
    if os.environ.get("AUCHAN_DEBUG") == "1":
        page.on("console", lambda msg: log(f"CONSOLE: {msg.text}"))
        page.on("requestfailed", lambda req: log(f"REQ_FAILED: {req.url} {req.failure}"))
        # page.on("request", lambda req: log(f"REQ: {req.method} {req.url}")) # Too noisy?
        page.on("response", lambda res: log(f"RESP: {res.status} {res.url}") if res.status >= 400 else None)

    try:
        await prepare_store_page(page)

        if DIRECT_URL:
            try:
                await page.goto(DIRECT_URL, wait_until="domcontentloaded")
                await page.wait_for_timeout(600)
                direct_result = await extract_from_pdp(page)
            except Exception:
                direct_result = None
            if direct_result:
                return direct_result
            if SKIP_SEARCH:
                return Result(
                    status="NO_PRICE",
                    note="direct_url_failed",
                    store=STORE_LABEL,
                    url=DIRECT_URL,
                )

        # Search and get price from search results
        searched, price_from_search = await search_ean(page, EAN)
        if not searched:
            return Result(
                status="NO_RESULTS",
                note=f"search_failed:{EAN}",
                store=STORE_LABEL,
            )
        
        # Extract other details from PDP
        result = await extract_from_pdp(page)
        
        # If we got price from search results but not from PDP, use search price
        if result and not result.price and price_from_search:
            log(f"using price from search results: {price_from_search}")
            result.price = price_from_search
            # Compute unit price if we have quantity
            if result.quantity:
                try:
                    price_float = float(price_from_search.replace(",", "."))
                    unit_price = compute_unit_price_from_quantity(price_float, result.quantity)
                    if unit_price:
                        result.unit_price = unit_price
                except (ValueError, AttributeError):
                    pass
        
        if result:
            return result
        
        # If PDP extraction completely failed but we have search price, return that
        if price_from_search:
            log(f"PDP extraction failed, returning search price only")
            try:
                price_float = float(price_from_search.replace(",", "."))
                formatted_price = f"{price_float:.2f}".replace(".", ",")
            except ValueError:
                formatted_price = price_from_search
            return Result(
                status="OK",
                price=formatted_price,
                url=page.url,
                store=STORE_LABEL,
                note="price_from_search_results",
            )
        
        return Result(
            status="NO_PRICE",
            note="price_missing",
            store=STORE_LABEL,
            url=page.url,
        )
    finally:
        try:
            await browser.close()
            await p.stop()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        payload = asyncio.run(run())
    except KeyboardInterrupt:
        print("ABORT")
        sys.exit(130)
    sys.stdout.write(json.dumps(payload.__dict__, ensure_ascii=False) + "\n")
