# finder.py
# Étape 1/3 — Scaffold solide et extensible, 100% code “dans le dur”.
from __future__ import annotations
import argparse
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from typing import Any, List, Dict, Iterable, Optional, Tuple, Protocol, Callable
import re
import os
import atexit
import json
from pathlib import Path
try:
    from ai_helpers import USE_AI_ASSIST, suggest_search_queries  # type: ignore
except Exception:  # pragma: no cover - AI optional
    USE_AI_ASSIST = False  # type: ignore
    suggest_search_queries = None  # type: ignore
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover - Playwright optional
    sync_playwright = None
    PlaywrightTimeoutError = Exception  # type: ignore
from .text_utils import is_pack_or_bundle
from descriptor_store import get_descriptor
HtmlProvider = Callable[[str], Optional[str]]
ImageCompareProvider = Callable[[Optional[str], Optional[str]], bool]
PLAYWRIGHT_SINGLETON: Dict[str, Optional[object]] = {
    "playwright": None,
    "browser": None,
    "context": None,
}
LECLERC_LISTING_IMAGES: Dict[str, str] = {}


def _normalize_leclerc_url_key(url: str) -> str:
    return url.split("#", 1)[0].strip()


def _store_leclerc_listing_image(url: Optional[str], image_url: Optional[str]) -> None:
    if not url or not image_url:
        return
    key = _normalize_leclerc_url_key(url)
    value = image_url.strip()
    if not key or not value:
        return
    LECLERC_LISTING_IMAGES[key] = value
    if len(LECLERC_LISTING_IMAGES) > 128:
        try:
            LECLERC_LISTING_IMAGES.pop(next(iter(LECLERC_LISTING_IMAGES)))
        except StopIteration:
            pass


