"""Minimal canonical product builder used by query and descriptor tooling.

This module reimplements the helper that existed before the repo reset.  It
normalises the descriptors harvested during the seed phase so that every store
can derive consistent tokens (brand, cœur de nom, taille, pack, etc.).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class CanonicalProduct:
    ean: str
    brand: Optional[str]
    line: Optional[str]
    name_core: Optional[str]
    variant: Optional[str]
    form: Optional[str]
    pack_count: Optional[int]
    size_value: Optional[float]
    size_unit: Optional[str]
    flavor_color: Optional[str]
    features: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    normalized_signature: str = ""


SIZE_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|cl|l|g|kg)\b", re.IGNORECASE)
PACK_PATTERN = re.compile(r"\b(\d+)\s*(?:x|×)\s*(\d*)", re.IGNORECASE)
FLAVOR_TOKENS = {
    "orange",
    "citron",
    "citron vert",
    "cola",
    "vanille",
    "framboise",
    "pomme",
}


def _first(values: Iterable[str]) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_size(texts: Iterable[str]) -> tuple[Optional[float], Optional[str]]:
    for text in texts:
        if not isinstance(text, str):
            continue
        match = SIZE_PATTERN.search(text.replace("·", " ").replace("℮", ""))
        if match:
            value = float(match.group(1).replace(",", "."))
            unit = match.group(2).lower()
            return value, unit
    return None, None


def _parse_pack(texts: Iterable[str]) -> Optional[int]:
    for text in texts:
        if not isinstance(text, str):
            continue
        match = PACK_PATTERN.search(text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def _detect_flavor(texts: Iterable[str]) -> Optional[str]:
    haystack = " ".join(t.lower() for t in texts if isinstance(t, str))
    for flavor in FLAVOR_TOKENS:
        if flavor in haystack:
            return flavor
    return None


def _normalised_signature(*parts: Optional[str]) -> str:
    tokens: List[str] = []
    for part in parts:
        if isinstance(part, str) and part.strip():
            normalized = re.sub(r"\s+", " ", part.strip().lower())
            tokens.append(normalized)
    return " ".join(tokens)


def build_canonical_product(
    descriptor: Dict[str, Any],
    seed_results: Optional[Dict[str, Any]] = None,
    *,
    ean: Optional[str] = None,
) -> CanonicalProduct:
    brand = descriptor.get("brand") or None
    if brand:
        brand = brand.strip()

    name_core = _first(
        (
            descriptor.get("name"),
            descriptor.get("title"),
            descriptor.get("seed_primary_name"),
            descriptor.get("description"),
        )
    )

    quantity = descriptor.get("quantity") or descriptor.get("seed_primary_quantity")
    size_value, size_unit = _parse_size(
        filter(
            None,
            [
                descriptor.get("quantity"),
                descriptor.get("seed_primary_quantity"),
                name_core,
            ],
        )
    )
    pack_count = _parse_pack(
        filter(None, [descriptor.get("name"), descriptor.get("description")])
    )

    flavor_color = _detect_flavor(
        filter(
            None,
            [
                descriptor.get("name"),
                descriptor.get("description"),
                descriptor.get("categories"),
            ],
        )
    )

    images: List[str] = []
    image_field = descriptor.get("image")
    if isinstance(image_field, str) and image_field.strip():
        images.append(image_field.strip())
    descriptor_images = descriptor.get("images")
    if isinstance(descriptor_images, list):
        for item in descriptor_images:
            if isinstance(item, str) and item.strip():
                images.append(item.strip())

    signature = _normalised_signature(
        ean or descriptor.get("ean"),
        brand or "",
        name_core or "",
        flavor_color or "",
        f"{size_value:g}{size_unit}" if size_value and size_unit else "",
    )

    return CanonicalProduct(
        ean=ean or descriptor.get("ean") or "",
        brand=brand,
        line=descriptor.get("line"),
        name_core=name_core,
        variant=descriptor.get("variant"),
        form=descriptor.get("form"),
        pack_count=pack_count,
        size_value=size_value,
        size_unit=size_unit,
        flavor_color=flavor_color,
        features=[],
        images=images,
        normalized_signature=signature,
    )


def canonical_product_as_dict(product: CanonicalProduct) -> Dict[str, Any]:
    return asdict(product)


__all__ = [
    "CanonicalProduct",
    "build_canonical_product",
    "canonical_product_as_dict",
    "_normalised_signature",
]

