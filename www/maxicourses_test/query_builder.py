#!/usr/bin/env python3
"""Query generation and validation built strictly from canonical seed terms."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from canonical_product import CanonicalProduct, _normalised_signature
from seed_terms_adapter import SeedTerms, from_canonical_product, from_descriptor
from store_profiles import STORE_PROFILES, StoreKey

CORE_STOPWORDS = {"aux", "au", "de", "du", "des", "la", "le", "les", "et", "en"}
CATEGORY_STOPWORDS = {"boisson", "boissons", "gazeuse", "gazeuses", "soda"}
SKU_PATTERN = re.compile(r"^[a-z]?\d{5,}$", re.IGNORECASE)


BRAND_NEGATIVE_HINTS: Dict[str, List[str]] = {
    "coca-cola": [
        "zero",
        "zéro",
        "sans sucre",
        "light",
        "cherry",
        "vanille",
        "caffeine",
        "caféine",
    ],
    "savora": ["douce", "bio", "x2", "lot", "format"],
}


@dataclass(frozen=True)
class QueryStage:
    label: str
    max_words: Optional[int]
    queries: Tuple[str, ...]
    negatives: Tuple[str, ...] = ()


def _normalize_query(value: str) -> str:
    return " ".join(value.strip().lower().split())


MONOPRIX_VARIANTS = ["nature", "vanille", "amande", "coco", "mangue", "chocolat", "orange", "sans sucre", "rouge"]


def seed_variant_negatives(variant: Optional[str]) -> Tuple[str, ...]:
    if not variant:
        return tuple()
    normalized = variant.strip().lower()
    if not normalized:
        return tuple()
    negatives: List[str] = []
    for token in MONOPRIX_VARIANTS:
        if token != normalized:
            negatives.append(token)
    if normalized == "orange":
        negatives.extend(["sans sucre", "sans sucres", "zero", "zéro", "rouge", "sanguine"])
    elif normalized in {"sans sucre", "zero", "zéro"}:
        negatives.extend(["orange", "original"])
    return tuple(dict.fromkeys(negatives))


def _dedupe(queries: Iterable[str], *, max_words: Optional[int]) -> Tuple[str, ...]:
    seen: set[str] = set()
    output: List[str] = []
    for raw in queries:
        query = _normalize_query(raw)
        if not query:
            continue
        if max_words is not None and len(query.split()) > max_words:
            continue
        if query in seen:
            continue
        seen.add(query)
        output.append(query)
    return tuple(output)


def _tokenize_text(value: Optional[str]) -> List[str]:
    if not isinstance(value, str):
        return []
    return value.replace("-", " ").split()


def _core_tokens(seed_terms: SeedTerms) -> List[str]:
    tokens = _tokenize_text(seed_terms.core)
    cleaned = [
        token
        for token in tokens
        if token
        and token.lower() not in CORE_STOPWORDS
        and token.lower() not in CATEGORY_STOPWORDS
        and token.lower() != (seed_terms.brand or "").lower()
    ]
    return cleaned


def _core_primary(seed_terms: SeedTerms) -> Optional[str]:
    tokens = _core_tokens(seed_terms)
    return tokens[0].lower() if tokens else None


def _size_tokens(seed_terms: SeedTerms) -> List[str]:
    tokens: List[str] = []
    if seed_terms.size_token:
        tokens.append(seed_terms.size_token)
    tokens.extend(seed_terms.size_aliases)
    seen: set[str] = set()
    unique: List[str] = []
    for token in tokens:
        if token and token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


def _is_liquid(seed_terms: SeedTerms) -> bool:
    for token in _size_tokens(seed_terms):
        if token.endswith(("l", "ml", "cl")):
            return True
    return False


def _combine(tokens: Sequence[Optional[str]]) -> str:
    filtered = [token for token in tokens if isinstance(token, str) and token.strip()]
    return " ".join(filtered)


def _brand_forms(brand: Optional[str]) -> List[str]:
    if not brand:
        return []
    base = brand.strip().lower()
    forms = [base]
    if "-" in base:
        forms.append(base.replace("-", " "))
    return list(dict.fromkeys(forms))


def _monoprix_plan(seed_terms: SeedTerms) -> List[QueryStage]:
    brand = seed_terms.brand
    core_primary = _core_primary(seed_terms)
    size_tokens = _size_tokens(seed_terms)
    pack_token = seed_terms.pack_token
    is_liquid = _is_liquid(seed_terms)
    variant_token = seed_terms.variant_tokens[0] if seed_terms.variant_tokens else None
    variant_negatives = seed_variant_negatives(variant_token)

    stages: List[QueryStage] = []

    q1_candidates: List[str] = []
    if brand and variant_token:
        q1_candidates.append(_combine([brand, variant_token]))
    if brand and core_primary:
        q1_candidates.append(_combine([brand, core_primary]))
    elif brand and pack_token:
        q1_candidates.append(_combine([brand, pack_token]))
    elif brand:
        q1_candidates.append(brand)
    q1 = _dedupe(q1_candidates, max_words=2)
    if q1:
        stages.append(QueryStage("Q1", 2, q1, variant_negatives))

    q2_candidates: List[str] = []
    if is_liquid and brand and size_tokens:
        for size in size_tokens:
            q2_candidates.append(_combine([brand, size]))
    elif not is_liquid and brand and pack_token:
        q2_candidates.append(_combine([brand, pack_token]))
    q2 = _dedupe(q2_candidates, max_words=2)
    if q2:
        stages.append(QueryStage("Q2", 2, q2))

    q3_candidates: List[str] = []
    if brand and variant_token and size_tokens:
        for size in size_tokens:
            q3_candidates.append(_combine([brand, variant_token, size]))
    if brand and core_primary and size_tokens:
        for size in size_tokens:
            q3_candidates.append(_combine([brand, core_primary, size]))
    elif brand and core_primary and pack_token:
        q3_candidates.append(_combine([brand, core_primary, pack_token]))
    q3 = _dedupe(q3_candidates, max_words=3)
    if q3:
        stages.append(QueryStage("Q3", 3, q3, variant_negatives))

    return stages


def _leclerc_plan(seed_terms: SeedTerms) -> List[QueryStage]:
    brand = seed_terms.brand
    core_primary = _core_primary(seed_terms)
    size_tokens = _size_tokens(seed_terms)
    pack_token = seed_terms.pack_token
    variant_primary = (
        seed_terms.variant_tokens[0] if seed_terms.variant_tokens else None
    )
    is_liquid = _is_liquid(seed_terms)

    stages: List[QueryStage] = []

    q1_candidates: List[str] = []
    if is_liquid and brand and core_primary and size_tokens:
        for size in size_tokens:
            q1_candidates.append(_combine([brand, core_primary, size]))
    elif brand and core_primary:
        q1_candidates.append(_combine([brand, core_primary]))
        if pack_token:
            q1_candidates.append(_combine([brand, core_primary, pack_token]))
    q1 = _dedupe(q1_candidates, max_words=3)
    if q1:
        stages.append(QueryStage("Q1", 3, q1))

    q2_candidates: List[str] = []
    if brand and size_tokens:
        for size in size_tokens:
            q2_candidates.append(_combine([brand, size]))
    elif brand and pack_token:
        q2_candidates.append(_combine([brand, pack_token]))
    q2 = _dedupe(q2_candidates, max_words=3)
    if q2:
        stages.append(QueryStage("Q2", 3, q2))

    q3_candidates: List[str] = []
    if brand and variant_primary:
        q3_candidates.append(_combine([brand, variant_primary]))
    q3 = _dedupe(q3_candidates, max_words=3)
    if q3:
        stages.append(QueryStage("Q3", 3, q3))

    return stages


def _intermarche_plan(seed_terms: SeedTerms) -> List[QueryStage]:
    brand = seed_terms.brand
    size_tokens = _size_tokens(seed_terms)
    variant_tokens = list(seed_terms.variant_tokens)
    core_primary = _core_primary(seed_terms)

    if not brand or not size_tokens:
        return []

    brand_forms = _brand_forms(brand)
    primary_size = size_tokens[0]

    q1_queries = [_combine([brand_form, primary_size]) for brand_form in brand_forms]
    q1 = _dedupe(q1_queries, max_words=None)

    q2: Tuple[str, ...] = tuple()
    if core_primary and core_primary not in seed_terms.variant_tokens:
        q2_queries = [
            _combine([brand_form, core_primary, primary_size])
            for brand_form in brand_forms
        ]
        q2 = _dedupe(q2_queries, max_words=None)

    q3: Tuple[str, ...] = tuple()
    if variant_tokens:
        variant_primary = variant_tokens[0]
        variant_brand_forms = [brand_forms[0]] if brand_forms else []
        q3_queries = [
            _combine([brand_form, variant_primary, primary_size])
            for brand_form in variant_brand_forms
        ]
        q3 = _dedupe(q3_queries, max_words=None)

    stages: List[QueryStage] = []
    if q1:
        stages.append(QueryStage("Q1", None, q1))
    if q2:
        stages.append(QueryStage("Q2", None, q2))
    if q3:
        stages.append(QueryStage("Q3", None, q3))
    return stages


def build_query_plan_from_descriptor(
    ean: str, descriptor: Optional[dict], store: StoreKey
) -> List[QueryStage]:
    seed_terms = from_descriptor(ean, descriptor)
    return _build_plan_for_seed_terms(seed_terms, store)


def _allowed_tokens(seed_terms: SeedTerms) -> Set[str]:
    allowed: Set[str] = set()
    if seed_terms.brand:
        brand_normalized = seed_terms.brand.strip().lower()
        allowed.add(brand_normalized)
        allowed.update(_tokenize_text(seed_terms.brand))
    if seed_terms.core:
        for token in _tokenize_text(seed_terms.core):
            token = token.lower()
            if (
                token
                and token not in CORE_STOPWORDS
                and token not in CATEGORY_STOPWORDS
            ):
                allowed.add(token)
    if seed_terms.size_token:
        allowed.add(seed_terms.size_token)
    allowed.update(seed_terms.size_aliases)
    if seed_terms.pack_token:
        allowed.add(seed_terms.pack_token)
    allowed.update(seed_terms.variant_tokens)
    return allowed


def _tokenize_query(query: str) -> List[str]:
    return query.lower().split()


def _validate_stage_queries(
    seed_terms: SeedTerms, stages: Sequence[QueryStage], store: StoreKey
) -> None:
    allowed_tokens = _allowed_tokens(seed_terms)
    for stage in stages:
        for query in stage.queries:
            tokens = _tokenize_query(query)
            forbidden = [
                token
                for token in tokens
                if SKU_PATTERN.match(token) or token in CATEGORY_STOPWORDS
            ]
            if forbidden:
                raise ValueError(
                    f"{store}: forbidden tokens {forbidden} detected in '{query}'"
                )
            unknown = [token for token in tokens if token not in allowed_tokens]
            if unknown:
                raise ValueError(
                    f"{store}: unknown canonical tokens {unknown} in '{query}'"
                )


def _build_plan_for_seed_terms(
    seed_terms: SeedTerms, store: StoreKey
) -> List[QueryStage]:
    store_lower = store.lower()
    if store_lower == "monoprix":
        plan = _monoprix_plan(seed_terms)
    elif store_lower in {"leclerc", "leclercdrive"}:
        plan = _leclerc_plan(seed_terms)
    elif store_lower == "intermarche":
        plan = _intermarche_plan(seed_terms)
    else:
        plan = []
    _validate_stage_queries(seed_terms, plan, store)
    return plan


def _ensure_requirements(product: CanonicalProduct, store: StoreKey) -> None:
    profile = STORE_PROFILES[store]
    for field in profile.get("required", []):
        if not getattr(product, field, None):
            raise ValueError(
                f"Canonical product missing required field '{field}' for store '{store}'"
            )


def _build_negative_tokens(product: CanonicalProduct, store: StoreKey) -> List[str]:
    profile = STORE_PROFILES[store]
    negatives: List[str] = []
    sources = profile.get("negatives_from") or []
    if not sources:
        sources = ["variant≠", "pack_count≠", "size≠", "flavor_color≠"]

    variant = (product.variant or "").lower()
    if "variant≠" in sources:
        variant_exclusions = {"sans sucre", "zero", "zéro", "light", "cherry", "vanille"}
        if variant:
            variant_exclusions.discard(variant)
            if variant and variant != "original":
                variant_exclusions.add("original")
        negatives.extend(variant_exclusions)

    if "pack_count≠" in sources and product.pack_count:
        negatives.extend(
            [
                str(product.pack_count + 1),
                str(max(1, product.pack_count - 1)),
                f"x{product.pack_count + 1}",
                f"x{max(1, product.pack_count - 1)}",
            ]
        )

    if "size≠" in sources and product.size_value and product.size_unit:
        try:
            negatives.append(f"{product.size_value + 0.5:g}{product.size_unit}")
            lower = max(0.5, product.size_value - 0.5)
            negatives.append(f"{lower:g}{product.size_unit}")
        except TypeError:
            pass

    if "flavor_color≠" in sources and product.flavor_color:
        flavor = product.flavor_color.lower()
        for candidate in {
            "orange",
            "citron",
            "cola",
            "cherry",
            "vanille",
            "pomme",
            "framboise",
        }:
            if candidate != flavor:
                negatives.append(candidate)

    negatives.extend(brand_negative_hints(product.brand))
    negatives.extend(profile.get("stopwords", []))
    seen: set[str] = set()
    unique = []
    for token in negatives:
        token = token.strip().lower()
        if token and token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


def generate_store_queries(
    product: CanonicalProduct,
    store: StoreKey,
    *,
    max_queries: int = 6,
    extra_negatives: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    """Generate positive and negative tokens for the given store."""
    _ensure_requirements(product, store)
    seed_terms = from_canonical_product(product)
    stages = _build_plan_for_seed_terms(seed_terms, store)
    queries: List[str] = []
    for stage in stages:
        for query in stage.queries:
            if query not in queries:
                queries.append(query)
            if len(queries) >= max_queries:
                break
        if len(queries) >= max_queries:
            break

    negatives = _build_negative_tokens(product, store)
    if extra_negatives:
        negatives.extend(extra_negatives)
    negatives = list(dict.fromkeys(negatives))
    return {"queries": queries, "negatives": negatives}


def brand_negative_hints(brand: Optional[str]) -> List[str]:
    if not isinstance(brand, str):
        return []
    normalized = brand.strip().lower()
    if not normalized:
        return []
    normalized = normalized.replace("’", "'").replace(" ", "-")
    return list(BRAND_NEGATIVE_HINTS.get(normalized, []))


__all__ = [
    "build_query_plan_from_descriptor",
    "generate_store_queries",
    "brand_negative_hints",
    "CATEGORY_STOPWORDS",
    "SKU_PATTERN",
]
