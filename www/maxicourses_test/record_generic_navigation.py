#!/usr/bin/env python3

"""Generic recorder for human navigation using Chrome CDP."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

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


def parse_args():
    parser = argparse.ArgumentParser(description="Record human navigation (Chrome CDP)")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument("--url", default="https://www.carrefour.fr/courses")
    parser.add_argument("--out", default="../traces/carrefour-trace.jsonl")
    parser.add_argument("--context-index", type=int, default=0)
    return parser.parse_args()


def main():
    args = parse_args()
    trace_path = Path(args.out)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    events = []
    start = time.time()

    async def record_session():
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(args.cdp_url)
            contexts = browser.contexts
            if contexts:
                context = contexts[min(max(args.context_index, 0), len(contexts) - 1)]
            else:
                context = await browser.new_context()
            page = await context.new_page()

            async def record(payload):
                events.append({
                    "kind": payload.get("kind", "raw"),
                    "ts": time.time() - start,
                    "data": payload,
                })

            await page.expose_function("recordEvent", lambda payload: asyncio.create_task(record(payload)))
            await page.add_init_script(JS_INSTRUMENTATION)
            await page.goto(args.url, wait_until="domcontentloaded")
            events.append({"kind": "navigation", "ts": 0.0, "data": {"url": page.url}})

            print("Enregistrement lancé. Navigue dans Chrome 9222.")
            print("Quand le prix est visible, appuie sur Entrée ici.")
            sys.stdin.readline()

    asyncio.run(record_session())
    events.append({"kind": "stop", "ts": time.time() - start, "data": {}})
    trace_path.write_text("\n".join(json.dumps(evt, ensure_ascii=False) for evt in events), encoding="utf-8")
    print(f"Trace sauvegardée dans {trace_path}")


if __name__ == "__main__":
    main()
