#!/usr/bin/env python3
import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context


@dataclass
class Result:
    status: str
    vendor: Optional[str] = None
    price: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None


async def run() -> Result:
    p, browser, context, page = await make_context(
        headless=False, proxy=os.getenv('PROXY'), storage_state_path=None, user_agent=None
    )
    try:
        # scan existing pages to find a supported vendor tab
        target = None
        vendor = None
        for ctx in browser.contexts:
            pages = ctx.pages
            for pg in pages:
                u = pg.url or ''
                if 'leclercdrive.fr' in u:
                    target = pg; vendor = 'leclerc_drive'; break
                if 'carrefour.fr' in u and '/p/' in u:
                    target = pg; vendor = 'carrefour'; break
                if 'auchan.fr' in u and ('/p-' in u or '/produit' in u):
                    target = pg; vendor = 'auchan'; break
                if 'chronodrive.com' in u:
                    target = pg; vendor = 'chronodrive'; break
            if target:
                break
        if not target:
            await browser.close(); await p.stop()
            return Result(status='NO_TAB')

        await target.bring_to_front()
        await target.wait_for_load_state('domcontentloaded')
        # If chronodrive search page, open first product result automatically
        try:
            if vendor=='chronodrive' and '/recherche' in (target.url or ''):
                sel = "a[href*='/fiche-produit'], a[href*='/produit'], a[href*='/product']"
                await target.wait_for_selector(sel, timeout=5000)
                await target.locator(sel).first.click()
                await target.wait_for_load_state('domcontentloaded')
        except Exception:
            pass

        # generic price extraction
        price = None
        title = None
        try:
            title = await target.locator('h1').first.text_content(timeout=4000)
        except Exception:
            pass
        # JSON-LD first
        try:
            scripts = target.locator("script[type='application/ld+json']")
            n = await scripts.count()
            for i in range(n):
                raw = await scripts.nth(i).text_content()
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                items = data if isinstance(data, list) else [data]
                for it in items:
                    if isinstance(it, dict) and it.get('@type') in ('Product',):
                        offers = it.get('offers')
                        if isinstance(offers, dict):
                            price = price or offers.get('price')
                        elif isinstance(offers, list):
                            for of in offers:
                                if isinstance(of, dict):
                                    price = price or of.get('price')
        except Exception:
            pass
        if not price:
            try:
                # Try several nodes and fall back to full page HTML
                loc = target.locator("*[class*='price'], [data-testid*='price'], [class*='Prix'], [class*='prix']")
                n = await loc.count()
                texts = []
                for i in range(min(n, 20)):
                    try:
                        t = await loc.nth(i).text_content(timeout=1000)
                        if t:
                            texts.append(t)
                    except Exception:
                        pass
                texts.append(await target.content())
                joined = "\n".join(texts).replace('\xa0',' ')

                candidates = []
                # Pattern like 1€73 (avoid per-unit with /)
                for m in re.finditer(r"(\d+)\s*€\s*(\d{2})(?!\s*/)", joined):
                    candidates.append(float(f"{m.group(1)}.{m.group(2)}"))
                # Pattern like 1,73 € or 1.73 € (avoid /)
                for m in re.finditer(r"(\d+[\.,]\d{2})\s*€(?!\s*/)", joined):
                    candidates.append(float(m.group(1).replace(',', '.')))
                # Select the highest plausible unit price (< 100)
                candidates = [c for c in candidates if 0 < c < 100]
                if candidates:
                    price = f"{max(candidates):.2f}"
            except Exception:
                pass

        url = target.url
        await browser.close(); await p.stop()
        if price:
            return Result(status='OK', vendor=vendor, price=price, title=title, url=url)
        return Result(status='NO_PRICE', vendor=vendor, title=title, url=url)
    except Exception:
        try:
            await browser.close(); await p.stop()
        except Exception:
            pass
        return Result(status='ERROR')


if __name__ == '__main__':
    res = asyncio.run(run())
    print(json.dumps(res.__dict__, ensure_ascii=False))
