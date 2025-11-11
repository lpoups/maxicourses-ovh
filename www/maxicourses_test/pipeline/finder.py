# finder.py
# Étape 1/3 — Scaffold solide et extensible, 100% code “dans le dur”.
from __future__ import annotations
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Dict, Iterable, Optional, Tuple, Protocol, Callable
import re
import os
import atexit
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover - Playwright optional
    sync_playwright = None
    PlaywrightTimeoutError = Exception  # type: ignore
from .text_utils import is_pack_or_bundle
HtmlProvider = Callable[[str], Optional[str]]
ImageCompareProvider = Callable[[Optional[str], Optional[str]], bool]
PLAYWRIGHT_SINGLETON: Dict[str, Optional[object]] = {
    "playwright": None,
    "browser": None,
    "context": None,
}
PHASH_CACHE: Dict[str, Optional[int]] = {}
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
def _phash_js() -> str:
    return """
    async (imgUrl) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      const loaded = new Promise((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = (err) => reject(err);
      });
      img.src = imgUrl;
      await loaded;
      const size = 32;
      const smaller = 8;
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, size, size);
      let imageData;
      try {
        imageData = ctx.getImageData(0, 0, size, size);
      } catch (err) {
        return null;
      }
      const pixels = imageData.data;
      const signal = new Array(size);
      for (let y = 0; y < size; y++) {
        signal[y] = new Array(size);
        for (let x = 0; x < size; x++) {
          const idx = (y * size + x) * 4;
          const r = pixels[idx];
          const g = pixels[idx + 1];
          const b = pixels[idx + 2];
          signal[y][x] = 0.299 * r + 0.587 * g + 0.114 * b;
        }
      }
      const coeffs = [];
      for (let v = 0; v < smaller; v++) {
        for (let u = 0; u < smaller; u++) {
          let sum = 0;
          for (let y = 0; y < size; y++) {
            for (let x = 0; x < size; x++) {
              sum += signal[y][x] *
                Math.cos(((2 * x + 1) * u * Math.PI) / (2 * size)) *
                Math.cos(((2 * y + 1) * v * Math.PI) / (2 * size));
            }
          }
          const cu = u === 0 ? Math.SQRT1_2 : 1;
          const cv = v === 0 ? Math.SQRT1_2 : 1;
          const value = 0.25 * cu * cv * sum;
          coeffs.push(value);
        }
      }
      if (coeffs.length <= 1) {
        return null;
      }
      const rest = coeffs.slice(1);
      const avg = rest.reduce((acc, val) => acc + val, 0) / rest.length;
      let hash = 0n;
      for (let i = 0; i < coeffs.length; i++) {
        const value = coeffs[i];
        hash = (hash << 1n) | (value > avg ? 1n : 0n);
      }
      return hash.toString();
    }
    """
def _hamming_distance(a: int, b: int) -> int:
    x = a ^ b
    count = 0
    while x:
        x &= x - 1
        count += 1
    return count
def _compute_phash_sync(url: Optional[str]) -> Optional[int]:
    if not url:
        return None
    cached = PHASH_CACHE.get(url)
    if cached is not None:
        return cached
    context = _ensure_sync_playwright_context()
    if context is None:
        PHASH_CACHE[url] = None
        return None
    page = None
    try:
        page = context.new_page()
        page.goto("about:blank")
        script = _phash_js()
        h_str = page.evaluate(
            "async ({script, target}) => { const fn = eval(script); return await fn(target); }",
            {"script": script, "target": url},
        )
        value = int(h_str) if h_str is not None else None
        PHASH_CACHE[url] = value
        return value
    except Exception:
        PHASH_CACHE[url] = None
        return None
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
def _make_monoprix_image_provider() -> Optional[ImageCompareProvider]:
    if sync_playwright is None:
        return None
    if _ensure_sync_playwright_context() is None:
        return None
    def _provider(seed_url: Optional[str], cand_url: Optional[str]) -> bool:
        a = _compute_phash_sync(seed_url)
        b = _compute_phash_sync(cand_url)
        if a is None or b is None:
            return False
        return _hamming_distance(a, b) <= 12
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
            return page.content()
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
    def tokens(self) -> List[str]:
        txt = " ".join([self.title, self.brand, self.kind, self.qty, " ".join(self.qualifiers), self.raw_text])
        txt = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿœ\s\-\.]", " ", txt.lower())
        return [t for t in re.split(r"\s+", txt) if t]
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
        )
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
        raise NotImplementedError
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
        raise NotImplementedError
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
# Registres codés en dur. Ajouter un magasin = ajouter une classe + lister ici.
EAN_DIRECT_REGISTRY: List[type] = [
    CarrefourAdapter,
    AuchanAdapter,
    # CoursesUAdapter, ChronodriveAdapter, etc. à ajouter ici
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
        self.keywords = KeywordGenerator(max_keywords=4).make(consolidated)
        return self.keywords
    # Étape C: chercher sur sites sans EAN
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
                urls = adapter.search_by_keywords(self.keywords)
                for url in urls:
                    pd = adapter.parse_product_page(url)
                    if not pd:
                        continue
                    if getattr(adapter, "can_extract_ean_from_href", False):
                        m = re.search(r"\b(\d{8,14})\b", (url or ""))
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
                    if base_score < policy.min_text_score:
                        self.audit.append(
                            AuditEntry(
                                adapter=adapter.name,
                                url=url,
                                base_score=base_score,
                                threshold_used=policy.min_text_score,
                                image_pass=False,
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
                                image_pass=False,
                                forced=None,
                                reason="missing_ean_required",
                            )
                        )
                        continue
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
                    final_score = base_score
                    audit_reason = "generic"
                    if adapter.name == "monoprix" and img_pass:
                        final_score = max(final_score, 0.95)
                        audit_reason = "mono_text+image"
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
        # tri décroissant par score
        results.sort(key=lambda r: -r.score)
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
if __name__ == "__main__":
    # Appel “dans le dur” pour tester la tuyauterie.
    EAN = "5411188118961"  # exemple
    consolidated, keywords, candidates, decision = find_equivalents(EAN)
    print("[Consolidated]", consolidated)
    print("[Keywords]", keywords)
    print("[Candidates top 5]", [(c.adapter, round(c.score, 3), c.url) for c in candidates[:5]])
    print("[Decision]", (decision.adapter, decision.url, round(decision.score, 3)) if decision else None)
