#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

JS_INSTRUMENTATION = """
(() => {
  const buildPath = (node) => {
    if (!node) return null;
    if (!(node instanceof Element)) return null;
    const parts = [];
    while (node && node.nodeType === Node.ELEMENT_NODE) {
      let descriptor = node.tagName.toLowerCase();
      if (node.id) {
        descriptor += `#${node.id}`;
        parts.unshift(descriptor);
        break;
      }
      if (node.classList.length) {
        descriptor += '.' + Array.from(node.classList).slice(0, 3).join('.');
      }
      const sibling = node.parentElement ? Array.from(node.parentElement.children).filter(n => n.tagName === node.tagName) : [];
      if (sibling.length > 1) {
        const index = sibling.indexOf(node) + 1;
        descriptor += `:nth-of-type(${index})`;
      }
      parts.unshift(descriptor);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };

  const relay = (payload) => {
    if (window.recordEvent) {
      try {
        window.recordEvent(payload);
      } catch (err) {
        console.warn('recordEvent error', err);
      }
    }
  };

  const capture = (type, event) => {
    relay({
      kind: type,
      epoch_ms: Date.now(),
      path: buildPath(event.target),
      value: event.target && event.target.value,
      key: event.key,
      code: event.code,
      url: window.location.href,
      pointer: { x: event.clientX, y: event.clientY },
    });
  };

  document.addEventListener('click', (event) => capture('click', event), true);
  document.addEventListener('input', (event) => capture('input', event), true);
  document.addEventListener('keydown', (event) => capture('key', event), true);
  document.addEventListener('keyup', (event) => capture('key', event), true);
})();
"""


async def human_pause(page, ms: int) -> None:
  await page.wait_for_timeout(max(ms, 100))


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Capture une trace Auchan Talence Gallieni (EAN 3124480200433)")
  parser.add_argument("--cdp-url", default=os.environ.get("CDP_URL", "http://127.0.0.1:9222"))
  parser.add_argument("--out", default="../traces/auchan-20251104-talence-orangina.jsonl")
  parser.add_argument("--ean", default="3124480200433")
  parser.add_argument("--store-url", default="https://www.auchan.fr/magasins/drive/auchan-drive-supermarche-talence-gallieni/s-6117")
  return parser.parse_args()


async def ensure_cookie_accept(page) -> None:
  selectors = [
    "button#onetrust-accept-btn-handler",
    "button:has-text(\"Tout accepter\")",
    "button:has-text(\"Accepter\")",
  ]
  for sel in selectors:
    try:
      btn = page.locator(sel).first
      if await btn.count():
        await btn.click()
        await human_pause(page, 1500)
        return
    except PlaywrightTimeout:
      continue
    except Exception:
      continue


async def ensure_drive_selected(page) -> None:
  selectors = [
    "button:has-text(\"Choisir ce drive\")",
    "button:has-text(\"Choisir ce Drive\")",
    "button[data-testid='choose-this-drive']",
  ]
  for sel in selectors:
    try:
      btn = page.locator(sel).first
      if await btn.count():
        await btn.click()
        await human_pause(page, 1200)
        return
    except Exception:
      continue


async def type_search(page, text: str) -> None:
  toggle_selectors = [
    "button[data-testid='current-search-button']",
    "button[data-testid='search-trigger']",
    "button:has-text(\"Rechercher\")",
    "button.header-search__button",
    "button:has([data-icon='search'])",
  ]
  for sel in toggle_selectors:
    try:
      btn = page.locator(sel).first
      if await btn.count():
        await btn.click()
        await human_pause(page, 400)
        break
    except Exception:
      continue

  candidates = [
    "input[placeholder*='Recherchez']",
    "input[placeholder*='recherchez']",
    "input[name='search']",
    "input[data-testid='search-input']",
    "input[type='search']",
  ]
  search_input = None
  for sel in candidates:
    node = page.locator(sel).first
    if await node.count():
      search_input = node
      break
  if search_input is None:
    raise RuntimeError("Champ de recherche introuvable")
  await search_input.click()
  await human_pause(page, 500)
  await search_input.fill("")
  await human_pause(page, 300)
  for ch in text:
    await page.keyboard.type(ch, delay=120)
  await human_pause(page, 400)
  await page.keyboard.press("Enter")
  await human_pause(page, 2000)


async def open_product(page, ean: str) -> None:
  selectors = [
    f"a[href*='{ean}']",
    "a:has-text(\"Orangina\")",
  ]
  for sel in selectors:
    loc = page.locator(sel).first
    try:
      if await loc.count():
        await loc.click()
        await human_pause(page, 2500)
        return
    except Exception:
      continue
  raise RuntimeError("Impossible d'ouvrir la fiche produit")


async def reveal_price(page) -> None:
  selectors = [
    "button:has-text(\"Afficher le prix\")",
    "button:has-text(\"Voir le prix\")",
    "button.price-unavailable__button",
    "button[data-testid='product-price-reveal']",
  ]
  for sel in selectors:
    btn = page.locator(sel).first
    try:
      if await btn.count():
        await btn.click()
        await human_pause(page, 2000)
        return
    except Exception:
      continue


async def wait_price_visible(page) -> None:
  price_selectors = [
    "[data-testid='product-price']",
    ".product-price",
    "span:has-text('€')",
  ]
  for _ in range(10):
    for sel in price_selectors:
      try:
        node = page.locator(sel).first
        if await node.count():
          text = await node.text_content()
          if text and "€" in text:
            return
      except Exception:
        continue
    await human_pause(page, 1000)
  raise RuntimeError("Prix non visible après 10 secondes")


async def capture_trace(args) -> None:
  out_path = Path(args.out)
  out_path.parent.mkdir(parents=True, exist_ok=True)

  events = []
  start = time.time()

  async def record(payload):
    events.append({
      "kind": payload.get("kind", "raw"),
      "ts": time.time() - start,
      "data": payload,
    })

  async with async_playwright() as p:
    browser = await p.chromium.connect_over_cdp(args.cdp_url)
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = context.pages[0] if context.pages else await context.new_page()

    try:
      await page.bring_to_front()
    except Exception:
      pass

    await page.expose_function("recordEvent", lambda payload: asyncio.create_task(record(payload)))
    await page.add_init_script(JS_INSTRUMENTATION)

    await page.goto(args.store_url, wait_until="domcontentloaded")
    events.append({"kind": "navigation", "ts": 0.0, "data": {"url": page.url}})

    await human_pause(page, 1500)
    await ensure_cookie_accept(page)
    await ensure_drive_selected(page)
    await human_pause(page, 800)
    await type_search(page, args.ean)
    await human_pause(page, 1200)
    await open_product(page, args.ean)
    await human_pause(page, 1500)
    await reveal_price(page)
    await wait_price_visible(page)
    await human_pause(page, 1500)

  events.append({"kind": "stop", "ts": time.time() - start, "data": {}})
  out_path.write_text("\n".join(json.dumps(evt, ensure_ascii=False) for evt in events), encoding="utf-8")


def main() -> None:
  args = parse_args()
  asyncio.run(capture_trace(args))


if __name__ == "__main__":
  main()
