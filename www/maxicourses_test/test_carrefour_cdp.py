
import asyncio
import os
from playwright.async_api import async_playwright
import random

async def main():
    cdp_url = os.environ.get("CDP_URL", "http://127.0.0.1:9222") # Try direct local port
    print(f"Connecting to CDP: {cdp_url}")
    
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0]
            await context.clear_cookies()
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
            
            # Navigate
            url = "https://www.carrefour.fr/s?q=5449000283900"
            print(f"Navigating to {url}")
            await page.goto(url, wait_until="domcontentloaded")
            
            # Check for iframe challenge (Turnstile/Cloudflare)
            print("Looking for challenge...")
            await page.wait_for_timeout(2000)
            
            # Try to click Cloudflare checkbox if present
            try:
                # Often in an iframe
                frames = page.frames
                for frame in frames:
                    try:
                        checkbox = frame.locator("input[type='checkbox']").first
                        if await checkbox.count() > 0:
                            print("Found checkbox in frame! Clicking...")
                            await checkbox.click(force=True)
                            await page.wait_for_timeout(1000)
                    except:
                        pass
                    # Or specific Cloudflare selector
                    try:
                        cf_btn = frame.locator("#challenge-stage").first
                        if await cf_btn.count() > 0:
                             print("Found challenge stage! Clicking center...")
                             box = await cf_btn.bounding_box()
                             if box:
                                 await page.mouse.move(box["x"]+10, box["y"]+10)
                                 await page.mouse.down()
                                 await page.wait_for_timeout(100)
                                 await page.mouse.up()
                    except:
                        pass
            except Exception as e:
                print(f"Interaction error: {e}")

            # Human Interaction generic
            print("Simulating human behavior...")
            for _ in range(5):
                await page.mouse.move(random.randint(100, 500), random.randint(100, 500))
                await page.wait_for_timeout(random.randint(200, 500))
                
            await page.wait_for_timeout(5000) # Wait for challenge resolution
            
            # Check for block
            content = await page.content()
            if "Cloudflare" in content or "challenge-platform" in content:
                print("STATUS: CF_BLOCK")
                # Dump content
                with open("carrefour_block.html", "w") as f:
                    f.write(content)
            elif "5449000283900" in content:
                print("STATUS: OK (Found EAN)")
            else:
                title = await page.title()
                print(f"STATUS: UNKNOWN (Title: {title})")
                
            await page.close()
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(main())
