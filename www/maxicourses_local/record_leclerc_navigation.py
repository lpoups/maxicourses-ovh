#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List

from playwright.async_api import async_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture des interactions humaines sur un site (Chrome CDP)."
    )
    parser.add_argument(
        "--cdp-url",
        default="http://localhost:9222",
        help="URL CDP de Chrome (par défaut: http://localhost:9222)",
    )
    parser.add_argument(
        "--url",
        default="https://www.leclercdrive.fr/",
        help="URL de départ à ouvrir dans l'onglet contrôlé.",
    )
    parser.add_argument(
        "--out",
        default="leclerc_navigation_trace.jsonl",
        help="Fichier de sortie (JSON Lines) pour stocker les événements.",
    )
    parser.add_argument(
        "--context-index",
        type=int,
        default=0,
        help="Index du contexte Playwright à réutiliser lorsqu'on se connecte au CDP (défaut: 0).",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Déclenche une navigation automatique de démonstration (Leclerc Bruges).",
    )
    parser.add_argument(
        "--stop-flag",
        type=Path,
        help="Chemin d'un fichier sentinelle : lorsqu'il apparaît, l'enregistrement s'arrête automatiquement.",
    )
    return parser.parse_args()


@dataclass
class Event:
    kind: str
    ts: float
    data: Dict[str, Any]

    def to_json(self) -> str:
        payload = {
            "kind": self.kind,
            "ts": self.ts,
            "data": self.data,
        }
        return json.dumps(payload, ensure_ascii=False)


