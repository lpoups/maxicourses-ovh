#!/usr/bin/env python3
import asyncio
import os
import sys
from pathlib import Path

TARGETS = {
    'intermarche': 'intermarche.com',
    'leclercdrive': 'leclercdrive.fr',
    'leclerc': 'e.leclerc',
    'carrefour': 'carrefour.fr',
    'auchan': 'auchan.fr',
    'chronodrive': 'chronodrive.com',
}

async def main(site: str):
    if site not in TARGETS:
        print(f"Unknown site: {site}")
        sys.exit(2)
    cdp_url = os.environ.get('CDP_URL', 'http://127.0.0.1:9222')
    out_path = Path('state') / f"{site}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        contexts = browser.contexts
        target = TARGETS[site]
        for ctx in contexts:
            for page in ctx.pages:
                url = page.url or ''
                if target in url:
                    await page.wait_for_load_state('domcontentloaded')
                    await ctx.storage_state(path=str(out_path))
                    print(f"STATE_SAVED {out_path} from {url}")
                    return
        print(f"No page for {site} found; open the site in Chrome first.")
        sys.exit(3)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("USAGE: save_state_from_cdp.py <site>")
        sys.exit(2)
    asyncio.run(main(sys.argv[1]))