def _lookup_leclerc_listing_image(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return LECLERC_LISTING_IMAGES.get(_normalize_leclerc_url_key(url))


def _close_playwright() -> None:
    pw = PLAYWRIGHT_SINGLETON.get("playwright")
    browser = PLAYWRIGHT_SINGLETON.get("browser")
    context = PLAYWRIGHT_SINGLETON.get("context")
    try:
        if context is not None:
            context.close()
    except Exception:
        pass
    try:
        if browser is not None:
            browser.close()
    except Exception:
        pass
    try:
        if pw is not None:
            pw.stop()
    except Exception:
        pass
    PLAYWRIGHT_SINGLETON.update({"playwright": None, "browser": None, "context": None})
def _ensure_sync_playwright_context():
    if sync_playwright is None:
        return None
    if PLAYWRIGHT_SINGLETON["context"] is not None:
        return PLAYWRIGHT_SINGLETON["context"]
    try:
        pw = sync_playwright().start()
    except Exception:
        return None
    browser = None
    context = None
    try:
        cdp_url = os.environ.get("CDP_URL")
        if cdp_url:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            existing = browser.contexts
            context = existing[0] if existing else browser.new_context()
        else:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
    except Exception:
        try:
            pw.stop()
        except Exception:
            pass
        return None
    PLAYWRIGHT_SINGLETON.update({"playwright": pw, "browser": browser, "context": context})
    atexit.register(_close_playwright)
    return context
def _make_monoprix_image_provider() -> Optional[ImageCompareProvider]:
    try:
        from .image_matching import compare_references
    except Exception:
        return None

    def _provider(_self, seed_url: Optional[str], cand_url: Optional[str]) -> bool:
        if not seed_url or not cand_url:
            return False
        clean_seed = re.sub(r"\s+", "", seed_url).strip()
        clean_cand = re.sub(r"\s+", "", cand_url).strip()
        if not clean_seed or not clean_cand:
            return False
        return compare_references(clean_seed, clean_cand, threshold=16)

    return _provider
def _make_leclerc_html_provider() -> Optional[HtmlProvider]:
    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        return None
    @lru_cache(maxsize=64)
    def _fetch(url: str) -> Optional[str]:
        if not url:
            return None
        page = None
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            try:
                page.wait_for_selector("h1", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(600)
            html = page.content()
            if html and "datadome" in html.lower():
                page.wait_for_timeout(1200)
                html = page.content()
            return html
        except Exception:
            return None
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
    return _fetch
def _clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())
def _compose_keyword_query(keywords: List[str], max_length: int = 40) -> str:
    tokens = [t.strip() for t in keywords if isinstance(t, str) and t.strip()]
    query = " ".join(tokens)
    if len(query) <= max_length:
        return query
    trimmed: List[str] = []
    for token in tokens:
        trial = " ".join(trimmed + [token]) if trimmed else token
        if len(trial) <= max_length or not trimmed:
            trimmed.append(token)
        else:
            break
    return " ".join(trimmed)[:max_length].rstrip()
def _make_leclerc_listing_provider() -> Optional[Callable[[List[str]], List[Tuple[str, str, str]]]]:
    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        return None
    store_url = os.environ.get(
        "LECLERC_FINDER_STORE_URL",
        "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx",
    )
    def _provider(keywords: List[str]) -> List[Tuple[str, str, str]]:
        query = _compose_keyword_query(keywords)
        if not query:
            return []
        page = None
        from urllib.parse import urljoin
        results: List[Tuple[str, str, str]] = []
        try:
            page = context.new_page()
            page.goto(store_url, wait_until="domcontentloaded", timeout=15000)
            try:
                consent = page.query_selector("#onetrust-accept-btn-handler")
                if consent:
                    consent.click()
                    page.wait_for_timeout(600)
            except Exception:
                pass
            search_box = page.query_selector("input[id*='rechercheTexte']")
            if not search_box:
                return []
            search_box.click()
            page.wait_for_timeout(200)
            search_box.fill("")
            page.wait_for_timeout(150)
            for ch in query:
                search_box.type(ch, delay=30)
            page.wait_for_timeout(350)
            try:
                search_box.press("Enter")
            except Exception:
                page.keyboard.press("Enter")
            try:
                page.wait_for_selector("li.liWCRS310_Product", timeout=8000)
            except PlaywrightTimeoutError:
                return []
            page.wait_for_timeout(500)
            cards = page.query_selector_all("li.liWCRS310_Product")
            for card in cards:
                try:
                    link = card.query_selector("a.aWCRS310_Product")
                    if not link:
                        continue
                    href = link.get_attribute("href") or ""
                    if not href:
                        continue
                    title = _clean_text(link.inner_text())
                    snippet_node = card.query_selector(".divWCRS310_Description") or card
                    snippet = _clean_text(snippet_node.inner_text() if snippet_node else "")
                    abs_url = urljoin(page.url, href)
                    thumb = None
                    img_node = card.query_selector("img")
                    if img_node:
                        for attr in ("data-src", "data-srcset", "src"):
                            raw = img_node.get_attribute(attr)
                            if raw and raw.strip():
                                thumb = raw.strip().split(" ")[0]
                                break
                    if thumb:
                        if thumb.startswith("//"):
                            thumb = "https:" + thumb
                        elif thumb.startswith("/"):
                            thumb = urljoin(page.url, thumb)
                        elif not thumb.lower().startswith(("http://", "https://")):
                            thumb = urljoin(page.url, thumb)
                        _store_leclerc_listing_image(abs_url, thumb)
                    results.append((abs_url, title, snippet))
                    if len(results) >= 10:
                        break
                except Exception:
                    continue
            return results
        except Exception:
            return []
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
    return _provider

def _make_monoprix_listing_provider() -> Optional[Callable[[List[str]], List[Tuple[str, str, str]]]]:
    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        return None

    @lru_cache(maxsize=64)
    def _provider_cached(query: str) -> List[Tuple[str, str, str]]:
        if not query:
            return []
        page = None
        results: List[Tuple[str, str, str]] = []
        try:
            page = context.new_page()
            search_url = f"https://courses.monoprix.fr/search?q={query}"
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            try:
                page.wait_for_selector("a[href*='/p/']", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(800)
            anchors = page.query_selector_all("a[href*='/p/']")
            seen: set[str] = set()
            for a in anchors:
                href = a.get_attribute("href") or ""
                if not href or "/content/" in href:
                    continue
                abs_url = href
                if abs_url.startswith("/"):
                    abs_url = f"https://courses.monoprix.fr{abs_url}"
                if abs_url in seen:
                    continue
                seen.add(abs_url)
                title = _clean_text(a.inner_text() or "")
                if not title:
                    continue
                snippet_node = a.query_selector("div, span")
                snippet = _clean_text(snippet_node.inner_text()) if snippet_node else ""
                results.append((abs_url, title, snippet))
                if len(results) >= 12:
                    break
        except Exception:
            return results
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
        return results

    def _provider(keywords: List[str]) -> List[Tuple[str, str, str]]:
        query = _compose_keyword_query(keywords, max_length=32)
        return _provider_cached(query)

    return _provider
# ---------- Modèle ----------
@dataclass
class ProductDescriptor:
    title: str = ""
    brand: str = ""
    kind: str = ""            # ex: "miel de fleurs"
    qty: str = ""             # ex: "500 g" ou "1,75 L"
    qualifiers: List[str] = field(default_factory=list)  # ex: ["bio", "sans sucre"]
    ean: Optional[str] = None
    image_url: Optional[str] = None
    source: str = ""          # nom d’enseigne adapter
    raw_text: str = ""        # descriptif long brut pour matching
    seed_query: str = ""      # requete seed (titre riche)
    leclerc_queries: List[str] = field(default_factory=list) # requetes specifiques leclerc
    def tokens(self) -> List[str]:
        txt = " ".join([self.title, self.brand, self.kind, self.qty, " ".join(self.qualifiers), self.raw_text])
        txt = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿœ\s\-\.]", " ", txt.lower())
        return [t for t in re.split(r"\s+", txt) if t]


def _descriptor_to_product(payload: Optional[Dict[str, Any]], *, source: str) -> Optional[ProductDescriptor]:
    if not isinstance(payload, dict):
        return None
    canonical = payload.get("canonical") if isinstance(payload.get("canonical"), dict) else {}
    title = payload.get("name") or payload.get("seed_primary_name") or canonical.get("name_core") or ""
    brand = payload.get("brand") or canonical.get("brand") or ""
    qty = payload.get("quantity") or payload.get("seed_primary_quantity") or ""
    qualifiers = []
    for key in ("secondary_keywords", "qualifiers"):
        values = payload.get(key)
        if isinstance(values, (list, tuple)):
            for item in values:
                if isinstance(item, str) and item not in qualifiers:
                    qualifiers.append(item)
    image_url = None
    images = payload.get("images") or canonical.get("images")
    if isinstance(images, (list, tuple)) and images:
        image_url = images[0]
    elif isinstance(payload.get("image"), str):
        image_url = payload.get("image")
    raw_parts = []
    for key in ("description", "seed_query", "note"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            raw_parts.append(value.strip())
    def infer_brand_from_title(raw_title: str, fallback: str) -> str:
        generic = {
            "boisson",
            "lait",
            "jus",
            "eau",
            "soda",
            "boite",
            "bouteille",
            "pack",
            "lot",
            "bio",
            "sans",
            "produit",
            "vegetal",
            "végétal",
            "amande",
            "grillee",
            "grillée",
            "vanille",
            "intense",
        }
        tokens = re.findall(r"[A-Za-zÀ-ÿ0-9']+", raw_title or "")
        for tok in tokens:
            norm = tok.lower()
            if norm in generic:
                continue
            if any(char.isalpha() for char in tok) and not any(char.isdigit() for char in tok):
                return tok.strip()
        # fallback: dernier token alpha non générique
        for tok in reversed(tokens):
            norm = tok.lower()
            if norm in generic:
                continue
            if any(char.isalpha() for char in tok) and not any(char.isdigit() for char in tok):
                return tok.strip()
        return fallback

    brand_clean = str(brand or "").strip()
    if not brand_clean or brand_clean.lower() in {"", "boisson", "produit", "marque"}:
        brand_clean = infer_brand_from_title(str(title or ""), brand_clean)

    return ProductDescriptor(
        title=str(title or ""),
        brand=brand_clean,
        kind="",
        qty=str(qty or ""),
        qualifiers=qualifiers,
        ean=str(payload.get("ean") or "") or None,
        image_url=image_url,
        source=source,
        raw_text=" \n".join(raw_parts),
        seed_query=payload.get("seed_query") or "",
        leclerc_queries=payload.get("leclerc_queries") or [],
    )
# ---------- Interfaces Adapters ----------
class EanSearch(Protocol):
    def search_by_ean(self, ean: str) -> Optional[ProductDescriptor]:
        ...
class KeywordSearch(Protocol):
    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        """Retourne une liste d’URLs candidates (résultats de recherche)."""
        ...
    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        ...
class Adapter(Protocol):
    name: str
    supports_ean: bool
    supports_keywords: bool
    can_extract_ean_from_href: bool
    def hard_validate(self, src: "ProductDescriptor", url: str, pd: "ProductDescriptor") -> Optional[float]: ...
    def override_threshold(self) -> Optional[float]: ...
    def override_strict_qty(self) -> Optional[bool]: ...
    def html(self) -> HtmlProvider | None: ...
    def image_compare(self) -> Optional[ImageCompareProvider]: ...
# ---------- Moteur de consolidation ----------
class Consolidator:
    def __init__(self) -> None:
        self.sources: List[ProductDescriptor] = []
    def add(self, d: Optional[ProductDescriptor]) -> None:
        if d:
            self.sources.append(d)
    def merged(self) -> ProductDescriptor:
        # règle simple: privilégie champs les plus fréquents non vides parmi sources EAN-direct
        preferred_sources = {"seed", "canonical"}
        def pick(field: str, prefer_seed: bool = False) -> str:
            if prefer_seed:
                for src in self.sources:
                    source_label = (src.source or "").lower()
                    if source_label in preferred_sources:
                        value = getattr(src, field)
                        if value:
                            return value
            vals = [getattr(s, field) for s in self.sources if getattr(s, field)]
            if not vals:
                return ""
            # mode
            scores: Dict[str, int] = {}
            for v in vals:
                scores[v] = scores.get(v, 0) + 1
            return max(scores.items(), key=lambda kv: kv[1])[0]
        merged = ProductDescriptor(
            title=pick("title", prefer_seed=True),
            brand=pick("brand", prefer_seed=True),
            kind=pick("kind"),
            qty=pick("qty", prefer_seed=True),
            ean=next((s.ean for s in self.sources if s.ean), None),
            image_url=next((s.image_url for s in self.sources if s.image_url), None),
            source="consolidated",
            raw_text=" ".join([s.raw_text for s in self.sources if s.raw_text]),
            seed_query=pick("seed_query", prefer_seed=True),
        )
        # leclerc_queries: union
        lq_all: List[str] = []
        for s in self.sources:
            for lq in s.leclerc_queries:
                if lq not in lq_all:
                    lq_all.append(lq)
        merged.leclerc_queries = lq_all
        # qualifiers: union pondérée
        q_all: Dict[str, int] = {}
        for s in self.sources:
            for q in s.qualifiers:
                q_all[q] = q_all.get(q, 0) + 1
        merged.qualifiers = [q for q, _n in sorted(q_all.items(), key=lambda kv: -kv[1])]
        return merged
# ---------- Générateur de mots-clés ----------
class KeywordGenerator:
    STOPWORDS = {
        "le",
        "la",
        "les",
        "de",
        "des",
        "du",
        "au",
        "aux",
        "d",
        "l",
        "et",
        "pour",
        "avec",
        "boire",
        "sans",
        "lot",
        "lots",
        "pack",
        "packs",
        "promo",
        "produit",
        "produits",
        "course",
        "courses",
        "drive",
        "magasin",
        "offre",
        "offres",
        "nouveau",
        "nouvelle",
        "format",
        "original",
        "grand",
        "grande",
        "qualite",
        "qualité",
        "marque",
        "supermarché",
        "supermarche",
    }

    GENERIC_TOKENS = {
        "cafe",
        "cafes",
        "café",
        "cafés",
        "boisson",
        "boissons",
        "produit",
        "produits",
        "arabica",
        "intensite",
        "intensité",
        "qualite",
        "qualité",
    }

    BOOST_SUBSTRINGS = (
        "capsul",
        "dosett",
        "pod",
        "supremo",
        "ristretto",
        "espresso",
        "nespresso",
    )

    def __init__(self, max_keywords: int = 4, max_length: int = 30) -> None:
        self.max_keywords = max_keywords
        self.max_length = max_length

    @staticmethod
    def _strip_accents(value: str) -> str:
        import unicodedata
        return "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")

    def _normalize(self, value: Optional[str]) -> str:
        if not value:
            return ""
        value = self._strip_accents(value.lower())
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    def _format_brand(self, value: Optional[str]) -> str:
        if not isinstance(value, str):
            return ""
        cleaned = re.sub(r"\s+", " ", value.strip())
        if not cleaned:
            return ""
        if cleaned.isupper():
            return cleaned.title()
        return cleaned

    def _format_quantity(self, value: Optional[str]) -> str:
        if not isinstance(value, str):
            return ""
        cleaned = value.strip()
        if not cleaned:
            return ""
        cleaned = cleaned.replace(",", ".")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.upper()

    def _expand_quantity_variants(self, quantity: Optional[str]) -> List[str]:
        formatted = self._format_quantity(quantity)
        if not formatted:
            return []

        variants: List[str] = []
        seen: set[str] = set()

        def add_variant(text: str) -> None:
            candidate = text.strip()
            if not candidate:
                return
            key = candidate.upper()
            if key in seen:
                return
            seen.add(key)
            variants.append(candidate)

        add_variant(formatted)

        match = re.match(r"(?P<number>\d+(?:\.\d+)?)(?:\s*)?(?P<unit>ML|CL|L)\b", formatted)
        if match:
            try:
                value = float(match.group("number"))
            except ValueError:
                value = None
            unit = match.group("unit")
            if value is not None:
                liters = value
                if unit == "ML":
                    liters = value / 1000.0
                elif unit == "CL":
                    liters = value / 100.0

                liter_text = f"{liters:.2f}"
                add_variant(f"{liter_text} L")
                add_variant(f"{liter_text.replace('.', ',')} L")

                cl_value = int(round(liters * 100))
                ml_value = int(round(liters * 1000))
                if cl_value > 0:
                    add_variant(f"{cl_value} CL")
                if ml_value > 0:
                    add_variant(f"{ml_value} ML")

        return variants

    def _extract_tokens(self, descriptor: ProductDescriptor) -> List[str]:
        counter: Dict[str, float] = {}
        brand_norm = self._normalize(descriptor.brand)
        tracked_tokens: set[str] = set()

        raw_text = descriptor.raw_text
        if isinstance(raw_text, str) and len(raw_text) > 180:
            raw_text = " ".join(raw_text.split()[:40])

        def harvest(text: Optional[str], weight: float, *, primary: bool = False) -> None:
            if not text:
                return
            normalized_text = self._normalize(text)
            if not normalized_text:
                return
            for token in normalized_text.split():
                if not token or len(token) <= 2:
                    continue
                if token.isdigit():
                    continue
                if token in self.STOPWORDS:
                    continue
                if brand_norm and token == brand_norm:
                    continue
                counter[token] = counter.get(token, 0.0) + weight
                if primary:
                    tracked_tokens.add(token)

        harvest(descriptor.kind, 5.0, primary=True)
        harvest(descriptor.title, 4.0, primary=True)
        harvest(" ".join(descriptor.qualifiers), 3.0, primary=True)
        if raw_text:
            filtered = " ".join(tok for tok in self._normalize(raw_text).split() if tok in tracked_tokens)
            harvest(filtered, 0.5)
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return [token for token, _score in ranked]

    def _build_query(self, parts: List[str]) -> Optional[str]:
        cleaned_parts = [re.sub(r"\s+", " ", part.strip()) for part in parts if part and part.strip()]
        if not cleaned_parts:
            return None
        candidate = " ".join(cleaned_parts)
        while len(candidate) > self.max_length and len(cleaned_parts) > 1:
            cleaned_parts.pop()
            candidate = " ".join(cleaned_parts)
        if len(candidate) > self.max_length:
            candidate = candidate[: self.max_length].rstrip()
        return candidate or None

    def make(self, d: ProductDescriptor) -> List[str]:
        brand = self._format_brand(d.brand)
        quantity_variants = self._expand_quantity_variants(d.qty)
        quantity_primary = quantity_variants[0] if quantity_variants else ""
        tokens = self._extract_tokens(d)
        tokens = self._reprioritize_tokens(tokens)

        # déduire s’il s’agit d’un paquet multi-articles (xN)
        has_multiplier = False
        if d.qty and isinstance(d.qty, str):
            if re.search(r"\b\d+\s*[x×]\s*\d+\b", d.qty.lower()):
                has_multiplier = True
        if d.title and isinstance(d.title, str) and not has_multiplier:
            if re.search(r"\b\d+\s*[x×]\s*\d+\b", d.title.lower()):
                has_multiplier = True
        if not has_multiplier and sum(1 for t in tokens if re.fullmatch(r"\d+", t)) > 1:
            has_multiplier = True
        qualifiers = [self._format_brand(q) for q in d.qualifiers if isinstance(q, str)]

        queries: List[str] = []
        seen: set[str] = set()

        def add_query(parts: List[str]) -> None:
            query = self._build_query(parts)
            if not query:
                return
            key = query.lower()
            if key in seen:
                return
            seen.add(key)
            queries.append(query)

        main_token = tokens[0] if tokens else ""
        secondary_token = tokens[1] if len(tokens) > 1 else ""
        tertiary_token = tokens[2] if len(tokens) > 2 else ""

        if brand and main_token and quantity_variants:
            for qty in quantity_variants:
                add_query([brand, main_token, qty])

        if brand and main_token and secondary_token:
            add_query([brand, main_token, secondary_token])

        if brand and quantity_variants:
            for qty in quantity_variants:
                add_query([brand, qty])

        if brand and tertiary_token and quantity_primary and len(queries) < self.max_keywords:
            add_query([brand, tertiary_token, quantity_primary])

        for qual in qualifiers:
            if brand and qual and quantity_primary:
                add_query([brand, qual, quantity_primary])
            elif brand and qual and main_token:
                add_query([brand, qual, main_token])

        if not queries and brand and main_token:
            add_query([brand, main_token])

        if not queries and main_token and quantity_primary:
            add_query([main_token, quantity_primary])

        if not queries and tokens:
            add_query(tokens[:3])

        if not queries and brand:
            add_query([brand])

        return queries[: self.max_keywords]

    def _reprioritize_tokens(self, tokens: List[str]) -> List[str]:
        if not tokens:
            return tokens

        def priority(token: str) -> tuple[int, int]:
            base = token.lower()
            if any(sub in base for sub in self.BOOST_SUBSTRINGS):
                return (0, -len(token))
            if base in self.GENERIC_TOKENS:
                return (2, len(token))
            return (1, -len(token))

        enumerated = list(enumerate(tokens))
        enumerated.sort(key=lambda item: (*priority(item[1]), item[0]))
        return [token for _, token in enumerated]
# ---------- Moteur de matching ----------
class MatchingEngine:
    def __init__(self, strict_qty: bool = True) -> None:
        self.strict_qty = strict_qty
    def score(self, src: ProductDescriptor, tgt: ProductDescriptor) -> float:
        score = 0.0
        # marque
        if src.brand and tgt.brand and self._norm(src.brand) == self._norm(tgt.brand):
            score += 0.4
        # type
        if src.kind and tgt.kind and self._norm(src.kind) in self._norm(tgt.raw_text):
            score += 0.3
        # quantité
        if src.qty and tgt.qty and self._norm(src.qty) == self._norm(tgt.qty):
            score += 0.2
        elif not self.strict_qty and src.qty and tgt.raw_text and self._norm(src.qty) in self._norm(tgt.raw_text):
            score += 0.1
        # pénalité si “bio” apparaît côté cible alors que pas côté source
        src_has_bio = any(self._norm(q) == "bio" for q in src.qualifiers) or " bio " in f" {self._norm(src.raw_text)} "
        tgt_has_bio = any(self._norm(q) == "bio" for q in tgt.qualifiers) or " bio " in f" {self._norm(tgt.raw_text)} "
        if tgt_has_bio and not src_has_bio:
            score -= 0.2
        return max(0.0, min(1.0, score))
    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip().lower())
    def is_match(self, src: ProductDescriptor, tgt: ProductDescriptor, threshold: float = 0.7) -> bool:
        return self.score(src, tgt) >= threshold
    def image_match(
        self,
        seed_url: Optional[str],
        candidate_url: Optional[str],
        provider: Optional[ImageCompareProvider] = None,
    ) -> bool:
        if provider:
            try:
                return bool(provider(seed_url, candidate_url))
            except Exception:
                pass
        # Placeholder : on vérifie simplement un token commun >= 4 caractères entre les deux URLs.
        if not seed_url or not candidate_url:
            return False
        seed_tokens = re.sub(r"[^a-z0-9]+", " ", seed_url.lower()).split()
        candidate_tokens = re.sub(r"[^a-z0-9]+", " ", candidate_url.lower()).split()
        common = {t for t in seed_tokens if len(t) >= 4} & {t for t in candidate_tokens if len(t) >= 4}
        return bool(common)