class Recorder:
    def __init__(self, out_path: Path) -> None:
        self.out_path = out_path
        self.events: List[Event] = []
        self.start = time.time()

    def add_event(self, kind: str, data: Dict[str, Any]) -> None:
        rel_ts = time.time() - self.start
        self.events.append(Event(kind=kind, ts=rel_ts, data=data))

    def dump(self) -> None:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        with self.out_path.open("w", encoding="utf-8") as fh:
            for event in self.events:
                fh.write(event.to_json())
                fh.write("\n")


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

  const captureClick = (event) => {
    const target = event.target;
    relay({
      kind: 'click',
      epoch_ms: Date.now(),
      position: { x: event.clientX, y: event.clientY },
      path: buildPath(target),
      button: event.button,
      modifiers: {
        alt: event.altKey,
        ctrl: event.ctrlKey,
        meta: event.metaKey,
        shift: event.shiftKey,
      },
    });
  };

  const captureKey = (event) => {
    const target = event.target;
    relay({
      kind: 'key',
      epoch_ms: Date.now(),
      path: buildPath(target),
      key: event.key,
      code: event.code,
      type: event.type,
      value: (target && target.value !== undefined) ? target.value : undefined,
      modifiers: {
        alt: event.altKey,
        ctrl: event.ctrlKey,
        meta: event.metaKey,
        shift: event.shiftKey,
      },
    });
  };

  const captureInput = (event) => {
    const target = event.target;
    relay({
      kind: 'input',
      epoch_ms: Date.now(),
      path: buildPath(target),
      value: target && target.value,
      type: target && target.type,
    });
  };

  const captureScroll = (event) => {
    const target = event.target === document ? document.documentElement : event.target;
    relay({
      kind: 'scroll',
      epoch_ms: Date.now(),
      path: buildPath(target),
      scroll: {
        x: target && target.scrollLeft,
        y: target && target.scrollTop,
      },
    });
  };

  document.addEventListener('click', captureClick, true);
  document.addEventListener('keydown', captureKey, true);
  document.addEventListener('keyup', captureKey, true);
  document.addEventListener('input', captureInput, true);
  document.addEventListener('change', captureInput, true);
  document.addEventListener('scroll', captureScroll, true);
})();
"""


async def stdin_wait(prompt: str) -> None:
    loop = asyncio.get_running_loop()
    print(prompt, end="", flush=True)
    await loop.run_in_executor(None, sys.stdin.readline)


async def auto_demo(page) -> None:
    """Navigation programmatique imitant une visite humaine sur Leclerc Drive."""
    await page.wait_for_timeout(2500)

    # cookies
    cookie_selectors = [
        "button:has-text('Tout accepter')",
        "button:has-text('Accepter')",
        "button:has-text(\"J'accepte\")",
        "#onetrust-accept-btn-handler",
    ]
    for sel in cookie_selectors:
        btn = page.locator(sel).first
        try:
            if await btn.count():
                await btn.hover()
                await page.wait_for_timeout(400)
                await btn.click()
                await page.wait_for_timeout(900)
                break
        except Exception:
            continue

    # champ de recherche principal
    entry = page.locator("input[placeholder*='récupérer vos courses']").first
    try:
        if await entry.count():
            await entry.click()
            await page.wait_for_timeout(400)
            await entry.fill("")
            await page.wait_for_timeout(250)
            for ch in "Bruges":
                await entry.type(ch, delay=190)
            await page.wait_for_timeout(1500)
            option = page.locator("div[role='option']:has-text('Bruges (33520)')").first
            if await option.count():
                await option.hover()
                await page.wait_for_timeout(450)
                await option.click()
                await page.wait_for_timeout(1500)
    except Exception:
        pass

    # tentatives pour ouvrir le drive
    arrow_selectors = [
        "a[href*='magasin-173301-173301-Bruges']",
        "a:has-text('33520 Bruges')",
        "a[aria-label*='Bruges']",
    ]
    for sel in arrow_selectors:
        target = page.locator(sel).first
        try:
            if await target.count():
                await target.hover()
                await page.wait_for_timeout(500)
                await target.click()
                await page.wait_for_timeout(2200)
                break
        except Exception:
            continue

    # si page drive chargée, lancer une recherche produit
    search_selectors = [
        "input[name='Texte']",
        "input[id*='rechercheTexte']",
        "input[type='search']",
        "input[placeholder*='Recherchez']",
    ]
    term = "coca cola 1,75"
    for sel in search_selectors:
        field = page.locator(sel).first
        try:
            if await field.count() and await field.is_visible():
                await field.click()
                await page.wait_for_timeout(400)
                await field.fill("")
                await page.wait_for_timeout(200)
                for ch in term:
                    await field.type(ch, delay=170)
                await page.wait_for_timeout(600)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(2500)
                break
        except Exception:
            continue

    # ouvrir la première fiche produit si dispo
    try:
        result_link = page.locator("a[href*='fiche-produits']").first
        if await result_link.count():
            await result_link.hover()
            await page.wait_for_timeout(500)
            await result_link.click()
            await page.wait_for_timeout(2500)
    except Exception:
        pass

    await page.wait_for_timeout(1200)


async def run() -> None:
    args = parse_args()
    out_path = Path(args.out)
    recorder = Recorder(out_path)
    stop_flag = args.stop_flag
    if stop_flag:
        stop_flag = Path(stop_flag)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(args.cdp_url)
        contexts = browser.contexts
        if not contexts:
            context = await browser.new_context()
        else:
            index = min(max(args.context_index, 0), len(contexts) - 1)
            context = contexts[index]
        page = await context.new_page()

        await page.expose_binding(
            "recordEvent",
            lambda source, payload: recorder.add_event(payload.get("kind", "raw"), payload),
        )
        await page.add_init_script(JS_INSTRUMENTATION)

        async def frame_listener(frame):
            if frame == page.main_frame:
                title = None
                try:
                    title = await frame.page.title()
                except Exception:
                    title = None
                recorder.add_event(
                    "navigation",
                    {
                        "url": frame.url,
                        "title": title,
                    },
                )
        page.on("framenavigated", lambda frame: asyncio.create_task(frame_listener(frame)))

        await page.goto(args.url, wait_until="domcontentloaded")
        nav_title = None
        try:
            nav_title = await page.title()
        except Exception:
            nav_title = None
        recorder.add_event("navigation", {"url": page.url, "title": nav_title})

        print("Enregistrement lancé.")
        print(f" - Navigue dans l'onglet ouvert (URL initiale: {args.url})")
        if args.auto:
            print(" - Mode démo automatique activé (Leclerc Bruges).")
            await auto_demo(page)
        else:
            if stop_flag:
                if stop_flag.exists():
                    stop_flag.unlink()
                print(f" - Attente du fichier stop : {stop_flag} (crée-le quand tu veux terminer).\n")
                while True:
                    if stop_flag.exists():
                        break
                    await asyncio.sleep(0.5)
            else:
                print(" - Appuie sur Entrée dans ce terminal pour arrêter l'enregistrement.\n")
                await stdin_wait("[STOP] Appuie sur Entrée pour arrêter... ")
        if args.auto:
            await page.wait_for_timeout(500)

        recorder.add_event("stop", {"url": page.url})
        print("\nFin de l'enregistrement. Sauvegarde...")

    recorder.dump()
    print(f"Trace écrite dans {out_path}")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nInterruption utilisateur.")
