#!/usr/bin/env python3
import asyncio
import json
import typing
import os
import re
import sys
from dataclasses import dataclass
from urllib.parse import quote

from rich import print

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    from playwright_stealth import stealth_async
except Exception as e:
    print(f"ERR_IMPORT: {e}")
    sys.exit(2)


EAN = os.environ.get("EAN", "7613035676497").strip()
QUERY = os.environ.get("QUERY", "ricore original 260 g").strip()
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")


def extract_eans(text: str):
    return re.findall(r"(?<!\d)(\d{13})(?!\d)", text)


@dataclass
class Result:
    status: str
    price: typing.Optional[str] = None
    title: typing.Optional[str] = None
    url: typing.Optional[str] = None
    matched_ean: typing.Optional[str] = None
    note: typing.Optional[str] = None


async def run() -> Result:
    launch_kwargs = {"headless": HEADLESS, "timeout": 60000}
    if PROXY:
        launch_kwargs["proxy"] = {"server": PROXY}

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await stealth_async(page)
        except Exception:
            pass

        search_url = f"https://www.e.leclerc/recherche?q={quote(QUERY)}"
        try:
            await page.goto(search_url, wait_until="domcontentloaded")
        except PlaywrightTimeout:
            await browser.close()
            return Result(status="TIMEOUT", note="search_goto")

        # cookie banner
        for txt in ("Tout accepter", "Accepter", "J'accepte"):
            try:
                await page.locator(f"button:has-text('{txt}')").first.click(timeout=3000)
                break
            except Exception:
                pass

        # Wait results container
        try:
            await page.wait_for_selector("a[href*='/prod-']", timeout=10000)
        except Exception:
            # fallback generic link
            pass

        # Collect top N product links
        links = []
        try:
            loc = page.locator("a[href*='/prod-']")
            count = await loc.count()
            for i in range(min(count, 6)):
                href = await loc.nth(i).get_attribute("href")
                if href and href.startswith("/"):
                    links.append("https://www.e.leclerc" + href)
        except Exception:
            pass

        if not links:
            await browser.close()
            return Result(status="NO_RESULTS", url=search_url)

        # Open candidates and check EAN on PDP
        for url in links:
            try:
                await page.goto(url, wait_until="domcontentloaded")
            except Exception:
                continue

            # give time for dynamic PDP content
            try:
                await page.wait_for_timeout(1200)
            except Exception:
                pass

            # Try to read full text then extract EAN(s)
            body_txt = (await page.content())
            eans = extract_eans(body_txt)
            if EAN in eans or not eans:
                # Try to extract price from schema.org JSON first
                price = None
                title = None
                try:
                    scripts = page.locator("script[type='application/ld+json']")
                    n = await scripts.count()
                    for i in range(n):
                        raw = await scripts.nth(i).text_content()
                        try:
                            data = json.loads(raw)
                        except Exception:
                            continue
                        # Product or array of dicts
                        items = data if isinstance(data, list) else [data]
                        for it in items:
                            if isinstance(it, dict) and it.get("@type") in ("Product", "ProductGroup"):
                                title = it.get("name") or title
                                offers = it.get("offers")
                                if isinstance(offers, dict):
                                    price = offers.get("price") or price
                                elif isinstance(offers, list):
                                    for of in offers:
                                        if isinstance(of, dict):
                                            price = of.get("price") or price
                except Exception:
                    pass

                # Fallback DOM selectors for price
                if not price:
                    try:
                        p_loc = page.locator("*[class*='price'], [data-testid*='price']").first
                        price_text = await p_loc.text_content(timeout=6000)
                        if price_text:
                            price_text = price_text.strip().replace('\xa0', ' ')
                            m = re.search(r"(\d+[\.,]\d{2})\s*€", price_text)
                            if m:
                                price = m.group(1).replace(',', '.')
                    except Exception:
                        pass

                if price:
                    await browser.close()
                    return Result(status="OK", price=price, title=title, url=url, matched_ean=EAN if EAN in eans else None)

        await browser.close()
        return Result(status="NO_MATCH", url=links[0])


if __name__ == "__main__":
    try:
        res = asyncio.run(run())
    except KeyboardInterrupt:
        print("ABORT")
        sys.exit(130)
    print(json.dumps(res.__dict__, ensure_ascii=False))