# ---------- Registre d’adapters (dans le dur) ----------
class CarrefourAdapter:
    name = "carrefour"
    supports_ean = True
    supports_keywords = False
    can_extract_ean_from_href = False
    # Implémentation réelle à l’étape 2
    def search_by_ean(self, ean: str) -> Optional[ProductDescriptor]:
        descriptor = get_descriptor(ean)
        return _descriptor_to_product(descriptor, source="seed")
    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        return None
    def override_threshold(self) -> Optional[float]:
        return None
    def override_strict_qty(self) -> Optional[bool]:
        return None
    def html(self) -> HtmlProvider | None:
        return None
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None
class AuchanAdapter:
    name = "auchan"
    supports_ean = True
    supports_keywords = False
    can_extract_ean_from_href = False
    def search_by_ean(self, ean: str) -> Optional[ProductDescriptor]:
        descriptor = get_descriptor(ean)
        return _descriptor_to_product(descriptor, source="canonical")
    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        return None
    def override_threshold(self) -> Optional[float]:
        return None
    def override_strict_qty(self) -> Optional[bool]:
        return None
    def html(self) -> HtmlProvider | None:
        return None
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None
class MonoprixAdapter:
    name = "monoprix"
    supports_ean = False
    supports_keywords = True
    can_extract_ean_from_href = False
    _image_provider: Optional[ImageCompareProvider] = None
    def override_threshold(self) -> Optional[float]:
        return 0.75
    def override_strict_qty(self) -> Optional[bool]:
        return True
    def html(self) -> HtmlProvider | None:
        return getattr(self, "_html_provider", None)
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return getattr(self, "_image_provider", None)
    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        raise NotImplementedError
    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        raise NotImplementedError
    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        # Validation renforcée appliquée niveau pipeline (texte + image)
        return None
