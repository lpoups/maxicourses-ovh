#!/usr/bin/env python3
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

EAN = os.environ.get("EAN", "").strip()
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
STORE_ID = os.environ.get("AUCHAN_STORE_ID", "6117")
STORE_SLUG = os.environ.get(
    "AUCHAN_STORE_SLUG", "auchan-drive-supermarche-talence-gallieni"
).strip("/")
STORE_URL = os.environ.get(
    "AUCHAN_STORE_URL",
    f"https://www.auchan.fr/drive/magasins/{STORE_SLUG}",
)
STORE_LABEL = os.environ.get(
    "AUCHAN_STORE_LABEL", "Auchan Drive Supermarché Talence-Gallieni"
)
DEFAULT_USER_AGENT = os.environ.get(
    "AUCHAN_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.6613.18 Safari/537.36",
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
    selectors = [
        "#didomi-notice-agree-button",
        "#onetrust-accept-btn-handler",
        "button:has-text('Tout accepter')",
        "button:has-text('Accepter')",
        "button:has-text(\"J'accepte\")",
    ]
    for selector in selectors:
        button = page.locator(selector).first
        try:
            if await button.count():
                await button.click()
                await page.wait_for_timeout(400)
                return
        except Exception:
            continue


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


STORE_CONTEXT_SCRIPT = """
        (store) => {
            try {
                const {id, slug, label} = store;
                if (id) {
                    window.localStorage.setItem('storeId', id);
                    window.localStorage.setItem('journeyStoreId', id);
                }
                if (slug) {
                    window.localStorage.setItem('storeSlug', slug);
                }
                if (label) {
                    window.localStorage.setItem('storeName', label);
                }
            } catch (e) {}
        }
    """


async def install_store_context(page) -> None:
    payload = {"id": STORE_ID, "slug": STORE_SLUG, "label": STORE_LABEL}
    try:
        await page.add_init_script(STORE_CONTEXT_SCRIPT, payload)
    except Exception:
        pass


async def sync_store_context(page) -> None:
    payload = {"id": STORE_ID, "slug": STORE_SLUG, "label": STORE_LABEL}
    try:
        await page.evaluate(STORE_CONTEXT_SCRIPT, payload)
    except Exception:
        pass


async def prepare_store_page(page) -> None:
    log(f"goto store page {STORE_URL}")
    await page.goto(STORE_URL, wait_until="domcontentloaded")
    await sync_store_context(page)
    await accept_cookies(page)
    await close_delivery_modal(page)
    await page.wait_for_timeout(800)


async def focus_search_input(page):
    selectors = [
        "input[placeholder*='Rechercher']",
        "input[data-testid='search-input']",
        "input[type='search']",
    ]
    for selector in selectors:
        field = page.locator(selector).first
        try:
            if await field.count():
                await field.click()
                return field
        except Exception:
            continue
    return None


async def search_ean(page, ean: str) -> bool:
    if not (ean and ean.isdigit()):
        return False
    input_node = await focus_search_input(page)
    if not input_node:
        log("search input not found")
        return False
    try:
        await input_node.fill("")
        await page.wait_for_timeout(200)
        await input_node.type(ean, delay=40)
        await page.wait_for_timeout(150)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1200)
    except Exception as exc:
        log(f"search typing failed: {exc}")
        return False

    result_cards = page.locator(
        "article.product-thumbnail a[href*='/pr-'], "
        "a[href*='/produit/'], a[href*='/pr-']"
    )
    try:
        await result_cards.first.wait_for(timeout=8000)
        log("results visible, opening first candidate")
    except Exception:
        log("results not visible")
        return False

    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=12000):
            await result_cards.first.click()
        await accept_cookies(page)
        await page.wait_for_timeout(800)
        return True
    except Exception as exc:
        log(f"candidate click failed: {exc}")
        return False


async def reveal_price(page) -> None:
    selectors = [
        "button:has-text(\"Afficher le prix\")",
        "button:has-text(\"Voir le prix\")",
        "button.price-unavailable__button",
        "button.product-unavailable__button",
    ]
    for _ in range(3):
        for selector in selectors:
            button = page.locator(selector).first
            try:
                if await button.count():
                    await button.scroll_into_view_if_needed()
                    await button.click()
                    await page.wait_for_timeout(800)
                    break
            except Exception:
                continue
        price_node = page.locator("[data-testid='product-price'], .product-price").first
        if await price_node.count():
            return
        await page.wait_for_timeout(400)


def clean_price(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"(\d+[\.,]\d{2})", text.replace("\xa0", " "))
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
    components = _parse_quantity_components(value)
    if not components:
        return value.strip() if isinstance(value, str) else None
    amount, _, display_unit = components
    return _format_quantity_text(amount, display_unit)


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
    await reveal_price(page)
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
    if not price_text:
        price_text = clean_price(html)
    price_value = clean_price(price_text)
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
    if not quantity:
        quantity = extract_quantity(html)
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

    return Result(
        status="OK",
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

    storage_state = state_path_for("auchan")
    p, browser, context, page = await make_context(
        headless=HEADLESS,
        proxy=PROXY,
        storage_state_path=storage_state,
        user_agent=DEFAULT_USER_AGENT,
        use_stealth=False,
    )

    try:
        await install_store_context(page)
        await prepare_store_page(page)
        searched = await search_ean(page, EAN)
        if not searched:
            return Result(
                status="NO_RESULTS",
                note=f"search_failed:{EAN}",
                store=STORE_LABEL,
            )
        result = await extract_from_pdp(page)
        if result:
            return result
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
    print(json.dumps(payload.__dict__, ensure_ascii=False))
