
import asyncio
import os
import json
import re
from playwright.async_api import async_playwright

# Configuration
EAN = "5449000283900"
CDP_URL = "http://127.0.0.1:9223"

# Store IDs (From source inspection)
STORES = [
    {"name": "Market Fondaudège", "id": "1911"},
    {"name": "City Balguerie", "id": "800041"},
    {"name": "Super Lormont", "id": "738"},
]

async def set_store_cookie(context, store_id):
    await context.add_cookies([
        {
            "name": "FRONTAL_STORE",
            "value": store_id,
            "domain": ".carrefour.fr",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Lax",
        }
    ])
    print(f"[Cookie] Set FRONTAL_STORE={store_id}")

async def extract_price(page, store_name):
    # Quick dirty extraction to verify the page state
    try:
        # Check title
        title = await page.title()
        
        # Check price
        price_loc = page.locator("[data-testid='pdp-price'] span, .product-price, .ds-title").first
        price = await price_loc.text_content() if await price_loc.count() else "N/A"
        
        # Check store name in header
        store_picker = page.locator("[data-testid='store-switcher__current-store']").first
        current_store = await store_picker.text_content() if await store_picker.count() else "Unknown"
        
        print(f"[{store_name}] URL: {page.url}")
        print(f"[{store_name}] Store: {current_store.strip()} | Price: {price.strip()} | Title: {title.strip()}")
        
        if price == "N/A":
             # Dump partial content text
             text = await page.text_content("body")
             print(f"[{store_name}] debug body text len: {len(text)}")
             if "produits" in text:
                 print(f"[{store_name}] 'produits' found in body.")
        
        return price.strip()
    except Exception as e:
        print(f"[{store_name}] Extraction failed: {e}")
        return None

async def main():
    async with async_playwright() as p:
        print(f"Connecting to CDP: {CDP_URL}")
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # 1. Start with Market
        target_store = STORES[0]
        print(f"\n--- Testing 1: {target_store['name']} ({target_store['id']}) ---")
        await set_store_cookie(context, target_store["id"])
        
        # Initial Search
        print("Navigating to search page...")
        await page.goto(f"https://www.carrefour.fr/s?q={EAN}")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(3) 
        
        await extract_price(page, target_store["name"])
        
        # 2. Switch to City
        target_store = STORES[1]
        print(f"\n--- Testing 2: {target_store['name']} ({target_store['id']}) ---")
        await set_store_cookie(context, target_store["id"])
        
        print(f"Reloading page to {page.url} ...")
        await page.goto(page.url) # Explicit GoTo
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(3)
        
        await extract_price(page, target_store["name"])

        # 3. Switch to Super
        target_store = STORES[2]
        print(f"\n--- Testing 3: {target_store['name']} ({target_store['id']}) ---")
        await set_store_cookie(context, target_store["id"])
        
        print(f"Reloading page to {page.url} ...")
        await page.goto(page.url) # Explicit GoTo
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(3)
        
        await extract_price(page, target_store["name"])
        
        print("\nTest Complete.")

if __name__ == "__main__":
    asyncio.run(main())
