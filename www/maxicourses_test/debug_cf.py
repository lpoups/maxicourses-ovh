import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
import os

async def run():
    async with async_playwright() as p:
        # Launch options matching our "Deep Stealth" config
        browser = await p.chromium.launch(
            headless=False, # Headed mode via Xvfb
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--window-size=1920,1080",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="fr-FR",
            storage_state="state/carrefour_city.json"
        )
        page = await context.new_page()
        await stealth_async(page)
        
        print("Navigating to Carrefour...")
        try:
            await page.goto("https://www.carrefour.fr/courses", timeout=30000)
        except Exception as e:
            print(f"Navigation error: {e}")
            
        print("Waiting 5s...")
        await page.wait_for_timeout(5000)
        
        title = await page.title()
        print(f"Page Title: {title}")
        
        # Check for specific Cloudflare errors
        content = await page.content()
        if "Error 1020" in content:
            print("DIAGNOSIS: Error 1020 (Access Denied) -> IP BLOCK")
        elif "challenge" in content.lower() or "just a moment" in content.lower():
            print("DIAGNOSIS: Challenge Loop -> JS DETECTION")
        else:
            print("DIAGNOSIS: Unknown State")

        await page.screenshot(path="cf_debug.png", full_page=True)
        print("Screenshot saved to cf_debug.png")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
