#!/usr/bin/env python3
import asyncio
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

SITES = {
    'carrefour': 'https://www.carrefour.fr/',
    'courses-carrefour': 'https://courses.carrefour.fr/',
    'leclerc': 'https://www.e.leclerc/',
    'leclercdrive': 'https://www.leclercdrive.fr/',
    'auchan': 'https://www.auchan.fr/',
    'chronodrive': 'https://www.chronodrive.com/',
    'intermarche': 'https://www.intermarche.com/',
}


async def main(site: str):
    if site not in SITES:
        print(f"Unknown site. Choose among: {', '.join(SITES)}")
        sys.exit(2)
    target = SITES[site]
    outdir = Path(__file__).resolve().parent / 'state'
    outdir.mkdir(parents=True, exist_ok=True)
    outfile = outdir / f"{site}.json"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        try:
            await stealth_async(page)
        except Exception:
            pass

        print(f"OPEN {target}\n- Passe les captchas/cookies\n- Choisis un magasin Bordeaux si demandé\n- Connecte-toi si utile")
        delay = os.environ.get('STATE_DELAY_SECONDS')
        await page.goto(target)
        if delay:
            try:
                import time
                secs = int(delay)
                print(f"Waiting {secs} seconds before saving state...")
                time.sleep(max(secs, 0))
            except Exception:
                input("Press Enter when ready...")
        else:
            input("Press Enter when ready...")
        await ctx.storage_state(path=str(outfile))
        await browser.close()
        print(f"STATE_SAVED {outfile}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("USAGE: login_and_save_state.py <site>")
        sys.exit(2)
    asyncio.run(main(sys.argv[1]))
