"""AI helper stubs for Leclerc smart search.

This module centralises future IA calls. For the moment it only exposes
place‑holders so that the rest of the pipeline can import it without risk.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import os

# Feature flag : if absent/false the helpers short-circuit immediately.
USE_AI_ASSIST = os.getenv("USE_AI_ASSIST", "false").lower() in {"1", "true", "yes"}


def summarize_product_seed(seed_payloads: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Return an AI product profile derived from the seed payloads.

    For now returns a noop structure when AI assist is disabled.
    """
    if not USE_AI_ASSIST:
        return {
            "status": "disabled",
            "profile": None,
            "keywords": [],
        }
    raise NotImplementedError("AI summarisation not implemented yet")


def suggest_search_queries(ai_profile: Dict[str, Any]) -> List[str]:
    """Return a list of search queries tailored for Leclerc (≤ 40 chars each)."""
    if not USE_AI_ASSIST:
        return []
    raise NotImplementedError("AI query suggestion not implemented yet")


def score_leclerc_candidates(ai_profile: Dict[str, Any], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Score each Leclerc search candidate (MATCH / NO_MATCH).

    Expected output structure per candidate::
        {
            "status": "MATCH" | "NO_MATCH",
            "score": float,
            "justification": str,
        }
    """
    if not USE_AI_ASSIST:
        # Return NO_MATCH for every candidate so the current heuristic remains in place.
        return [
            {
                "status": "NO_MATCH",
                "score": 0.0,
                "justification": "AI assist disabled",
            }
            for _ in candidates
        ]
    raise NotImplementedError("AI candidate scoring not implemented yet")


def suggest_equivalent(
    ai_profile: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Optionally suggest an equivalent product when the exact one is absent."""
    if not USE_AI_ASSIST:
        return None
    raise NotImplementedError("AI equivalent suggestion not implemented yet")

