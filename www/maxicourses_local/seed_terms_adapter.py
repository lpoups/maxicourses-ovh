"""Adapters that transform canonical products or raw descriptors into token sets
used by :mod:`query_builder`."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from canonical_product import CanonicalProduct, build_canonical_product


@dataclass(frozen=True)
class SeedTerms:
    ean: str
    brand: Optional[str]
    core: str
    size_token: Optional[str]
    size_aliases: List[str]
    pack_token: Optional[str]
    variant_tokens: List[str]


def _size_aliases(value: Optional[float], unit: Optional[str]) -> List[str]:
    if not value or not unit:
        return []
    unit = unit.lower()
    raw = f"{value:g}{unit}"
    aliases = {raw}
    if unit == "l":
        aliases.add(f"{int(value * 100):d}cl")
        aliases.add(f"{int(value * 1000):d}ml")
    if "," not in raw and unit in {"l", "g"}:
        aliases.add(raw.replace(".", ","))
    return list(aliases)


def _pack_token(count: Optional[int]) -> Optional[str]:
    if not count or count <= 1:
        return None
    return f"x{count}"


def from_canonical_product(product: CanonicalProduct) -> SeedTerms:
    size_token = None
    if product.size_value and product.size_unit:
        size_token = f"{product.size_value:g}{product.size_unit.lower()}"
    aliases = _size_aliases(product.size_value, product.size_unit)
    pack_token = _pack_token(product.pack_count)

    variant_tokens: List[str] = []
    if product.variant:
        variant_tokens.extend(product.variant.lower().split())
    if product.flavor_color:
        variant_tokens.append(product.flavor_color.lower())

    core = product.name_core or ""
    return SeedTerms(
        ean=product.ean,
        brand=product.brand.lower() if product.brand else None,
        core=core,
        size_token=size_token,
        size_aliases=aliases,
        pack_token=pack_token,
        variant_tokens=list(dict.fromkeys(t for t in variant_tokens if t)),
    )


def from_descriptor(ean: str, descriptor: Optional[Dict[str, object]]) -> SeedTerms:
    product = build_canonical_product(descriptor or {}, None, ean=ean)
    return from_canonical_product(product)