class IntermarcheAdapter:
    name = "intermarche"
    supports_ean = False
    supports_keywords = True
    can_extract_ean_from_href = True  # cas particulier
    def override_threshold(self) -> Optional[float]:
        return 0.7
    def override_strict_qty(self) -> Optional[bool]:
        return True
    def html(self) -> HtmlProvider | None:
        return getattr(self, "_html_provider", None)
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None
    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        raise NotImplementedError
    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        raise NotImplementedError
    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        if not src.ean:
            return None
        m = re.search(r"\b(\d{8,14})\b", url or "")
        if m:
            pd.ean = m.group(1)
            if pd.ean == src.ean:
                return 1.0
        return None
class LeclercAdapter:
    name = "leclerc"
    supports_ean = False
    supports_keywords = True
    can_extract_ean_from_href = False
    def _listing_image_for(self, url: str) -> Optional[str]:
        return _lookup_leclerc_listing_image(url)
    def override_threshold(self) -> Optional[float]:
        return 0.7
    def override_strict_qty(self) -> Optional[bool]:
        return True
    def html(self) -> HtmlProvider | None:
        return getattr(self, "_html_provider", None)
    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        raise NotImplementedError
    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        raise NotImplementedError
    def find_info_link(self, product_url: str) -> Optional[str]:
        get_html = self.html()
        if not get_html:
            return None
        html = get_html(product_url) or ""
        if not html:
            return None
        # ancre textuelle “Informations pratiques”
        for match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.I | re.S):
            href, text = match.group(1), match.group(2) or ""
            txt = re.sub(r"<[^>]+>", " ", text).strip().lower()
            if "information" in txt and "pratique" in txt:
                if href.lower().startswith("javascript:") or href.strip() == "#":
                    continue
                return self._absolutize(product_url, href)
        # fallback sur motif URL
        for match in re.finditer(r'href="([^"]+)"', html, flags=re.I):
            href = match.group(1)
            href_lc = href.lower()
            if any(key in href_lc for key in ["information", "fiche", "caracteristique", "pratique"]):
                if href_lc.startswith("javascript:") or href.strip() == "#":
                    continue
                return self._absolutize(product_url, href)
        return None
    def extract_ean_from_info(self, info_url: str) -> Optional[str]:
        get_html = self.html()
        if not get_html:
            return None
        html = get_html(info_url) or ""
        if not html:
            return None
        # Recherche directe
        m = re.search(r"(?:gtin13|gtin|ean)[^0-9]{0,20}(\d{8,14})", html, flags=re.I)
        if m:
            return m.group(1)
        # Texte linéaire
        for match in re.finditer(r">([^<]{0,200})<", html, flags=re.I):
            txt = match.group(1)
            if re.search(r"\b(EAN|GTIN|Code[-\s]?barres)\b", txt, flags=re.I):
                m2 = re.search(r"\b(\d{8,14})\b", txt)
                if m2:
                    return m2.group(1)
        # JSON-LD
        for match in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.I | re.S):
            body = match.group(1) or ""
            m3 = re.search(r'"(gtin13|gtin|ean)"\s*:\s*"(\d{8,14})"', body, flags=re.I)
            if m3:
                return m3.group(2)
        return None
    @staticmethod
    def _extract_ean_from_html(html: Optional[str], url: Optional[str] = None) -> Optional[str]:
        if not html:
            return None
        patterns = [
            r'"(?:gtin13|gtin|ean)"\s*:\s*"(\d{8,14})"',
            r">\s*(?:EAN|GTIN|Code(?:[-\s]?barres)?)\s*[:#]?\s*(\d{8,14})",
            r"data-(?:ean|productean|gtin)=\"?(\d{8,14})\"?",
        ]
        for raw in patterns:
            match = re.search(raw, html, flags=re.I)
            if match:
                return match.group(1)
        if url:
            match = re.search(r"(?<!\d)(\d{8,14})(?!\d)", url)
            if match:
                return match.group(1)
        match = re.search(r"(?<!\d)(\d{8,14})(?!\d)", html)
        if match:
            return match.group(1)
        return None
    @staticmethod
    def _absolutize(base: str, href: str) -> str:
        try:
            from urllib.parse import urljoin
            return urljoin(base, href)
        except Exception:
            return href
    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        if not src.ean:
            return None
        info = self.find_info_link(url)
        if not info:
            get_html = self.html()
            ean = self._extract_ean_from_html(get_html(url) if get_html else None, url)
        else:
            ean = self.extract_ean_from_info(info)
            if not ean:
                get_html = self.html()
                ean = self._extract_ean_from_html(get_html(url) if get_html else None, url)
        if ean:
            pd.ean = ean
            if ean == src.ean:
                return 1.0
        elif src.image_url and pd.image_url:
            try:
                from .image_matching import compare_references
            except Exception:
                return None
            if compare_references(src.image_url, pd.image_url, threshold=16):
                pd.ean = src.ean
                return 0.92
        return None

