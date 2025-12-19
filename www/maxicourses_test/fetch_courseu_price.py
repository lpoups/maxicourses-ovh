#!/usr/bin/env python3
"""
Course U Price Fetcher - Simple Working Version
Based on the method that successfully bypassed Cloudflare
"""
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


# Configuration
HOME_URL = os.environ.get("STORE_URL", "https://www.coursesu.com/drive-superu-eysines")
STORE_NAME = os.environ.get("STORE_NAME", "Super U Eysines")
EAN = (os.environ.get("EAN") or "").strip()
CDP_URL = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
USE_CDP = os.environ.get("USE_CDP", "1") == "1"
HEADLESS = os.environ.get("HEADLESS", "0") != "0"


@dataclass
class Result:
    status: str
    price: Optional[str] = None
    unit_price: Optional[str] = None
    quantity: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    note: Optional[str] = None
    store: Optional[str] = None
    matched_ean: Optional[str] = None
    nutriscore_grade: Optional[str] = None
    nutriscore_image: Optional[str] = None
    image: Optional[str] = None


def build_note(store: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{ts} · {store}"


async def accept_cookies(page) -> None:
    """Click cookie consent button"""
    selectors = [
        "button:has-text('Accepter & Fermer')",
        "#popin_tc_privacy_button_3",
        "button[title='Accepter & Fermer']",
        "button:has-text('Tout accepter')",
        "#onetrust-accept-btn-handler",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(1000)
                sys.stderr.write(f"[COURSEU] Clicked cookie button: {sel}\n")
                return
        except Exception:
            pass


async def perform_search(page, term: str) -> bool:
    """Perform search in the search field"""
    search_selectors = [
        "input[id='q']",
        "input[name='q']",
        "input[type='search']",
        "input[placeholder*='Rechercher']",
    ]
    
    for sel in search_selectors:
        try:
            input_el = page.locator(sel).first
            if await input_el.count() > 0 and await input_el.is_visible():
                await input_el.click()
                await page.wait_for_timeout(500)
                # Effacer le contenu existant
                await input_el.fill("")
                await page.wait_for_timeout(200)
                # FRAPPE HUMAINE: type() avec délai entre chaque caractère (50-150ms)
                await input_el.type(term, delay=100)
                await page.wait_for_timeout(800)  # Pause avant Enter
                await input_el.press("Enter")
                sys.stderr.write(f"[COURSEU] Searched for: {term} (human typing)\n")
                return True
        except Exception as e:
            sys.stderr.write(f"[COURSEU] Search error with {sel}: {e}\n")
    return False


async def extract_price(page) -> tuple:
    """Extract price and product info from JSON-LD structured data"""
    price = None
    title = None
    unit_price = None
    quantity = None
    image = None
    matched_ean = None
    
    try:
        # Get page HTML content
        html_content = await page.content()
        
        # Extract from JSON-LD (structured data) - most reliable method
        import re
        pattern = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
        
        for match in pattern.finditer(html_content):
            try:
                import html as html_module
                raw = html_module.unescape(match.group(1).strip())
                data = json.loads(raw)
                
                # Handle array or single object
                products = data if isinstance(data, list) else [data]
                for item in products:
                    if not isinstance(item, dict):
                        continue
                    
                    # Check if it's a Product
                    item_type = item.get("@type", "")
                    if "Product" not in str(item_type):
                        # Check nested graph
                        if "@graph" in item:
                            for node in item["@graph"]:
                                if isinstance(node, dict) and "Product" in str(node.get("@type", "")):
                                    item = node
                                    break
                            else:
                                continue
                        else:
                            continue
                    
                    # Extract data
                    if not title:
                        title = item.get("name", "").strip()
                    
                    if not quantity:
                        quantity = item.get("size") or item.get("weight") or ""
                    
                    if not image:
                        img = item.get("image")
                        if isinstance(img, list):
                            image = img[0] if img else None
                        elif isinstance(img, str):
                            image = img
                    
                    if not matched_ean:
                        matched_ean = item.get("gtin13") or item.get("gtin") or item.get("sku")
                    
                    # Get price from offers
                    offers = item.get("offers")
                    if isinstance(offers, list):
                        offers = offers[0] if offers else None
                    if isinstance(offers, dict) and not price:
                        raw_price = offers.get("price") or offers.get("priceValue")
                        if raw_price:
                            # Format price
                            try:
                                price_float = float(str(raw_price).replace(",", "."))
                                price = f"{price_float:.2f} €".replace(".", ",")
                            except:
                                price = str(raw_price)
                        
                        # Get unit price if available
                        unit_raw = offers.get("priceSpecification", {})
                        if isinstance(unit_raw, dict):
                            unit_val = unit_raw.get("price")
                            unit_unit = unit_raw.get("referenceQuantity", {}).get("unitText", "")
                            if unit_val:
                                unit_price = f"{unit_val} €/{unit_unit}".strip("/")
                    
                    if price and title:
                        break
                        
            except json.JSONDecodeError:
                continue
            except Exception as e:
                sys.stderr.write(f"[COURSEU] JSON-LD parse error: {e}\n")
        
        # Fallback: try CSS selectors if JSON-LD failed
        if not price:
            sys.stderr.write("[COURSEU] JSON-LD extraction failed, trying CSS selectors...\n")
            
            # Course U uses .product-price which contains both pack price and unit price
            try:
                el = page.locator(".product-price").first
                if await el.count() > 0:
                    text = await el.inner_text()
                    sys.stderr.write(f"[COURSEU] .product-price raw text: '{text}'\n")
                    if "€" in text:
                        # Parse "3,88 €\n0,65 €/l" format
                        lines = [l.strip() for l in text.split('\n') if l.strip()]
                        if lines:
                            price = lines[0]  # "3,88 €"
                            if len(lines) > 1 and "€/" in lines[1]:
                                unit_price = lines[1]  # "0,65 €/l"
            except Exception as e:
                sys.stderr.write(f"[COURSEU] .product-price error: {e}\n")
            
            # Fallback to other selectors
            if not price:
                price_selectors = [
                    ".product-price__amount",
                    ".su-price__main",
                    ".su-price",
                    ".actions-container-price",
                ]
                for sel in price_selectors:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            text = await el.inner_text()
                            if "€" in text:
                                price = text.strip().split('\n')[0]
                                break
                    except:
                        pass
        
        # Get title from H1 if not found
        if not title:
            try:
                h1 = page.locator("h1").first
                if await h1.count() > 0:
                    title = await h1.inner_text()
            except:
                pass
                
    except Exception as e:
        sys.stderr.write(f"[COURSEU] Extraction error: {e}\n")
    
    sys.stderr.write(f"[COURSEU] Extracted: price={price}, title={title[:30] if title else None}..., ean={matched_ean}\n")
    return price, title, unit_price, quantity, image, matched_ean


async def collect() -> Result:
    """Main collection logic"""
    p = None
    browser = None
    
    try:
        p = await async_playwright().start()
        
        if USE_CDP:
            sys.stderr.write(f"[COURSEU] Connecting to CDP at {CDP_URL}\n")
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            
            # Find existing Course U page or use first page
            page = None
            for pg in ctx.pages:
                if "coursesu.com" in pg.url:
                    page = pg
                    sys.stderr.write(f"[COURSEU] Found existing page: {pg.url[:50]}\n")
                    break
            if page is None:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            
            # CRITICAL: Reset cache and cookies before Course U collection
            # This prevents Cloudflare blocks from previous sessions
            sys.stderr.write("[COURSEU] Resetting cache, cookies and storage...\n")
            try:
                # Clear cookies
                await ctx.clear_cookies()
                # Clear cache and storage via CDP
                client = await page.context.new_cdp_session(page)
                await client.send("Network.clearBrowserCache")
                await client.send("Storage.clearDataForOrigin", {
                    "origin": "https://www.coursesu.com",
                    "storageTypes": "all"
                })
                sys.stderr.write("[COURSEU] Cache/cookies reset complete\n")
            except Exception as e:
                sys.stderr.write(f"[COURSEU] Reset warning: {e}\n")
                # Fallback: try simpler cookie clear
                try:
                    await ctx.clear_cookies()
                except Exception:
                    pass
        else:
            browser = await p.chromium.launch(headless=HEADLESS)
            ctx = await browser.new_context()
            page = await ctx.new_page()
        
        current_url = page.url
        current_title = await page.title()
        sys.stderr.write(f"[COURSEU] Current: {current_url[:50]} - {current_title[:30]}\n")
        
        # Check if we need to navigate to Course U
        if "coursesu.com" not in current_url or "drive" not in current_url:
            sys.stderr.write(f"[COURSEU] Navigating to {HOME_URL}\n")
            try:
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2000)
            except PlaywrightTimeout:
                sys.stderr.write("[COURSEU] Navigation timeout\n")
        
        # Check for Cloudflare block
        title = await page.title()
        if "Cloudflare" in title or "Attention Required" in title:
            sys.stderr.write("[COURSEU] Cloudflare block detected!\n")
            return Result(status="CF_BLOCK", note=build_note(STORE_NAME), store=STORE_NAME)
        
        # Accept cookies
        await accept_cookies(page)
        
        # Perform search if EAN provided
        if EAN:
            search_success = await perform_search(page, EAN)
            if search_success:
                await page.wait_for_timeout(3000)
                
                # Check for search results and click first product
                product_links = page.locator("a[href*='/p/']")
                if await product_links.count() > 0:
                    first_product = product_links.first
                    await first_product.click()
                    await page.wait_for_timeout(2000)
                    sys.stderr.write(f"[COURSEU] Clicked product, now on: {page.url}\n")
        
        # Extract product data
        price, title_text, unit_price, quantity, image, matched_ean = await extract_price(page)
        
        # VALIDATION EAN STRICTE: L'EAN extrait doit correspondre à l'EAN recherché
        if matched_ean and str(matched_ean) != str(EAN):
            sys.stderr.write(f"[COURSEU] EAN MISMATCH: found {matched_ean}, expected {EAN} - rejecting product\n")
            return Result(
                status="NO_MATCH",
                note=f"EAN mismatch: found {matched_ean}, expected {EAN}",
                store=STORE_NAME,
                url=page.url,
            )
        
        if not matched_ean:
            sys.stderr.write(f"[COURSEU] WARNING: No EAN found on page - cannot validate product\n")
            # Si pas d'EAN trouvé, on ne peut pas valider le produit = NO_MATCH
            return Result(
                status="NO_MATCH",
                note="No EAN found on product page - cannot validate",
                store=STORE_NAME,
                url=page.url,
            )
        
        if price:
            return Result(
                status="MATCHED",
                price=price,
                unit_price=unit_price,
                quantity=quantity,
                title=title_text,
                url=page.url,
                note=build_note(STORE_NAME),
                store=STORE_NAME,
                matched_ean=matched_ean,
                image=image,
            )
        else:
            return Result(
                status="NO_PRICE",
                title=title_text,
                url=page.url,
                note=build_note(STORE_NAME),
                store=STORE_NAME,
                matched_ean=matched_ean,
            )
            
    except Exception as e:
        sys.stderr.write(f"[COURSEU] Error: {e}\n")
        return Result(status="ERROR", note=str(e), store=STORE_NAME)
    
    finally:
        if p and not USE_CDP:
            await p.stop()


async def main():
    result = await collect()
    print(json.dumps(result.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
