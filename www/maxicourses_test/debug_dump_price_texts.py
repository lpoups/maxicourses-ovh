#!/usr/bin/env python3
import asyncio, os
from scraper.engine import make_context

async def main():
    p, b, ctx, page = await make_context(headless=False, proxy=os.getenv('PROXY'), storage_state_path=None)
    # find an auchan PDP tab
    target=None
    for c in b.contexts:
        for pg in c.pages:
            if 'auchan.fr' in (pg.url or ''):
                target=pg; break
        if target: break
    if not target:
        print('NO_TAB')
        await b.close(); await p.stop(); return
    await target.bring_to_front(); await target.wait_for_load_state('domcontentloaded')
    loc = target.locator("//*[contains(text(),'€')] ")
    count = await loc.count()
    for i in range(min(count, 20)):
        try:
            h = await loc.nth(i).text_content()
            print(i, (h or '').strip().replace('\xa0',' '))
        except Exception:
            pass
    await b.close(); await p.stop()

if __name__=='__main__':
    asyncio.run(main())