LeclercAdapterBase = LeclercAdapter
IntermarcheAdapterBase = IntermarcheAdapter
MonoprixAdapterBase = MonoprixAdapter

try:
    from .adapters_keyword_impl import (
        LeclercAdapter as _KeywordLeclercAdapter,
        IntermarcheAdapter as _KeywordIntermarcheAdapter,
        MonoprixAdapter as _KeywordMonoprixAdapter,
    )
except Exception:
    LeclercAdapter = LeclercAdapterBase
    IntermarcheAdapter = IntermarcheAdapterBase
    MonoprixAdapter = MonoprixAdapterBase
else:
    LeclercAdapter = _KeywordLeclercAdapter
    IntermarcheAdapter = _KeywordIntermarcheAdapter
    MonoprixAdapter = _KeywordMonoprixAdapter
class ChronodriveAdapter:
    name = "chronodrive"
    supports_ean = True
    supports_keywords = False
    can_extract_ean_from_href = False

    def search_by_ean(self, ean: str) -> Optional[ProductDescriptor]:
        descriptor = get_descriptor(ean)
        return _descriptor_to_product(descriptor, source="seed")

    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        return None

    def override_threshold(self) -> Optional[float]:
        return None

    def override_strict_qty(self) -> Optional[bool]:
        return None

    def html(self) -> HtmlProvider | None:
        return None

    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None


