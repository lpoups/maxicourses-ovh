#!/usr/bin/env python3
"""Connect to Chrome 9222 and retrieve the Chronodrive slug of the current tab.

Usage:
    USE_CDP=1 python3 extract_chronodrive_slug.py [--cdp http://127.0.0.1:9222]

The script inspects all open tabs and looks for an URL containing
"/magasin/<slug>". It prints the slug and full URL as JSON.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from typing import Optional, List

from playwright.async_api import async_playwright

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
PATTERN = re.compile(r"/magasin/([^/?#]+)", re.IGNORECASE)
SLUG_PATTERNS = [
    re.compile(r'"slug"\s*:\s*"([A-Za-z0-9-]+)"'),
    re.compile(r'"storeSlug"\s*:\s*"([A-Za-z0-9-]+)"'),
    re.compile(r'magasin-([A-Za-z0-9-]+)'),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract Chronodrive store slug from Chrome debug session")
    parser.add_argument("--cdp", default=os.environ.get("CDP_URL", DEFAULT_CDP_URL), help="CDP websocket endpoint")
    parser.add_argument("--timeout", type=int, default=5, help="Seconds to wait for a page to become available")
    return parser.parse_args()


async def _collect_strings(page) -> List[str]:
    strings: List[str] = []
    try:
        html = await page.content()
        if html:
            strings.append(html)
    except Exception:
        pass
    try:
        cookies = await page.evaluate("document.cookie")
        if cookies:
            strings.append(cookies)
    except Exception:
        pass
    for store_accessor in ("window.localStorage", "window.sessionStorage"):
        try:
            entries = await page.evaluate(f"(() => Object.entries({store_accessor} || {{}}))()")
            for _, value in entries or []:
                if isinstance(value, str) and value:
                    strings.append(value)
        except Exception:
            continue
    return strings


def _extract_slug_from_strings(strings: List[str]) -> Optional[str]:
    for blob in strings:
        if not blob:
            continue
        for pattern in SLUG_PATTERNS:
            match = pattern.search(blob)
            if match:
                candidate = match.group(1)
                if candidate:
                    return candidate.lower()
    return None


async def find_slug(cdp_url: str, timeout: int) -> Optional[dict[str, str]]:
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        try:
            contexts = browser.contexts
            for context in contexts:
                pages = context.pages
                if not pages:
                    try:
                        page = await context.wait_for_event("page", timeout=timeout * 1000)
                        pages = [page]
                    except Exception:
                        pages = []
                for page in pages:
                    url = page.url
                    if not url:
                        continue
                    if "chronodrive.com" not in url:
                        continue
                    match = PATTERN.search(url)
                    if match:
                        slug = match.group(1)
                        return {"slug": slug.lower(), "url": url}
                    strings = await _collect_strings(page)
                    slug = _extract_slug_from_strings(strings)
                    if slug:
                        return {"slug": slug, "url": url}
        finally:
            await browser.close()
    return None


def main() -> int:
    if os.environ.get("USE_CDP") != "1":
        print(json.dumps({"error": "USE_CDP must be set to 1 (Chrome debug required)"}))
        return 1

    args = parse_args()
    try:
        result = asyncio.run(find_slug(args.cdp, args.timeout))
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"error": str(exc)}))
        return 1

    if not result:
        print(json.dumps({"status": "NOT_FOUND"}))
        return 2

    print(json.dumps({"status": "OK", **result}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
