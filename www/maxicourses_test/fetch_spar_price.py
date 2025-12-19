#!/usr/bin/env python3
"""Fetcher Spar (via mescoursesdeproximite.com or similar Casino backend) via requêtes HTTP."""
from __future__ import annotations

import json
import os
import re
import sys
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import urllib3  # type: ignore

from urllib3.exceptions import NotOpenSSLWarning

warnings.filterwarnings("ignore", category=NotOpenSSLWarning)

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:  # pragma: no cover - dépendance facultative
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore

EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
PROXY = os.environ.get("PROXY")
DIRECT_URL = (os.environ.get("DIRECT_URL") or "").strip()
SKIP_SEARCH = (os.environ.get("SKIP_SEARCH") or "0").lower() in {"1", "true", "yes"}

# SPAR / CASINO GROUP SHARED PLATFORM
BASE_URL = os.environ.get("SPAR_BASE_URL", "https://www.mescoursesdeproximite.com")
STORE_CODE = os.environ.get("SPAR_STORE_CODE", "UNKNOWN").strip()
STORE_SLUG = os.environ.get("SPAR_STORE_SLUG", "spar-unknown").strip()
STORE_LABEL = os.environ.get("SPAR_STORE_LABEL", "Spar").strip()
STORE_PATH = f"{STORE_SLUG}/{STORE_CODE}".strip("/")
STORE_URL = os.environ.get("SPAR_STORE_URL") or f"{BASE_URL.rstrip('/')}/courses-en-ligne/{STORE_PATH}"
SEARCH_TEMPLATE = os.environ.get(
    "SPAR_SEARCH_TEMPLATE",
    f"{BASE_URL.rstrip('/')}/recherche/{{store_code}}?produit_recherche={{query}}",
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.6",
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

SEARCH_TIMEOUT = (5, 20)

SIZE_PATTERN = re.compile(r"(\d+[.,]?\d*\s?(?:ml|cl|dl|l|kg|g))", re.IGNORECASE)
PACK_PATTERN = re.compile(r"(\d+\s*x\s*\d+[.,]?\d*\s?(?:ml|cl|kg|g)?)", re.IGNORECASE)
SCRIPT_JSON_PATTERN = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


@dataclass
class Candidate:
    url: str
    title: Optional[str] = None
    brand: Optional[str] = None
    price_text: Optional[str] = None
    unit_price: Optional[str] = None
    quantity: Optional[str] = None
    image: Optional[str] = None


@dataclass
class ResultPayload:
    status: str
    price: Optional[str] = None
    unit_price: Optional[str] = None
    quantity: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    note: Optional[str] = None
    store: Optional[str] = None
    matched_ean: Optional[str] = None
    image: Optional[str] = None
    product: Optional[Dict[str, Any]] = None
    _meta: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], {})}


class CardExtractor(HTMLParser):
    """Fallback parser pour extraire les cartes produit sans BeautifulSoup."""

    def __init__(self) -> None:
        super().__init__()
        self.fragments: List[str] = []
        self._capture_level = 0
        self._buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attr_map = {key: (value or "") for key, value in attrs}
        class_attr = attr_map.get("class", "")
        start_text = self.get_starttag_text() or ""
        if (
            tag == "div"
            and "card-produit-vignette" in class_attr
            and "card" in class_attr
            and self._capture_level == 0
        ):
            self._capture_level = 1
            self._buffer = [start_text]
            return
        if self._capture_level > 0:
            self._capture_level += 1
            self._buffer.append(start_text)

    def handle_endtag(self, tag: str) -> None:
        if self._capture_level > 0:
            self._buffer.append(f"</{tag}>")
            self._capture_level -= 1
            if self._capture_level == 0:
                self.fragments.append("".join(self._buffer))
                self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture_level > 0:
            self._buffer.append(data)

    def handle_startendtag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        if self._capture_level > 0:
            start_text = self.get_starttag_text() or ""
            self._buffer.append(start_text)