class CoursesUAdapter:
    name = "courseu"
    supports_ean = True
    supports_keywords = False
    can_extract_ean_from_href = False

    def search_by_ean(self, ean: str) -> Optional[ProductDescriptor]:
        descriptor = get_descriptor(ean)
        return _descriptor_to_product(descriptor, source="seed")

    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        return None

    def override_threshold(self) -> Optional[float]:
        return None

    def override_strict_qty(self) -> Optional[bool]:
        return None

    def html(self) -> HtmlProvider | None:
        return None

    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None


class G20Adapter:
    name = "g20"
    supports_ean = True
    supports_keywords = False
    can_extract_ean_from_href = False

    def search_by_ean(self, ean: str) -> Optional[ProductDescriptor]:
        descriptor = get_descriptor(ean)
        return _descriptor_to_product(descriptor, source="seed")

    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        return None

    def override_threshold(self) -> Optional[float]:
        return None

    def override_strict_qty(self) -> Optional[bool]:
        return None

    def html(self) -> HtmlProvider | None:
        return None

    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None


# Registres codés en dur. Ajouter un magasin = ajouter une classe + lister ici.
EAN_DIRECT_REGISTRY: List[type] = [
    CarrefourAdapter,
    AuchanAdapter,
    ChronodriveAdapter,
    CoursesUAdapter,
    G20Adapter,
]
KEYWORD_REGISTRY: List[type] = [
    MonoprixAdapter,
    IntermarcheAdapter,
    LeclercAdapter,
    # autres à ajouter ici
]
# ---------- Pipeline principal ----------
@dataclass
class MatchResult:
    adapter: str
    url: str
    descriptor: ProductDescriptor
    score: float
@dataclass(frozen=True)
class AdapterPolicy:
    requires_ean: bool
    require_image_lock: bool
    disallow_packs: bool
    min_text_score: float
POLICIES: Dict[str, AdapterPolicy] = {
    "intermarche": AdapterPolicy(requires_ean=True, require_image_lock=False, disallow_packs=True, min_text_score=0.70),
    "leclerc": AdapterPolicy(requires_ean=True, require_image_lock=False, disallow_packs=True, min_text_score=0.70),
    "monoprix": AdapterPolicy(requires_ean=False, require_image_lock=True, disallow_packs=True, min_text_score=0.75),
}
@dataclass
class AuditEntry:
    adapter: str
    url: str
    base_score: float
    threshold_used: float
    image_pass: bool
    forced: Optional[float]
    reason: str
