#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from playwright.async_api import async_playwright, Page


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rejoue une trace de navigation humaine.")
    parser.add_argument(
        "trace",
        type=Path,
        help="Fichier JSONL généré par record_leclerc_navigation.py",
    )
    parser.add_argument(
        "--cdp-url",
        default="http://localhost:9222",
        help="URL CDP de Chrome.",
    )
    parser.add_argument(
        "--context-index",
        type=int,
        default=0,
        help="Contexte Playwright à utiliser lorsqu'on se connecte à Chrome.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Facteur de vitesse (>1 accélère, <1 ralentit).",
    )
    return parser.parse_args()


def load_events(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    events.sort(key=lambda e: e.get("ts", 0.0))
    return events


async def ensure_navigation(page: Page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded")


async def replay(events: List[Dict[str, Any]], page: Page, speed: float) -> None:
    start_time = time.time()
    base_ts = events[0]["ts"] if events else 0.0

    async def wait_until(event_ts: float) -> None:
        target = (event_ts - base_ts) / max(speed, 1e-3)
        while True:
            elapsed = time.time() - start_time
            if elapsed >= target:
                break
            await asyncio.sleep(min(0.05, target - elapsed))

    async def handle_click(evt: Dict[str, Any]) -> None:
        path = evt.get("data", {}).get("path")
        pos = evt.get("data", {}).get("position") or {}
        if path:
            locator = page.locator(path)
            try:
                count = await locator.count()
            except Exception:
                count = 0
            if count:
                try:
                    await locator.first.click(delay=80)
                    return
                except Exception:
                    pass
        x = pos.get("x")
        y = pos.get("y")
        if x is not None and y is not None:
            await page.mouse.click(x, y, delay=60)

    async def handle_key(evt: Dict[str, Any]) -> None:
        key = evt.get("data", {}).get("key")
        typ = evt.get("data", {}).get("type")
        if not key:
            return
        if typ == "keydown":
            try:
                await page.keyboard.press(key, delay=40)
            except Exception:
                pass

    async def handle_input(evt: Dict[str, Any]) -> None:
        path = evt.get("data", {}).get("path")
        value = evt.get("data", {}).get("value")
        if not path:
            return
        script = """
        (selector, value) => {
            const node = document.querySelector(selector);
            if (!node) return false;
            node.focus({ preventScroll: true });
            const old = node.value;
            if (typeof value === 'string') {
                node.value = value;
            }
            const evt = new Event('input', { bubbles: true });
            node.dispatchEvent(evt);
            if (old !== value) {
                const changeEvt = new Event('change', { bubbles: true });
                node.dispatchEvent(changeEvt);
            }
            return true;
        }
        """
        try:
            await page.evaluate(script, path, value)
        except Exception:
            pass

    async def handle_scroll(evt: Dict[str, Any]) -> None:
        path = evt.get("data", {}).get("path")
        scroll = evt.get("data", {}).get("scroll", {})
        x = scroll.get("x")
        y = scroll.get("y")
        script = """
        (selector, x, y) => {
            let target = document.querySelector(selector);
            if (!target) target = document.documentElement;
            if (typeof x === 'number') target.scrollLeft = x;
            if (typeof y === 'number') target.scrollTop = y;
        }
        """
        try:
            await page.evaluate(script, path, x, y)
        except Exception:
            pass

    for event in events:
        kind = event.get("kind")
        if kind == "navigation":
            # handled separately (first navigation only)
            continue
        await wait_until(event.get("ts", 0.0))
        if kind == "click":
            await handle_click(event)
        elif kind == "key":
            await handle_key(event)
        elif kind == "input":
            await handle_input(event)
        elif kind == "scroll":
            await handle_scroll(event)
        elif kind == "stop":
            break


async def main() -> None:
    args = parse_args()
    events = load_events(args.trace)
    if not events:
        print("Aucun évènement à rejouer.")
        return

    first_nav = next((e for e in events if e.get("kind") == "navigation"), None)
    if not first_nav:
        print("Trace sans navigation initiale, abandonné.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(args.cdp_url)
        contexts = browser.contexts
        if not contexts:
            context = await browser.new_context()
        else:
            index = min(max(args.context_index, 0), len(contexts) - 1)
            context = contexts[index]
        page = await context.new_page()
        await ensure_navigation(page, first_nav.get("data", {}).get("url") or first_nav.get("url"))
        print(f"Rejeu démarré depuis {page.url}")
        await replay(events, page, args.speed)
        print("Rejeu terminé.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interruption utilisateur.")