def _build_search_url(term: str) -> str:
    safe_query = quote(term, safe="")
    template = SEARCH_TEMPLATE or "{base}/recherche/{store_code}?produit_recherche={query}"
    return (
        template.replace("{base}", BASE_URL.rstrip("/"))
        .replace("{query}", safe_query)
        .replace("{term}", safe_query)
        .replace("{ean}", safe_query)
        .replace("{store_code}", STORE_CODE)
        .replace("{store}", STORE_CODE)
    )


def _normalize_price(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    # Support numbers coming from JSON-LD (int/float) in direct mode
    if isinstance(text, (int, float)):
        text = f"{text:.2f}" if isinstance(text, float) else str(text)
    cleaned = (
        str(text)
        .replace("\xa0", " ")
        .replace("€", "")
        .strip()
        .replace(" ", "")
        .replace(",", ".")
    )
    match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    if not match:
        return None
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    quantized = value.quantize(Decimal("0.01"))
    return f"{quantized:.2f}".replace(".", ",")


def _strip_parentheses(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().strip("()").strip()


def _extract_pdp_price_info(html: str) -> tuple[Optional[str], Optional[str]]:
    if not html:
        return None, None
    price_text = None
    unit_text = None
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "lxml")
            container = soup.select_one(".prixProduit")
            if container:
                spans = container.select("span")
                for span in spans:
                    text = span.get_text(" ", strip=True)
                    if not text or "€" not in text:
                        continue
                    if text.startswith("(") and text.endswith(")"):
                        unit_text = text.strip("()")
                    elif price_text is None:
                        price_text = text
        except Exception:
            price_text = unit_text = None
    if not price_text:
        match = re.search(r'prixProduit[\s\S]*?<span[^>]*>\s*([\d\s.,]+)\s*€', html, re.IGNORECASE)
        if match:
            price_text = match.group(1).strip() + " €"
    if not unit_text:
        match = re.search(r'\(([^<>]*€\s*/[^<>]+)\)', html, re.IGNORECASE)
        if match:
            unit_text = match.group(1).strip()
    return price_text, unit_text


def _guess_quantity(*texts: Optional[str]) -> Optional[str]:
    for raw in texts:
        if not raw:
            continue
        text = raw.replace("\xa0", " ")
        pack = PACK_PATTERN.search(text)
        if pack:
            return pack.group(1).strip()
        size = SIZE_PATTERN.search(text)
        if size:
            return size.group(1).strip()
    return None


def _clean_html_text(value: str) -> str:
    cleaned = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_price_from_card(card_node) -> Optional[str]:
    if BeautifulSoup is None:
        return None
    for span in card_node.select("span"):
        text = span.get_text(" ", strip=True)
        if not text:
            continue
        if "€" not in text:
            continue
        if "/" in text:
            continue
        if re.search(r"\d", text):
            return text
    return None


def _parse_cards_with_bs4(html: str) -> List[Candidate]:
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    cards: List[Candidate] = []
    for node in soup.select("div.card.card-produit-vignette"):
        link = node.select_one(".produit-desc a[href]")
        if not link:
            continue
        href = link["href"]
        title_node = node.select_one(".produit-desc h3")
        brand_node = node.select_one(".produit-desc strong")
        unit_node = node.select_one(".produit-desc span.montserratlight")
        img_node = node.select_one(".produit-img img")
        raw_title = title_node.get_text(" ", strip=True) if title_node else ""
        brand = brand_node.get_text(" ", strip=True) if brand_node else ""
        unit_price = unit_node.get_text(" ", strip=True) if unit_node else None
        price_text = _extract_price_from_card(node)
        quantity = _guess_quantity(raw_title, unit_price)
        image = urljoin(BASE_URL, img_node["src"]) if img_node and img_node.get("src") else None
        cards.append(
            Candidate(
                url=urljoin(BASE_URL, href),
                title=raw_title or None,
                brand=brand or None,
                price_text=price_text,
                unit_price=_strip_parentheses(unit_price),
                quantity=quantity,
                image=image,
            )
        )
    return cards


def _parse_cards_fallback(html: str) -> List[Candidate]:
    extractor = CardExtractor()
    extractor.feed(html)
    cards: List[Candidate] = []
    for fragment in extractor.fragments:
        link_match = re.search(r'<a[^>]+href="([^"]+/produit/[^"]+)"', fragment)
        if not link_match:
            continue
        href = link_match.group(1)
        img_match = re.search(r'<img[^>]+src="([^"]+)"', fragment)
        brand_match = re.search(r"<strong>(.*?)</strong>", fragment, re.DOTALL | re.IGNORECASE)
        name_match = re.search(r"<h3[^>]*>(.*?)</h3>", fragment, re.DOTALL | re.IGNORECASE)
        unit_match = re.search(r"\(([^()]*€/[^()]+)\)", fragment)
        price_match = re.search(r">([\d\s.,]+)\s*€<", fragment)
        title = _clean_html_text(name_match.group(1)) if name_match else None
        brand = _clean_html_text(brand_match.group(1)) if brand_match else None
        unit_price = _strip_parentheses(unit_match.group(1) if unit_match else None)
        quantity = _guess_quantity(title, unit_price)
        image = urljoin(BASE_URL, img_match.group(1)) if img_match else None
        price_text = price_match.group(1).strip() + " €" if price_match else None
        cards.append(
            Candidate(
                url=urljoin(BASE_URL, href),
                title=title,
                brand=brand,
                price_text=price_text,
                unit_price=unit_price,
                quantity=quantity,
                image=image,
            )
        )
    return cards


def _parse_cards(html: str) -> List[Candidate]:
    cards = _parse_cards_with_bs4(html)
    if cards:
        return cards
    return _parse_cards_fallback(html)


def _extract_product_jsonld(html: str) -> Optional[Dict[str, Any]]:
    for match in SCRIPT_JSON_PATTERN.finditer(html):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for entry in _iter_jsonld(data):
            if isinstance(entry, dict) and entry.get("@type") == "Product":
                return entry
    return None


def _iter_jsonld(data: Any):
    if isinstance(data, dict):
        if data.get("@type") == "Product":
            yield data
        if isinstance(data.get("itemListElement"), list):
            for item in data["itemListElement"]:
                yield from _iter_jsonld(item)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_jsonld(item)


def _fetch_product_details(session: requests.Session, url: str) -> Dict[str, Any]:
    try:
        response = session.get(url, timeout=SEARCH_TIMEOUT)
    except requests.RequestException:
        return {}
    if response.status_code >= 400:
        return {}
    html = response.text
    data = _extract_product_jsonld(html)
    price_text, unit_text = _extract_pdp_price_info(html)
    if not isinstance(data, dict):
        data = {}
    brand = None
    brand_entry = data.get("brand")
    if isinstance(brand_entry, dict):
        brand = brand_entry.get("name")
    elif isinstance(brand_entry, str):
        brand = brand_entry
    offers = data.get("offers")
    if not isinstance(offers, dict):
        offers = None
    schema_price = offers.get("price") if offers else data.get("price")
    price_value = price_text or schema_price
    return {
        "ean": data.get("gtin13") or data.get("gtin") or data.get("sku"),
        "brand": brand,
        "name": data.get("name"),
        "price": price_value,
        "unit_price": unit_text,
    }


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if PROXY:
        session.proxies.update({"http": PROXY, "https": PROXY})
    retry = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_spar() -> ResultPayload:
    if not EAN:
        return ResultPayload(status="ERROR", error="EAN manquant", note=STORE_LABEL)
    
    # Allow missing store code if we just want to test logic, but in prod it's needed
    # if not STORE_CODE:
    #     return ResultPayload(status="ERROR", error="STORE_CODE manquant", note=STORE_LABEL)
    
    query = QUERY or EAN
    if not query:
        return ResultPayload(status="ERROR", error="Requête vide", note=STORE_LABEL)

    session = _make_session()

    if DIRECT_URL:
        direct_meta = {
            "store_code": STORE_CODE,
            "store_url": STORE_URL,
            "query": query,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direct_url": DIRECT_URL,
        }
        details = _fetch_product_details(session, DIRECT_URL)
        details = details if isinstance(details, dict) else {}
        matched_ean = details.get("ean")
        if matched_ean and EAN and matched_ean != EAN:
            if SKIP_SEARCH:
                return ResultPayload(
                    status="NO_MATCH",
                    note=STORE_LABEL,
                    url=DIRECT_URL,
                    matched_ean=matched_ean,
                    _meta=direct_meta,
                )
        price = _normalize_price(details.get("price"))
        unit_price = _strip_parentheses(details.get("unit_price"))
        title = details.get("name")
        brand = details.get("brand")
        quantity = _guess_quantity(title)
        if price:
            payload_product = {
                "title": title,
                "brand": brand,
                "qty": quantity,
                "ean": matched_ean or EAN,
                "image_url": None,
                "source": "spar",
            }
            return ResultPayload(
                status="OK",
                price=price,
                unit_price=unit_price,
                quantity=quantity,
                title=title,
                url=DIRECT_URL,
                note=STORE_LABEL,
                store=STORE_LABEL,
                matched_ean=matched_ean or EAN,
                image=None,
                product=payload_product,
                _meta=direct_meta,
            )
        if SKIP_SEARCH:
            return ResultPayload(
                status="NO_PRICE",
                title=title,
                url=DIRECT_URL,
                note=STORE_LABEL,
                matched_ean=matched_ean or EAN,
                _meta=direct_meta,
            )

    search_url = _build_search_url(query)
    meta = {
        "search_url": search_url,
        "store_code": STORE_CODE,
        "store_url": STORE_URL,
        "query": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        response = session.get(search_url, timeout=SEARCH_TIMEOUT)
    except requests.RequestException as exc:
        return ResultPayload(status="ERROR", error=f"Requête échouée: {exc}", note=STORE_LABEL, _meta=meta)

    if response.status_code == 404:
        return ResultPayload(status="NO_RESULTS", note="Spar (404)", _meta=meta)
    if response.status_code >= 500:
        return ResultPayload(
            status="ERROR",
            error=f"HTTP {response.status_code}",
            note=STORE_LABEL,
            _meta=meta,
        )

    candidates = _parse_cards(response.text)
    if not candidates:
        return ResultPayload(status="NO_RESULTS", note="Spar", _meta=meta)

    # MANDATE: Keyword Search + Validation EAN
    for candidate in candidates:
        details = _fetch_product_details(session, candidate.url)
        details = details if isinstance(details, dict) else {}
        matched_ean = details.get("ean")
        
        # STRICT VALIDATION
        if matched_ean != EAN:
            continue
            
        price = _normalize_price(candidate.price_text or details.get("price"))
        product_title = candidate.title or details.get("name")
        brand = candidate.brand or details.get("brand")
        quantity = candidate.quantity or _guess_quantity(product_title)
        unit_price = candidate.unit_price or _strip_parentheses(details.get("unit_price"))
        payload_product = {
            "title": product_title,
            "brand": brand,
            "qty": quantity,
            "ean": matched_ean,
            "image_url": candidate.image,
            "source": "spar",
        }
        return ResultPayload(
            status="OK" if price else "NO_PRICE",
            price=price,
            unit_price=unit_price,
            quantity=quantity,
            title=product_title,
            url=candidate.url,
            note=STORE_LABEL,
            store=STORE_LABEL,
            matched_ean=matched_ean,
            image=candidate.image,
            product=payload_product,
            _meta=meta,
        )

    return ResultPayload(
        status="NO_MATCH",
        note="Spar",
        _meta={**meta, "candidates": len(candidates)},
    )


def main() -> int:
    result = fetch_spar()
    print(json.dumps(result.as_dict(), ensure_ascii=False))
    return 0 if result.status not in {"ERROR"} else 1


if __name__ == "__main__":
    sys.exit(main())