class FinderPipeline:
    _hooks_initialized = False

    def __init__(self) -> None:
        self.ensure_hooks()
        self.consolidator = Consolidator()
        self.matcher = MatchingEngine(strict_qty=True)
        self.keywords: List[str] = []
        self.audit: List[AuditEntry] = []
        self._monoprix_cache: List[str] = []

    @classmethod
    def ensure_hooks(cls) -> None:
        if cls._hooks_initialized:
            return
        try:
            html_provider = _make_leclerc_html_provider()
            if html_provider is not None:
                LeclercAdapter._html_provider = staticmethod(html_provider)  # type: ignore[attr-defined]
            listing_provider = _make_leclerc_listing_provider()
            if listing_provider is not None:
                LeclercAdapter._listing_provider = staticmethod(listing_provider)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            image_provider = _make_monoprix_image_provider()
            if image_provider is not None:
                MonoprixAdapter._image_provider = image_provider  # type: ignore[attr-defined]
            listing_provider = _make_monoprix_listing_provider()
            if listing_provider is not None:
                MonoprixAdapter._listing_provider = staticmethod(listing_provider)  # type: ignore[attr-defined]
        except Exception:
            pass
        cls._hooks_initialized = True
    def _policy(self, adapter_name: str) -> AdapterPolicy:
        return POLICIES.get(adapter_name, AdapterPolicy(True, False, True, 0.70))
    # Étape A: collecter depuis sites EAN-direct
    def collect_from_ean_sites(self, ean: str) -> ProductDescriptor:
        for cls in EAN_DIRECT_REGISTRY:
            adapter = cls()
            assert getattr(adapter, "supports_ean", False) is True
            try:
                pd = adapter.search_by_ean(ean)
                self.consolidator.add(pd)
            except NotImplementedError:
                # placeholder tant que l’implémentation n’est pas faite
                continue
        consolidated = self.consolidator.merged()
        if not consolidated.ean:
            consolidated.ean = ean
        return consolidated
    # Étape B: générer mots-clés
    def generate_keywords(self, consolidated: ProductDescriptor) -> List[str]:
        base_text = (
            consolidated.seed_query
            or consolidated.title
            or consolidated.raw_text
            or consolidated.brand
            or ""
        ).strip()
        tokens = base_text.split()
        priority_keywords: List[str] = []
        if len(tokens) >= 4:
            priority_keywords.append(" ".join(tokens[:4]))
        if len(tokens) >= 3:
            priority_keywords.append(" ".join(tokens[:3]))

        heuristic_keywords = KeywordGenerator(max_keywords=4).make(consolidated)
        ai_keywords: List[str] = []
        if USE_AI_ASSIST and suggest_search_queries:
            profile = {
                "title": consolidated.title,
                "brand": consolidated.brand,
                "quantity": consolidated.qty,
                "qualifiers": consolidated.qualifiers,
                "ean": consolidated.ean,
                "seed_query": consolidated.seed_query,
            }
            try:
                resp = suggest_search_queries(
                    profile,
                    descriptor=asdict(consolidated),
                    max_queries=5,
                    store="generic",
                    max_length=32,
                )
                queries = resp.data.get("queries") if isinstance(resp.data, dict) else None
                if isinstance(queries, list):
                    ai_keywords = [q for q in queries if isinstance(q, str) and q.strip()]
            except Exception:
                ai_keywords = []

        merged: List[str] = []
        seen: set[str] = set()

        def push(seq: List[str]):
            for item in seq:
                value = " ".join(item.split())
                if not value:
                    continue
                key = value.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(value)

        push(priority_keywords)
        push(ai_keywords)
        push(heuristic_keywords)
        self.keywords = merged[:8]
        if not self.keywords:
            fallback = self._fallback_keywords_from_summary(consolidated.ean)

def _fallback_keywords_from_summary(self, ean: Optional[str]) -> List[str]:
    if not ean:
        return []
    summary_path = Path(os.environ.get("RESULTS_DIR") or "/Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicourses_test/results") / "summary.json"
    if not summary_path.exists():
        return []
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    block = data.get(str(ean))
    if not isinstance(block, dict):
        return []
    titles: List[str] = []
    brands: List[str] = []
    for entry in block.values():
        if not isinstance(entry, dict):
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        t = payload.get("title") or payload.get("product_name")
        product_obj = payload.get("product") or {}
        b = payload.get("brand") or product_obj.get("brand")
        if isinstance(t, str) and t.strip():
            titles.append(t.strip())
        if isinstance(b, str) and b.strip():
            brands.append(b.strip())
        if not b and isinstance(t, str) and t.strip():
            inferred = _infer_brand_from_title(t)
            if inferred:
                brands.append(inferred)
    title = titles[0] if titles else ""
    brand = brands[0] if brands else ""
    tokens = []
    norm = re.sub(r"[^a-z0-9]+", " ", title.lower())
    for tok in norm.split():
        if re.search(r"\d", tok):
            continue
        if tok in {"ml", "l", "cl", "kg", "g", "gr", "litre", "litres"}:
            continue
        if tok and tok not in tokens:
            tokens.append(tok)
    main = tokens[0] if tokens else ""
    candidates = []
    if brand and main:
        candidates.append(f"{brand} {main}")
    if title:
        candidates.append(title)
    if main:
        candidates.append(main)
    seen: set[str] = set()
    filtered: List[str] = []
    for q in candidates:
        key = q.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        filtered.append(q)
    return filtered[:3]

def _monoprix_keywords(self, consolidated: ProductDescriptor) -> List[str]:
    """
    Requêtes Monoprix sans quantités pour éviter les listings trop larges.
    """
    filtered: List[str] = []
    seen: set[str] = set()
    unit_tokens = {"ml", "l", "cl", "kg", "g", "gr", "kg.", "l.", "ml.", "cl.", "litre", "litres"}

    def strip_qty(query: str) -> Optional[str]:
        tokens: List[str] = []
        for tok in query.split():
            low = tok.lower().strip()
            if re.search(r"\d", low):
                continue
            if low in unit_tokens:
                continue
            tokens.append(tok)
        cleaned = " ".join(tokens).strip()
        return cleaned or None

    for q in self.keywords:
        cleaned = strip_qty(q)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        filtered.append(cleaned)

    if not filtered:
        brand = (consolidated.brand or "").strip()
        title_tokens: List[str] = []
        norm_title = re.sub(r"[^a-z0-9]+", " ", (consolidated.title or "").lower())
        for tok in norm_title.split():
            if tok in unit_tokens or re.search(r"\d", tok):
                continue
            if tok and tok not in title_tokens:
                title_tokens.append(tok)
        main_token = title_tokens[0] if title_tokens else ""
        if brand and main_token:
            filtered.append(f"{brand} {main_token}")
        elif main_token:
            filtered.append(main_token)
        elif brand:
            filtered.append(brand)

