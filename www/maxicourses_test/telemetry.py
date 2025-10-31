"""Lightweight telemetry helper used by the Intermarché fetcher.

Writes JSONL events to ``maxicourses_test/logs/telemetry.jsonl`` with a tiny
5×5 MB rotation, matching the schema described in ``docs/ONBOARDING.md``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_PATH = LOG_DIR / "telemetry.jsonl"
MAX_BYTES = 5 * 1024 * 1024
MAX_ROTATIONS = 5

StageLiteral = Literal["Q0", "Q1", "Q2", "Q3", "Q4", "fallback", "memory"]


def _timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _rotate_logs() -> None:
    if not LOG_PATH.exists():
        return
    if LOG_PATH.stat().st_size < MAX_BYTES:
        return
    highest = LOG_DIR / f"telemetry.jsonl.{MAX_ROTATIONS - 1}"
    highest.unlink(missing_ok=True)
    for idx in range(MAX_ROTATIONS - 1, 0, -1):
        target = LOG_DIR / f"telemetry.jsonl.{idx}"
        source = LOG_DIR / ("telemetry.jsonl" if idx == 1 else f"telemetry.jsonl.{idx-1}")
        if source.exists():
            source.rename(target)


def _write_event(payload: Dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_logs()
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        pass


def log_event(event: Dict[str, Any]) -> None:
    payload = dict(event)
    payload.setdefault("ts", _timestamp())
    _write_event(payload)


def log_search_attempt(
    *,
    store: str,
    ean: Optional[str],
    query: Optional[str],
    stage: Optional[StageLiteral],
    results_count: Optional[int],
    search_url: Optional[str],
    filters: Optional[Dict[str, Any]] = None,
) -> None:
    log_event(
        {
            "status": "search_attempt",
            "ts": _timestamp(),
            "store": store,
            "ean": ean,
            "query": query,
            "stage": stage,
            "results_count": results_count,
            "search_url": search_url,
            "filters": filters or {},
        }
    )


def log_candidate_scored(
    *,
    store: str,
    ean: Optional[str],
    query: Optional[str],
    stage: Optional[StageLiteral],
    url: Optional[str],
    title: Optional[str],
    match_status: Optional[str],
    reason: Optional[str],
    search_url: Optional[str] = None,
) -> None:
    log_event(
        {
            "status": "candidate_scored",
            "ts": _timestamp(),
            "store": store,
            "ean": ean,
            "query": query,
            "stage": stage,
            "url": url,
            "title": title,
            "match_status": match_status,
            "reason": reason,
            "search_url": search_url,
        }
    )


def log_hit_accepted(
    *,
    store: str,
    ean: Optional[str],
    query: Optional[str],
    stage: Optional[StageLiteral],
    url: Optional[str],
    title: Optional[str],
    match_status: Optional[str],
    reason: Optional[str],
    comparison_basis: Optional[str] = None,
    unit_price: Optional[float] = None,
    ai: Optional[Dict[str, Any]] = None,
) -> None:
    log_event(
        {
            "status": "hit_accepted",
            "ts": _timestamp(),
            "store": store,
            "ean": ean,
            "query": query,
            "stage": stage,
            "url": url,
            "title": title,
            "match_status": match_status,
            "reasons": [reason] if reason else [],
            "comparison_basis": comparison_basis,
            "unit_price": unit_price,
            "ai": ai or {},
        }
    )


def log_hit_rejected(
    *,
    store: str,
    ean: Optional[str],
    query: Optional[str],
    stage: Optional[StageLiteral],
    url: Optional[str],
    title: Optional[str],
    match_status: Optional[str],
    reason: Optional[str],
) -> None:
    log_event(
        {
            "status": "hit_rejected",
            "ts": _timestamp(),
            "store": store,
            "ean": ean,
            "query": query,
            "stage": stage,
            "url": url,
            "title": title,
            "match_status": match_status,
            "reasons": [reason] if reason else [],
        }
    )
