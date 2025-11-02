#!/usr/bin/env python3
"""Fetcher Intermarché respectant le mandat de collecte."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import typing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, unquote

from rich import print
import sys as _sys
import os as _os

_sys.path.append(_os.path.dirname(__file__))
from scraper.engine import make_context, state_path_for

from collection_mandate import get_method
from seed_catalog import all_seeds  # noqa: E402
from telemetry import (
    StageLiteral,
    log_candidate_scored,
    log_event as log_telemetry_event,
    log_hit_accepted,
    log_hit_rejected,
    log_search_attempt,
)
from query_builder import CATEGORY_STOPWORDS, SKU_PATTERN
from typing import cast

EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
PROXY = os.environ.get("PROXY")
HOME_URL = os.environ.get("HOME_URL", "https://www.intermarche.com/")
MANDATE = get_method("intermarche")
DEBUG_INTERMARCHE = os.environ.get("DEBUG_INTERMARCHE") == "1"
DEBUG_DUMP_ROOT = os.environ.get("HUMAN_DEBUG_DIR") or os.environ.get(
    "INTERMARCHE_DEBUG_DIR"
)

# Avoid hammering the same fallback terms twice in a row
DEFAULT_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.120 Safari/537.36"
TELEMETRY_STORE = "intermarche"

DEFAULT_HEADERS = {
    "sec-ch-ua": '"Chromium";v="127", "Not(A:Brand";v="24", "Google Chrome";v="127"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "upgrade-insecure-requests": "1",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.5",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
}

EARLY_EAN_URL_PATTERN = re.compile(r"/produit/[^?#]*?(?:-|/)(\d{13})(?:[^0-9]|$)")
FORBIDDEN_LABEL_TOKENS = {"boisson gazeuse"}
SKU_LABEL_PATTERN = re.compile(r"\bp\d{5,}\b", flags=re.IGNORECASE)
CORE_STOPWORDS = {"aux", "au", "de", "du", "des", "la", "le", "les", "et", "en"}
INTERMARCHE_MAX_PDP = 3
INTERMARCHE_MAX_RESULTS = 5

MANUAL_DESCRIPTOR = all_seeds()


def _looks_like_ean(term: typing.Optional[str]) -> bool:
    if not term:
        return False
    stripped = "".join(ch for ch in term.strip() if ch.isdigit())
    if not stripped:
        return False
    return stripped == term.strip().replace(" ", "") and 8 <= len(stripped) <= 14


def extract_ean_from_url(url: typing.Optional[str]) -> typing.Optional[str]:
    """Intermarché PDP URLs embed the 13-digit EAN; extract it when present."""
    if not url:
        return None
    match = re.search(r"(\d{13})(?=[^0-9]|$)", url)
    if match:
        return match.group(1)
    return None


def extract_ean_from_candidate_href(url: typing.Optional[str]) -> typing.Optional[str]:
    """Use the stricter /produit/ slug-based regex recommended by the mandate."""
    if not url:
        return None
    match = EARLY_EAN_URL_PATTERN.search(url)
    return match.group(1) if match else None


def _canonical_token_filter(label: str) -> bool:
    """Return True if the label contains tokens that must be rejected."""
    haystack = label.lower()
    if any(token in haystack for token in FORBIDDEN_LABEL_TOKENS):
        return True
    if SKU_LABEL_PATTERN.search(haystack):
        return True
    for token in haystack.split():
        if SKU_PATTERN.match(token):
            return True
    return False


def _emit_candidate_telemetry(
    *,
    query: typing.Optional[str],
    stage: typing.Optional[StageLiteral],
    candidate_url: typing.Optional[str],
    title: typing.Optional[str],
    match_status: str,
    reason: typing.Optional[str],
    search_url: typing.Optional[str],
    ean: typing.Optional[str],
) -> None:
    log_candidate_scored(
        store=TELEMETRY_STORE,
        ean=ean,
        query=query,
        stage=stage,
        url=candidate_url,
        title=title,
        match_status=match_status,
        reason=reason,
        search_url=search_url,
    )
    if match_status == "EXACT":
        log_hit_accepted(
            store=TELEMETRY_STORE,
            ean=ean,
            query=query,
            stage=stage,
            url=candidate_url,
            title=title,
            match_status=match_status,
            reason=reason,
        )
    else:
        log_hit_rejected(
            store=TELEMETRY_STORE,
            ean=ean,
            query=query,
            stage=stage,
            url=candidate_url,
            title=title,
            match_status=match_status,
            reason=reason,
        )


def load_storage_state(path: typing.Optional[Path]) -> typing.Optional[dict]:
    if not path:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:
        return None


async def apply_storage_state(context, page, state: typing.Optional[dict]) -> None:
    if not state:
        return
    cookies = state.get("cookies") if isinstance(state, dict) else None
    if cookies:
        try:
            await context.add_cookies(cookies)
        except Exception:
            pass


def _debug_path(name: str) -> typing.Optional[Path]:
    if not DEBUG_DUMP_ROOT:
        return None
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    path = Path(DEBUG_DUMP_ROOT).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{safe}.html"


async def debug_dump(page, name: str) -> None:
    if not DEBUG_DUMP_ROOT:
        return
    try:
        html = await page.content()
    except Exception:
        return
    target = _debug_path(name)
    if not target:
        return
    try:
        target.write_text(html, encoding="utf-8")
        if DEBUG_INTERMARCHE:
            sys.stderr.write(f"[intermarche] debug dump -> {target}\n")
    except Exception:
        pass


async def debug_shot(page, name: str) -> None:
    if not DEBUG_DUMP_ROOT:
        return
    target = _debug_path(name)
    if not target:
        return
    png_path = target.with_suffix(".png")
    try:
        await page.screenshot(path=str(png_path))
        if DEBUG_INTERMARCHE:
            sys.stderr.write(f"[intermarche] debug screenshot -> {png_path}\n")
    except Exception:
        pass


def debug_json(name: str, payload: typing.Any) -> None:
    if not DEBUG_DUMP_ROOT or payload is None:
        return
    target = _debug_path(name)
    if not target:
        return
    json_path = target.with_suffix(".json")
    try:
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if DEBUG_INTERMARCHE:
            sys.stderr.write(f"[intermarche] debug json -> {json_path}\n")
    except Exception:
        pass


async def handle_404(page) -> bool:
    """Detect Intermarché 404 page and click the return button if present."""
    try:
        banner = page.locator("text='Vous êtes perdus dans nos rayons'").first
        if await banner.count():
            if DEBUG_INTERMARCHE:
                sys.stderr.write("[intermarche] 404 detected, returning to home\n")
            await debug_dump(page, "404-page")
            try:
                await page.get_by_role(
                    "button", name=lambda name: name and "Revenir" in name
                ).click()
            except Exception:
                await page.locator(
                    "button", has_text="Revenir à l'accueil"
                ).first.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(5000)
            return True
    except Exception:
        pass
    return False


def decode_store_label(raw: str) -> str:
    if not raw:
        return ""
    return unquote(unquote(raw)).strip()


async def get_store_metadata(context) -> typing.Optional[dict]:
    try:
        cookies = await context.cookies()
    except Exception:
        return None
    for cookie in cookies:
        if cookie.get("name") == "itm_pdv":
            try:
                data = json.loads(unquote(cookie.get("value", "")))
            except Exception:
                return None
            data["decoded_name"] = decode_store_label(data.get("name", ""))
            data["decoded_city"] = decode_store_label(data.get("city", ""))
            return data
    return None


def _descriptor_seed(ean: str) -> typing.Optional[str]:
    """Compose the human search phrase stored in the manual descriptors table."""
    if not ean:
        return None
    entry = MANUAL_DESCRIPTOR.get(ean)
    if not isinstance(entry, dict):
        return None
    seed_query = entry.get("seed_query")
    if isinstance(seed_query, str):
        candidate = seed_query.strip()
        if candidate and not _looks_like_ean(candidate):
            return candidate
    pieces = []
    for key in ("brand", "name", "quantity"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            pieces.append(value.strip())
    if pieces:
        candidate = " ".join(pieces)
        if candidate and not _looks_like_ean(candidate):
            return candidate
    description = entry.get("description")
    if isinstance(description, str):
        candidate = description.strip()
        if candidate and not _looks_like_ean(candidate):
            return candidate
    return None


def _normalized_quantity_to_liters(
    quantity: typing.Optional[str],
) -> typing.Optional[float]:
    if not isinstance(quantity, str):
        return None
    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*(l|litre|litres|ml|millilitre|millilitres)",
        quantity.lower(),
    )
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit.startswith("ml") or "milli" in unit:
        return value / 1000.0
    return value


def _normalize_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def _forbidden_query_tokens(query: str) -> list[str]:
    tokens = _normalize_query(query).split()
    forbidden: list[str] = []
    for token in tokens:
        if SKU_PATTERN.match(token):
            forbidden.append(token)
        elif token in CATEGORY_STOPWORDS:
            forbidden.append(token)
    return forbidden


def _normalize_text(value: typing.Optional[str]) -> typing.Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().lower().split())
    return normalized or None


def _format_size_token(
    size_value: typing.Optional[typing.Union[int, float]],
    size_unit: typing.Optional[str],
) -> typing.Optional[str]:
    if size_value is None or size_unit is None:
        return None
    try:
        value = float(size_value)
    except (TypeError, ValueError):
        return None
    unit = size_unit.strip().lower()
    if unit in {"l", "litre", "litres"}:
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        text = text.replace(".", ",")
        return f"{text}l"
    if unit in {"ml", "millilitre", "millilitres"}:
        return f"{int(round(value))}ml"
    if unit in {"cl"}:
        return f"{int(round(value))}cl"
    return None


def _extract_quantity_token(quantity: typing.Optional[str]) -> typing.Optional[str]:
    if not isinstance(quantity, str):
        return None
    normalized = quantity.lower().replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(l|cl|ml)", normalized)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    return _format_size_token(value, unit)


def _valid_brand(value: typing.Optional[str]) -> typing.Optional[str]:
    candidate = _normalize_text(value)
    if candidate and not re.search(r"\d", candidate):
        return candidate
    return None


def _extract_core_tokens(
    text: typing.Optional[str], brand_tokens: set[str]
) -> list[str]:
    if not isinstance(text, str):
        return []
    tokens: list[str] = []
    for token in re.findall(r"[0-9a-zà-öø-ÿ]+", text.lower()):
        if (
            token in brand_tokens
            or token in CORE_STOPWORDS
            or token in CATEGORY_STOPWORDS
        ):
            continue
        if token.isdigit():
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _canonical_core_phrase(
    descriptor: typing.Optional[dict],
    canonical: typing.Optional[dict],
    brand_tokens: set[str],
) -> typing.Optional[str]:
    variants: list[typing.Optional[str]] = []
    if isinstance(canonical, dict):
        variants.append(canonical.get("variant"))
    if isinstance(descriptor, dict):
        variants.append(descriptor.get("variant"))
    for text in variants:
        tokens = _extract_core_tokens(text, brand_tokens)
        if tokens:
            return " ".join(tokens[:3])
    candidates = []
    if isinstance(canonical, dict):
        candidates.append(canonical.get("name_core"))
    if isinstance(descriptor, dict):
        candidates.extend(
            [
                descriptor.get("seed_primary_name"),
                descriptor.get("name"),
                descriptor.get("description"),
            ]
        )
    for text in candidates:
        tokens = _extract_core_tokens(text, brand_tokens)
        if tokens:
            return " ".join(tokens[:3])
    return None


def _canonical_size_token(
    descriptor: typing.Optional[dict], canonical: typing.Optional[dict]
) -> typing.Optional[str]:
    if isinstance(canonical, dict):
        token = _format_size_token(
            canonical.get("size_value"), canonical.get("size_unit")
        )
        if token:
            return token
    if isinstance(descriptor, dict):
        for key in ("quantity", "seed_primary_quantity"):
            token = _extract_quantity_token(descriptor.get(key))
            if token:
                return token
    return None


def _canonical_context(
    ean: str, descriptor: typing.Optional[dict]
) -> typing.Optional[dict]:
    canonical = descriptor.get("canonical") if isinstance(descriptor, dict) else None
    brand = _valid_brand(
        descriptor.get("brand") if isinstance(descriptor, dict) else None
    )
    if not brand and isinstance(canonical, dict):
        brand = _valid_brand(canonical.get("brand"))
    if not brand:
        return None
    brand_hyphen = brand.replace(" ", "-")
    brand_space = brand.replace("-", " ")
    brand_tokens = set(brand_hyphen.split()) | set(brand_space.split())

    core_phrase = _canonical_core_phrase(descriptor, canonical, brand_tokens)
    size_token = _canonical_size_token(descriptor, canonical)

    return {
        "brand_hyphen": brand_hyphen,
        "brand_space": brand_space,
        "core_phrase": core_phrase,
        "size_token": size_token,
    }


def _build_inter_queries(ean: str, descriptor: typing.Optional[dict]) -> list[str]:
    context = _canonical_context(ean, descriptor)
    if not context:
        return []
    brand_hyphen = context["brand_hyphen"]
    brand_space = context["brand_space"]
    core_phrase = context["core_phrase"]
    size_token = context["size_token"]

    queries: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        normalized = _normalize_query(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            queries.append(normalized)

    if size_token:
        add(f"{brand_hyphen} {size_token}")
        if brand_space != brand_hyphen:
            add(f"{brand_space} {size_token}")
        if core_phrase:
            add(f"{brand_hyphen} {core_phrase} {size_token}")
    else:
        if core_phrase:
            add(f"{brand_hyphen} {core_phrase}")
            if brand_space != brand_hyphen:
                add(f"{brand_space} {core_phrase}")
        add(brand_hyphen)
        if brand_space != brand_hyphen:
            add(brand_space)

    return queries[:3]


def _descriptor_queries(descriptor: typing.Optional[dict]) -> list[str]:
    if not isinstance(descriptor, dict):
        return []
    queries_map = descriptor.get("queries")
    if not isinstance(queries_map, dict):
        return []
    raw_queries = queries_map.get("intermarche")
    if not isinstance(raw_queries, list):
        return []
    queries: list[str] = []
    seen: set[str] = set()
    for raw in raw_queries:
        if not isinstance(raw, str):
            continue
        normalized = _normalize_query(raw)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        queries.append(normalized)
        if len(queries) >= 3:
            break
    return queries


def build_query_plan() -> list[tuple[StageLiteral, str]]:
    if not EAN:
        return []
    descriptor = MANUAL_DESCRIPTOR.get(EAN)
    queries = _descriptor_queries(descriptor)
    if not queries:
        queries = _build_inter_queries(EAN, descriptor)
    plan: list[tuple[StageLiteral, str]] = []
    for idx, query in enumerate(queries):
        stage = cast(StageLiteral, f"Q{idx + 1}")
        plan.append((stage, query))
    return plan


def _get_negatives(descriptor: typing.Optional[dict]) -> list[str]:
    if not isinstance(descriptor, dict):
        return []
    neg_map = descriptor.get("negatives")
    if isinstance(neg_map, dict):
        values = neg_map.get("intermarche") or []
        if isinstance(values, list):
            return [
                token.lower().strip()
                for token in values
                if isinstance(token, str) and token.strip()
            ]
    return []


@dataclass
class Result:
    status: str
    price: typing.Optional[str] = None
    title: typing.Optional[str] = None
    url: typing.Optional[str] = None
    note: typing.Optional[str] = None
    matched_ean: typing.Optional[str] = None
    unit_price: typing.Optional[str] = None
    quantity: typing.Optional[str] = None
    store: typing.Optional[str] = None


COOKIE_SELECTORS = [
    "button:has-text('Tout accepter')",
    "button:has-text('Accepter')",
    'button:has-text("J\'accepte")',
    "#onetrust-accept-btn-handler",
    "#didomi-notice-agree-button",
]


async def click_first(page, selectors: typing.Sequence[str]) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1500):
                await loc.click()
                return True
        except Exception:
            continue
    return False


async def perform_site_search(page, term: str) -> bool:
    """Try to perform a search via the site search box instead of direct navigation."""
    search_selectors = [
        "input[type='search']",
        "input[name='search']",
        "input[placeholder*='Rechercher']",
        "input[aria-label*='Rechercher']",
    ]
    for sel in search_selectors:
        try:
            field = page.locator(sel).first
            if await field.is_visible(timeout=2000):
                await field.fill(term)
                await field.press("Enter")
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(5000)
                return True
        except Exception:
            continue
    return False


async def accept_cookies(page) -> None:
    for sel in COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                return
        except Exception:
            pass
    try:
        await page.evaluate(
            """
            (() => {
              const labels = ['tout accepter', 'accepter', "j'accepte", 'ok'];
              const buttons = [...document.querySelectorAll('button')];
              for (const b of buttons) {
                const txt = (b.innerText || '').trim().toLowerCase();
                if (labels.some(l => txt.includes(l))) {
                  b.click();
                  return;
                }
              }
            })();
            """
        )
    except Exception:
        pass


async def ensure_store_selected(page) -> None:
    try:
        # Depending on the flow Intermarché may show a store selection modal
        if await page.locator("[data-testid='store-modal']").is_visible(timeout=2000):
            await click_first(
                page,
                [
                    "[data-testid='store-modal'] button:has-text('Valider')",
                    "[data-testid='store-modal'] button:has-text('Sélectionner')",
                    "[data-testid='store-modal'] button:has-text('Choisir ce magasin')",
                ],
            )
            await page.wait_for_load_state("domcontentloaded")
            return
    except Exception:
        pass
    try:
        await click_first(
            page,
            [
                "button:has-text('Choisir mon magasin')",
                "button:has-text('Mon magasin')",
                "button:has-text('Choisir ce magasin')",
                "button:has-text('Sélectionner ce magasin')",
            ],
        )
    except Exception:
        pass


async def ensure_home(page) -> bool:
    """If a 404 / lost page is shown, click the button to return home."""
    try:
        lost = page.locator("text=Vous êtes perdus dans nos rayons")
        if await lost.count():
            btn = page.locator('button:has-text("Revenir à l\'accueil")')
            if await btn.count():
                await btn.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(5000)
                return True
    except Exception:
        pass
    return False


async def perform_search(page, term: str) -> bool:
    """Submit a search query via the header search box."""
    try:
        encoded = quote_plus(term)
        search_url = f"https://www.intermarche.com/recherche/{encoded}"
        await page.goto(search_url, wait_until="networkidle")
        try:
            await page.wait_for_selector("a[href*='/produit/']", timeout=10000)
        except Exception:
            await page.wait_for_timeout(5000)
        return True
    except Exception:
        return False


async def collect_product_links(page) -> list[dict]:
    """Extract product anchors from the current search results page."""
    results = []
    try:
        anchors = page.locator("a[href*='/produit/']")
        count = await anchors.count()
    except Exception:
        count = 0
    for idx in range(min(count, INTERMARCHE_MAX_RESULTS)):
        try:
            link = anchors.nth(idx)
            href = await link.get_attribute("href")
            if not href:
                continue
            text = await link.inner_text(timeout=2000)
            results.append({"href": href, "text": text})
        except Exception:
            continue
    return results


async def run() -> Result:
    storage_state_path = state_path_for("intermarche")
    p, browser, context, page = await make_context(
        headless=HEADLESS,
        proxy=PROXY,
        storage_state_path=(
            storage_state_path if os.environ.get("USE_CDP") != "1" else None
        ),
        user_agent=DEFAULT_UA,
    )

    async def _adopt_new_page(new_page):
        nonlocal page
        try:
            await new_page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
        old_page = page
        page = new_page
        try:
            await new_page.bring_to_front()
        except Exception:
            pass
        if old_page and old_page != new_page:
            try:
                await old_page.close()
            except Exception:
                pass

    context.on("page", lambda new_page: asyncio.create_task(_adopt_new_page(new_page)))

    state_data = load_storage_state(
        Path(storage_state_path) if storage_state_path else None
    )
    if state_data:
        await apply_storage_state(context, page, state_data)

    use_cdp = os.environ.get("USE_CDP") == "1"
    if use_cdp:
        preferred_page = None
        for existing in context.pages:
            try:
                url = existing.url
            except Exception:
                url = ""
            if url and "intermarche.com" in url and not url.startswith("about:"):
                preferred_page = existing
                break
        if not preferred_page and context.pages:
            preferred_page = context.pages[0]
        if preferred_page:
            if page != preferred_page:
                try:
                    await page.close()
                except Exception:
                    pass
            page = preferred_page
        try:
            await page.bring_to_front()
        except Exception:
            pass

    try:
        await context.set_extra_http_headers(DEFAULT_HEADERS)
    except Exception:
        pass

    home_url = HOME_URL or "https://www.intermarche.com/"
    if not page.url or "intermarche.com" not in page.url:
        try:
            await page.goto("about:blank")
            await page.wait_for_timeout(5000)
        except Exception:
            pass
        try:
            await page.goto(home_url, wait_until="domcontentloaded")
        except Exception:
            pass
    else:
        try:
            await page.reload(wait_until="domcontentloaded")
        except Exception:
            pass
    try:
        await page.wait_for_timeout(5000)
        await page.mouse.move(200, 200, steps=15)
        await page.wait_for_timeout(5000)
    except Exception:
        pass
    if DEBUG_INTERMARCHE:
        sys.stderr.write(f"[intermarche] landed on {page.url}\n")
    if await ensure_home(page):
        await ensure_home(page)  # second chance if redirected twice
    await accept_cookies(page)
    await ensure_store_selected(page)

    store_metadata = await get_store_metadata(context)
    store_label = None
    if isinstance(store_metadata, dict):
        store_label = (
            store_metadata.get("decoded_name") or store_metadata.get("name") or None
        )
    if DEBUG_INTERMARCHE:
        sys.stderr.write(f"[intermarche] store metadata label={store_label}\n")

    descriptor_entry = MANUAL_DESCRIPTOR.get(EAN) if EAN else None
    negatives_tokens = _get_negatives(descriptor_entry)

    try:
        query_plan = build_query_plan()
    except ValueError as exc:
        sys.stderr.write(f"[intermarche] query plan error: {exc}\n")
        await browser.close()
        await p.stop()
        return Result(status="ERROR", note="invalid_query_tokens")

    if not query_plan:
        await browser.close()
        await p.stop()
        return Result(status="NO_QUERY")

    price = None
    title = None
    pdp = None
    final_pdp: typing.Optional[str] = None
    final_matched_ean: typing.Optional[str] = None
    unit_price = None
    quantity_text = (
        descriptor_entry.get("quantity") if isinstance(descriptor_entry, dict) else None
    )
    final_matched_reason: typing.Optional[str] = None
    accepted_stage: typing.Optional[StageLiteral] = None
    accepted_query: typing.Optional[str] = None
    accepted_search_url: typing.Optional[str] = None

    for stage_label, term in query_plan:
        stage_matched_ean: typing.Optional[str] = None
        stage_matched_reason: typing.Optional[str] = None
        normalized_term = _normalize_query(term)
        forbidden_tokens = _forbidden_query_tokens(term)
        if forbidden_tokens:
            log_telemetry_event(
                {
                    "store": TELEMETRY_STORE,
                    "ean": EAN,
                    "query": normalized_term,
                    "stage": stage_label,
                    "status": "search_attempt",
                    "hit": False,
                    "seed_based": True,
                    "used_memory": False,
                    "allowed_tokens": False,
                    "filtered_tokens": forbidden_tokens,
                    "results_count": 0,
                    "search_url": None,
                }
            )
            continue

        await page.goto(home_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        await accept_cookies(page)
        await ensure_store_selected(page)
        await accept_cookies(page)
        performed = await perform_search(page, term)
        if not performed:
            if DEBUG_INTERMARCHE:
                sys.stderr.write(
                    f"[intermarche] search field not available for term '{term}'\n"
                )
            continue
        await debug_dump(page, f"search-{term}")
        await debug_shot(page, f"search-{term}")
        await page.wait_for_timeout(5000)
        if await handle_404(page):
            if DEBUG_INTERMARCHE:
                sys.stderr.write(
                    f"[intermarche] 404 after search '{term}', retrying next term\n"
                )
            continue
        candidates_info = await collect_product_links(page)
        pdp = None
        candidates: list[str] = []
        candidate_labels: dict[str, str] = {}
        seen_candidate_urls: set[str] = set()
        for info in candidates_info:
            href = info.get("href")
            if not href:
                continue
            label = (info.get("text") or "").strip()
            normalized_label = label.lower()
            if negatives_tokens and any(
                token in normalized_label for token in negatives_tokens
            ):
                continue
            if _canonical_token_filter(normalized_label):
                continue
            if href.startswith("/"):
                href = f"https://www.intermarche.com{href}"
            if href in seen_candidate_urls:
                continue
            seen_candidate_urls.add(href)
            candidates.append(href)
            candidate_labels[href] = label
        if DEBUG_INTERMARCHE:
            sys.stderr.write(
                f"[intermarche] candidates for term '{term}': {candidates}\n"
            )

        search_url = page.url
        log_search_attempt(
            store=TELEMETRY_STORE,
            ean=EAN,
            query=normalized_term,
            stage=stage_label,
            results_count=len(candidates),
            search_url=search_url,
        )

        matched_href = None
        fallback_href = None
        pdp_visits = 0
        for idx, href in enumerate(candidates):
            if pdp_visits >= INTERMARCHE_MAX_PDP:
                break
            label = candidate_labels.get(href, "")
            candidate_reason = None
            url_ean_candidate = extract_ean_from_candidate_href(href)
            if url_ean_candidate and EAN and url_ean_candidate != EAN:
                _emit_candidate_telemetry(
                    query=normalized_term,
                    stage=stage_label,
                    candidate_url=href,
                    title=label or None,
                    match_status="REJECTED",
                    reason="ean_mismatch",
                    search_url=search_url,
                    ean=EAN,
                )
                continue
            if url_ean_candidate and EAN and url_ean_candidate == EAN:
                candidate_reason = "ean_in_url"
            try:
                await page.goto(href, wait_until="domcontentloaded")
                await page.wait_for_timeout(5000)
                pdp_visits += 1
                try:
                    await page.wait_for_selector(
                        "[data-testid='product-price'], .product-price", timeout=6000
                    )
                except Exception:
                    pass
                if await handle_404(page):
                    await ensure_home(page)
                    _emit_candidate_telemetry(
                        query=normalized_term,
                        stage=stage_label,
                        candidate_url=href,
                        title=label or None,
                        match_status="REJECTED",
                        reason="pdp_404",
                        search_url=search_url,
                        ean=EAN,
                    )
                    continue
                if DEBUG_INTERMARCHE:
                    sys.stderr.write(f"[intermarche] inspecting {page.url}\n")
                await debug_dump(page, f"pdp-{idx}")
                await debug_shot(page, f"pdp-{idx}")
                current_url = page.url or href
                if not fallback_href:
                    fallback_href = current_url
                url_ean = extract_ean_from_candidate_href(
                    current_url
                ) or extract_ean_from_url(current_url)
                if url_ean:
                    if EAN:
                        if url_ean == EAN:
                            matched_href = current_url
                            stage_matched_ean = url_ean
                            stage_matched_reason = candidate_reason or "ean_in_url"
                            if DEBUG_INTERMARCHE:
                                sys.stderr.write(
                                    f"[intermarche] url match -> {stage_matched_ean} reason={stage_matched_reason}\n"
                                )
                            break
                        _emit_candidate_telemetry(
                            query=normalized_term,
                            stage=stage_label,
                            candidate_url=current_url,
                            title=label or None,
                            match_status="REJECTED",
                            reason="ean_mismatch",
                            search_url=search_url,
                            ean=EAN,
                        )
                        continue
                    matched_href = current_url
                    stage_matched_ean = url_ean
                    break
            except Exception:
                _emit_candidate_telemetry(
                    query=normalized_term,
                    stage=stage_label,
                    candidate_url=href,
                    title=label or None,
                    match_status="REJECTED",
                    reason="exception",
                    search_url=search_url,
                    ean=EAN,
                )
                continue
        pdp = matched_href or fallback_href
        if not pdp:
            continue
        if EAN:
            pdp_ean = extract_ean_from_url(pdp)
            if pdp_ean != EAN:
                # en dernier recours s'assurer qu'on ne conserve pas une mauvaise page
                continue
            stage_matched_ean = EAN
            if stage_matched_reason is None:
                stage_matched_reason = "ean_in_url"
        elif stage_matched_ean is None:
            stage_matched_ean = extract_ean_from_url(pdp)
        # ensure we are on the product page corresponding to pdp
        if page.url != pdp:
            try:
                await page.goto(pdp, wait_until="domcontentloaded")
                await page.wait_for_timeout(5000)
                try:
                    await page.wait_for_selector(
                        "[data-testid='product-price'], .product-price", timeout=6000
                    )
                except Exception:
                    pass
            except Exception:
                pass
        await accept_cookies(page)
        await ensure_store_selected(page)
        await accept_cookies(page)
        await ensure_store_selected(page)

        page_html = await page.content()
        has_identifier_match = bool(
            stage_matched_ean and (stage_matched_ean == EAN if EAN else True)
        )
        if not price:
            try:
                ld_scripts = await page.locator(
                    "script[type='application/ld+json']"
                ).all_text_contents()
            except Exception:
                ld_scripts = []
            for raw in ld_scripts:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("@type") != "Product":
                        continue
                    price_info = item.get("price")
                    if isinstance(price_info, dict):
                        value = price_info.get("value")
                        if value is not None and price is None:
                            try:
                                price = f"{float(value):.2f}".replace(".", ",")
                            except Exception:
                                price = str(value)
                    if not title:
                        maybe_title = item.get("name")
                        if isinstance(maybe_title, str) and maybe_title.strip():
                            title = maybe_title.strip()
        if not unit_price and page_html:
            match = re.search(r"(\d+[\.,]\d{2})\s*€\s*/\s*([a-zA-ZéÉ/]+)", page_html)
            if match:
                amount = match.group(1).replace(".", ",")
                unit = match.group(2).strip().upper()
                unit_price = f"{amount} € / {unit}"
        if not quantity_text:
            try:
                qty_candidate = await page.locator(
                    "[data-testid='product-packaging'], .product__weight, .product__capacity, .product-details__weight"
                ).first.text_content(timeout=2000)
                if qty_candidate:
                    quantity_text = " ".join(qty_candidate.split())
            except Exception:
                pass
        if not has_identifier_match:
            # Try schema.org pour récupérer l'identifiant GTIN
            try:
                for i in range(
                    await page.locator("script[type='application/ld+json']").count()
                ):
                    raw = (
                        await page.locator("script[type='application/ld+json']")
                        .nth(i)
                        .text_content()
                    )
                    data = json.loads(raw)
                    items = data if isinstance(data, list) else [data]
                    for it in items:
                        if isinstance(it, dict) and it.get("@type") in ("Product",):
                            gtin = (
                                it.get("gtin13") or it.get("gtin") or it.get("gtin14")
                            )
                            if gtin:
                                gtin_str = str(gtin).strip()
                                if gtin_str:
                                    if EAN and gtin_str == EAN:
                                        stage_matched_ean = gtin_str
                                        has_identifier_match = True
                                        if stage_matched_reason is None:
                                            stage_matched_reason = "ean_in_pdp"
                                    elif not EAN:
                                        stage_matched_ean = (
                                            stage_matched_ean or gtin_str
                                        )
                                        has_identifier_match = True
                            title = it.get("name") or title
                            offers = it.get("offers")
                            if isinstance(offers, dict):
                                price = price or offers.get("price")
                            elif isinstance(offers, list):
                                for of in offers:
                                    if isinstance(of, dict):
                                        price = price or of.get("price")
                            if EAN and gtin and str(gtin).strip() == EAN:
                                matched_href = pdp
            except Exception:
                pass

        if EAN:
            canonical = None
            try:
                canonical = await page.locator(
                    "link[rel='canonical']"
                ).first.get_attribute("href")
            except Exception:
                canonical = None
            has_ean = (
                (canonical and EAN in canonical)
                or (EAN in pdp if pdp else False)
                or False
            )
            if not has_ean and page_html:
                has_ean = EAN in page_html
            if has_ean:
                stage_matched_ean = EAN
                has_identifier_match = True
                if stage_matched_reason is None:
                    stage_matched_reason = "ean_in_pdp"

        if EAN and not has_identifier_match:
            _emit_candidate_telemetry(
                query=normalized_term,
                stage=stage_label,
                candidate_url=pdp,
                title=title,
                match_status="REJECTED",
                reason="ean_not_found",
                search_url=search_url,
                ean=EAN,
            )
            price = None
            title = None
            pdp = None
            continue

        # Try to read price from dedicated data attributes
        if not price:
            try:
                data_price_node = page.locator(
                    "[data-testid='product-price'], [data-test='product-price']"
                ).first
                price_text = await data_price_node.text_content(timeout=5000)
                if price_text:
                    price_text = price_text.strip().replace("\xa0", " ")
                    m = re.search(r"(\d+[\.,]\d{2})", price_text)
                    if m:
                        price = m.group(1).replace(",", ".")
            except Exception:
                pass

        # Fallback DOM
        if not price:
            try:
                txt = await page.locator(
                    "*[class*='price'], [data-testid*='price']"
                ).first.text_content(timeout=6000)
                if txt:
                    txt = txt.strip().replace("\xa0", " ")
                    m = re.search(r"(\d+[\.,]\d{2})\s*€", txt)
                    if m:
                        price = m.group(1).replace(",", ".")
            except Exception:
                pass

        if price:
            if EAN and stage_matched_ean and stage_matched_ean != EAN:
                _emit_candidate_telemetry(
                    query=normalized_term,
                    stage=stage_label,
                    candidate_url=pdp,
                    title=title,
                    match_status="REJECTED",
                    reason="ean_mismatch",
                    search_url=search_url,
                    ean=EAN,
                )
                price = None
                title = None
                stage_matched_ean = None
                pdp = None
                continue
            accepted_stage = stage_label
            accepted_query = normalized_term
            accepted_search_url = search_url
            final_matched_ean = stage_matched_ean
            final_matched_reason = stage_matched_reason
            final_pdp = pdp
            break
        if stage_matched_ean and stage_matched_reason:
            if DEBUG_INTERMARCHE:
                sys.stderr.write(
                    f"[intermarche] matched term '{term}' via {stage_matched_reason} -> {stage_matched_ean} (no price)\n"
                )
            accepted_stage = stage_label
            accepted_query = normalized_term
            accepted_search_url = search_url
            final_matched_ean = stage_matched_ean
            final_matched_reason = stage_matched_reason
            final_pdp = pdp
            break

    if not store_label:
        try:
            metadata = await get_store_metadata(context)
        except Exception:
            metadata = None
        if isinstance(metadata, dict):
            store_label = metadata.get("decoded_name") or metadata.get("name") or None

    await browser.close()
    await p.stop()
    if DEBUG_INTERMARCHE:
        sys.stderr.write(
            f"[intermarche] final state price={price} pdp={pdp} final_pdp={final_pdp} matched={final_matched_ean} reason={final_matched_reason}\n"
        )
    if price and pdp:
        try:
            price = f"{float(str(price).replace(',', '.')):.2f}"
        except Exception:
            price = str(price)
        price = price.replace(".", ",")
        if isinstance(descriptor_entry, dict):
            title = (
                title
                or descriptor_entry.get("name")
                or descriptor_entry.get("description")
            )
        final_quantity = quantity_text or (
            descriptor_entry.get("quantity")
            if isinstance(descriptor_entry, dict)
            else None
        )
        if not unit_price:
            liters = _normalized_quantity_to_liters(final_quantity)
            try:
                if liters and liters > 0:
                    unit_value = float(price.replace(",", ".")) / liters
                    unit_price = f"{unit_value:.2f}".replace(".", ",") + " € / L"
            except Exception:
                pass
        if unit_price:
            amount, sep, tail = unit_price.partition(" €")
            if amount:
                unit_price = amount.replace(".", ",") + sep + tail
        if EAN and final_matched_ean == EAN:
            _emit_candidate_telemetry(
                query=accepted_query or normalized_term,
                stage=accepted_stage or stage_label,
                candidate_url=pdp,
                title=title,
                match_status="EXACT",
                reason=final_matched_reason or "ean_in_pdp",
                search_url=accepted_search_url,
                ean=EAN,
            )
        note = None
        if store_label:
            note = f"Intermarché · {store_label}"
        else:
            note = "Intermarché (CDP)"
        return Result(
            status="OK",
            price=price,
            title=title,
            url=pdp,
            note=note,
            matched_ean=final_matched_ean,
            unit_price=unit_price,
            quantity=final_quantity,
            store=store_label,
        )
    if final_matched_ean and final_pdp:
        if DEBUG_INTERMARCHE:
            sys.stderr.write(
                f"[intermarche] returning NO_PRICE with EAN={final_matched_ean} url={final_pdp}\n"
            )
        log_candidate_scored(
            store=TELEMETRY_STORE,
            ean=EAN,
            query=accepted_query,
            stage=accepted_stage,
            url=final_pdp,
            title=title,
            match_status="EXACT",
            reason=final_matched_reason,
            search_url=accepted_search_url,
        )
        log_hit_rejected(
            store=TELEMETRY_STORE,
            ean=EAN,
            query=accepted_query,
            stage=accepted_stage,
            url=final_pdp,
            title=title,
            match_status="EXACT",
            reason="no_price",
        )
        return Result(
            status="NO_PRICE",
            title=title,
            url=final_pdp,
            note=None,
            matched_ean=final_matched_ean,
            unit_price=None,
            quantity=None,
            store=store_label,
        )
    if pdp:
        return Result(
            status="NO_PRICE",
            title=title,
            url=pdp,
            note=None,
            matched_ean=final_matched_ean,
            unit_price=None,
            quantity=None,
            store=store_label,
        )
    return Result(status="NO_RESULTS")


if __name__ == "__main__":
    res = asyncio.run(run())
    print(json.dumps(res.__dict__, ensure_ascii=False))