def search_on_keyword_sites(self, consolidated: ProductDescriptor) -> List[MatchResult]:
    self.ensure_hooks()
    results: List[MatchResult] = []
    orig_strict = self.matcher.strict_qty
    for cls in KEYWORD_REGISTRY:
        adapter = cls()
        assert getattr(adapter, "supports_keywords", False) is True
        policy = self._policy(adapter.name)
        try:
            override_strict = adapter.override_strict_qty()
            if override_strict is not None:
                self.matcher.strict_qty = bool(override_strict)
            if adapter.name == "leclerc" and consolidated.leclerc_queries:
                urls = adapter.search_by_keywords(consolidated.leclerc_queries)
            elif adapter.name == "monoprix":
                urls = []
                mono_queries = self._monoprix_keywords(consolidated)
                for q in mono_queries:
                    attempt_urls = adapter.search_by_keywords([q])
                    if attempt_urls:
                        urls.extend(attempt_urls)
                        break
            else:
                urls = adapter.search_by_keywords(self.keywords)
            for url in urls:
                pd = adapter.parse_product_page(url)
                if not pd:
                    continue
                if getattr(adapter, "can_extract_ean_from_href", False):
                    m = re.search(r"(\d{8,14})", (url or ""))
                    if m and not pd.ean:
                        pd.ean = m.group(1)
                    if pd.ean:
                        self.consolidator.add(pd)
                provider: Optional[ImageCompareProvider] = None
                if hasattr(adapter, "image_compare"):
                    try:
                        provider = adapter.image_compare()
                    except Exception:
                        provider = None
                if policy.disallow_packs and is_pack_or_bundle(pd.title, pd.raw_text):
                    self.audit.append(
                        AuditEntry(
                            adapter=adapter.name,
                            url=url,
                            base_score=0.0,
                            threshold_used=policy.min_text_score,
                            image_pass=False,
                            forced=None,
                            reason="filtered_pack",
                        )
                    )
                    continue
                forced = adapter.hard_validate(consolidated, url, pd)
                if forced is not None:
                    if policy.requires_ean and not pd.ean:
                        self.audit.append(
                            AuditEntry(
                                adapter=adapter.name,
                                url=url,
                                base_score=1.0,
                                threshold_used=policy.min_text_score,
                                image_pass=False,
                                forced=float(forced),
                                reason="forced_but_missing_ean",
                            )
                        )
                        continue
                    results.append(MatchResult(adapter=adapter.name, url=url, descriptor=pd, score=float(forced)))
                    self.audit.append(
                        AuditEntry(
                            adapter=adapter.name,
                            url=url,
                            base_score=1.0,
                            threshold_used=policy.min_text_score,
                            image_pass=False,
                            forced=float(forced),
                            reason="hard_validate",
                        )
                    )
                    continue
                base_score = self.matcher.score(consolidated, pd)
                img_pass = True
                if policy.require_image_lock:
                    img_pass = self.matcher.image_match(
                        consolidated.image_url,
                        pd.image_url,
                        provider=provider,
                    )
                    if not img_pass:
                        self.audit.append(
                            AuditEntry(
                                adapter=adapter.name,
                                url=url,
                                base_score=base_score,
                                threshold_used=policy.min_text_score,
                                image_pass=False,
                                forced=None,
                                reason="image_lock_failed",
                            )
                        )
                        continue
                meets_text_threshold = base_score >= policy.min_text_score
                if not meets_text_threshold and not (policy.require_image_lock and img_pass):
                    self.audit.append(
                        AuditEntry(
                            adapter=adapter.name,
                            url=url,
                            base_score=base_score,
                            threshold_used=policy.min_text_score,
                            image_pass=img_pass,
                            forced=None,
                            reason="below_text_threshold",
                        )
                    )
                    continue
                if policy.requires_ean and not pd.ean:
                    self.audit.append(
                        AuditEntry(
                            adapter=adapter.name,
                            url=url,
                            base_score=base_score,
                            threshold_used=policy.min_text_score,
                            image_pass=img_pass,
                            forced=None,
                            reason="missing_ean_required",
                        )
                    )
                    continue
                final_score = base_score
                audit_reason = "generic"
                if policy.require_image_lock and img_pass and not meets_text_threshold:
                    final_score = max(final_score, policy.min_text_score)
                    audit_reason = "image_override"
                if adapter.name == "monoprix" and img_pass:
                    final_score = max(final_score, 0.995)
                    audit_reason = "mono_image_override" if audit_reason == "image_override" else "mono_text+image"
                results.append(MatchResult(adapter=adapter.name, url=url, descriptor=pd, score=final_score))
                self.audit.append(
                    AuditEntry(
                        adapter=adapter.name,
                        url=url,
                        base_score=base_score,
                        threshold_used=policy.min_text_score,
                        image_pass=img_pass,
                        forced=None,
                        reason=audit_reason,
                    )
                )
        except NotImplementedError:
            continue
        finally:
            self.matcher.strict_qty = orig_strict
        results.sort(key=lambda r: -r.score)
        return results
        return results
    # Étape D: décision
    def decide(self, consolidated: ProductDescriptor, candidates: List[MatchResult], threshold: float = 0.7
               ) -> Optional[MatchResult]:
        self.ensure_hooks()
        for c in candidates:
            policy = self._policy(c.adapter)
            thr = max(threshold, policy.min_text_score)
            if policy.requires_ean and not c.descriptor.ean:
                continue
            if c.score >= 0.99 or self.matcher.is_match(consolidated, c.descriptor, threshold=thr):
                return c
        return None
# ---------- API haut niveau ----------
def find_equivalents(ean: str, threshold: float = 0.7) -> Tuple[ProductDescriptor, List[str], List[MatchResult], Optional[MatchResult]]:
    pipeline = FinderPipeline()
    consolidated = pipeline.collect_from_ean_sites(ean)
    keywords = pipeline.generate_keywords(consolidated)
    candidates = pipeline.search_on_keyword_sites(consolidated)
    decision = pipeline.decide(consolidated, candidates, threshold=threshold)
    return consolidated, keywords, candidates, decision
# ---------- Exécution de test manuelle ----------
def _cli() -> None:
    parser = argparse.ArgumentParser(description="Finder pipeline debug")
    parser.add_argument("--ean", required=False, help="EAN à analyser (13 chiffres)")
    parser.add_argument("--threshold", type=float, default=0.7, help="Seuil de matching")
    parser.add_argument("--dump", action="store_true", help="Affiche les détails")
    args = parser.parse_args()
    ean = re.sub(r"\D", "", args.ean or "")
    if len(ean) != 13:
        raise SystemExit("[finder] EAN invalide")
    consolidated, keywords, candidates, decision = find_equivalents(ean, threshold=args.threshold)
    print("[Consolidated]", consolidated)
    print("[Keywords]", keywords)
    if args.dump:
        print("[Candidates top 5]", [(c.adapter, round(c.score, 3), c.url) for c in candidates[:5]])
        print("[Decision]", (decision.adapter, decision.url, round(decision.score, 3)) if decision else None)


if __name__ == "__main__":
    _cli()
