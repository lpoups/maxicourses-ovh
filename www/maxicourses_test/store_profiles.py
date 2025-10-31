"""Declarative store profiles for query generation."""
from __future__ import annotations

from typing import Dict, Literal, TypedDict

StoreKey = Literal["monoprix", "leclerc", "leclercdrive", "intermarche"]


class StoreProfile(TypedDict, total=False):
    max_terms: int
    required: list[str]
    negatives_from: list[str]
    stopwords: list[str]


STORE_PROFILES: Dict[StoreKey, StoreProfile] = {
    "monoprix": {
        "max_terms": 3,
        "required": ["brand", "name_core", "size_value"],
        "negatives_from": ["variant≠", "size≠", "pack_count≠", "flavor_color≠"],
        "stopwords": ["promo", "lot", "maxi", "format", "eco"],
    },
    "leclerc": {
        "max_terms": 3,
        "required": ["brand", "name_core"],
        "negatives_from": ["variant≠", "size≠", "pack_count≠"],
        "stopwords": ["lot", "duo", "family", "ecopack"],
    },
    "leclercdrive": {
        "max_terms": 3,
        "required": ["brand", "name_core"],
        "negatives_from": ["variant≠", "size≠", "pack_count≠"],
        "stopwords": ["lot", "duo", "family", "ecopack"],
    },
    "intermarche": {
        "required": ["brand", "size_value"],
        "negatives_from": ["variant≠", "size≠", "flavor_color≠"],
        "stopwords": ["promo", "lot", "x2", "x3", "mega"],
    },
}

