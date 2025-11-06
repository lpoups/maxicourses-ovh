#!/usr/bin/env python3
"""Fetcher G20 Minute (collecte simple via la page de recherche)."""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import urljoin

import requests

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    BeautifulSoup = None  # type: ignore


EAN = os.environ.get("EAN", "").strip()
QUERY = os.environ.get("QUERY", "").strip()
PROXY = os.environ.get("PROXY")

BASE_URL = os.environ.get("G20_BASE_URL", "https://www.g20-minute.com")
SEARCH_TEMPLATE = os.environ.get(
    "G20_SEARCH_TEMPLATE",
    "https://www.g20-minute.com/search/{ean}",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Connection": "keep-alive",
}


@dataclass
class Result:
    status: str
    price: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    note: Optional[str] = None
    unit_price: Optional[str] = None
    quantity: Optional[str] = None
    matched_ean: Optional[str] = None
    image: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


def _normalize_price(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = text.replace("\xa0", " ").strip()
    match = re.search(r"(\d+[.,]\d+)", cleaned)
    if not match:
        return None
    value = match.group(1).replace(".", ",")
    if "," not in value:
        value = f"{value},00"
    return value


def _normalize_unit(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return text.replace("\xa0", " ").replace(".", ",").strip()


def _build_search_url(term: str) -> str:
    template = SEARCH_TEMPLATE or "{ean}"
    try:
        return template.format(ean=term, query=term)
    except KeyError:
        return template.replace("{ean}", term).replace("{query}", term)


def _select_fragment(html: str, ean: str) -> Optional[str]:
    pattern = re.compile(
        rf'<div id="product-{re.escape(ean)}" class="item[^"]*">(.*?)<div class="item-actions"',
        re.S,
    )
    match = pattern.search(html)
    if match:
        return match.group(1)
    # Fallback: take first product block
    fallback = re.search(r'<div id="product-\d{13}" class="item[^"]*">(.*?)<div class="item-actions"', html, re.S)
    return fallback.group(1) if fallback else None


def _parse_with_bs4(html: str, ean: str) -> Optional[Result]:
    if BeautifulSoup is None:
        return None
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one(f"#product-{ean}") if ean else None
    if container is None:
        container = soup.select_one("#products .item")
    if container is None:
        return None

    def text_or_none(selector: str) -> Optional[str]:
        node = container.select_one(selector)
        return node.get_text(strip=True) if node else None

    title = text_or_none(".item-name")
    link_node = container.select_one(".item-name")
    href = link_node["href"] if link_node and link_node.has_attr("href") else None
    price_text = text_or_none(".item-price .price")
    attrs = [li.get_text(" ", strip=True) for li in container.select(".product-attrs li")]
    quantity = attrs[0] if attrs else None
    unit_price = None
    for attr in attrs[1:]:
        if "€" in attr:
            unit_price = attr
            break
    image_node = container.select_one(".item-img img")
    image = None
    if image_node and image_node.has_attr("src"):
        image = urljoin(BASE_URL, image_node["src"])

    result = Result(
        status="OK" if price_text else "NO_PRICE",
        price=_normalize_price(price_text),
        title=title,
        url=urljoin(BASE_URL, href) if href else None,
        note="G20 Minute",
        unit_price=_normalize_unit(unit_price),
        quantity=_normalize_unit(quantity),
        matched_ean=ean or None,
        image=image,
    )
    if result.status == "NO_PRICE":
        result.price = None
    return result


def _parse_with_regex(html: str, ean: str) -> Optional[Result]:
    fragment = _select_fragment(html, ean)
    if fragment is None:
        return None

    def match_text(pattern: str) -> Optional[str]:
        m = re.search(pattern, fragment, re.S)
        return m.group(1).strip() if m else None

    title = match_text(r'class="item-name">\s*([^<]+)\s*')
    href = match_text(r'<a href="([^"]+)" class="item-name">')
    price_text = match_text(r'class="item-price[^"]*">\s*<p class="price">([^<]+)</p>')
    attrs = re.findall(r'<li class="product-attr">\s*([^<]+)\s*</li>', fragment)
    quantity = attrs[0].strip() if attrs else None
    unit_price = None
    for attr in attrs[1:]:
        if "€" in attr:
            unit_price = attr.strip()
            break
    image = match_text(r'<img src="([^"]+)"')

    result = Result(
        status="OK" if price_text else "NO_PRICE",
        price=_normalize_price(price_text),
        title=title,
        url=urljoin(BASE_URL, href) if href else None,
        note="G20 Minute",
        unit_price=_normalize_unit(unit_price),
        quantity=_normalize_unit(quantity),
        matched_ean=ean or None,
        image=urljoin(BASE_URL, image) if image else None,
    )
    if result.status == "NO_PRICE":
        result.price = None
    return result


def fetch_g20(ean: str, query: str) -> Result:
    term = ean or query
    if not term:
        return Result(status="ERROR", note="EAN ou requête manquants")

    search_url = _build_search_url(term)
    session = requests.Session()
    session.headers.update(HEADERS)
    if PROXY:
        session.proxies.update({"http": PROXY, "https": PROXY})

    try:
        response = session.get(search_url, timeout=30)
    except requests.RequestException as exc:
        return Result(status="ERROR", note=f"Requête échouée: {exc}")

    if response.status_code == 404:
        return Result(status="NO_RESULTS", note="Page 404 G20")
    if response.status_code >= 500:
        return Result(status="ERROR", note=f"HTTP {response.status_code}")

    html = response.text
    parser_result = _parse_with_bs4(html, ean)
    if parser_result is None:
        parser_result = _parse_with_regex(html, ean)
    if parser_result is None:
        return Result(status="NO_RESULTS", note="G20 Minute")

    # Ensure status/message coherence
    if parser_result.status == "OK" and not parser_result.price:
        parser_result.status = "NO_PRICE"
    if not parser_result.note:
        parser_result.note = "G20 Minute"

    return parser_result


def main() -> int:
    result = fetch_g20(EAN, QUERY)
    print(json.dumps(result.as_dict(), ensure_ascii=False))
    return 0 if result.status not in {"ERROR"} else 1


if __name__ == "__main__":
    sys.exit(main())
