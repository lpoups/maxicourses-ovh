#!/usr/bin/env python3
"""Persist a single adapter result to the results/summary without running the full pipeline.

This is meant for manual fetch runs (ex: Leclerc) when we want the UI to reflect
the latest successful collect immediately. Typical usage:

    USE_CDP=1 HEADLESS=0 EAN=... QUERY="..." WRITE_RESULTS=1 \\
      python3 fetch_leclerc_drive_price.py

The fetcher can call :func:`ingest_adapter_result` directly; this module also
exposes a CLI that reads a JSON payload from stdin:

    python3 pipeline/ingest_adapter_result.py --ean 123 --adapter leclerc < payload.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from seed_catalog import all_seeds
from pipeline.models import PipelineRun, RawAdapterResult

# Load helpers from run_pipeline in "script" mode to avoid package import issues.
RUN_PIPELINE_PATH = Path(__file__).resolve().parent / "run_pipeline.py"
_spec = importlib.util.spec_from_file_location("pipeline_run_ingest", RUN_PIPELINE_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"Impossible de charger run_pipeline depuis {RUN_PIPELINE_PATH}")
_run_pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_run_pipeline)

DEFAULT_RESULTS_DIR = _run_pipeline.DEFAULT_RESULTS_DIR
PARIS_TZ = _run_pipeline.PARIS_TZ
export_dataset_snapshot = _run_pipeline.export_dataset_snapshot
save_run = _run_pipeline.save_run
update_summary = _run_pipeline.update_summary
ensure_results_dir = _run_pipeline.ensure_results_dir


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _reference_field(descriptor: Dict[str, Any], key: str, fallback_key: Optional[str] = None) -> Optional[str]:
    if not isinstance(descriptor, dict):
        return None
    primary = descriptor.get(key)
    if isinstance(primary, str) and primary.strip():
        return primary
    if fallback_key:
        secondary = descriptor.get(fallback_key)
        if isinstance(secondary, str) and secondary.strip():
            return secondary
    return None


def ingest_adapter_result(
    *,
    ean: str,
    adapter: str,
    payload: Dict[str, Any],
    status: Optional[str] = None,
    results_dir: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    command: Optional[list[str]] = None,
    descriptor: Optional[Dict[str, Any]] = None,
) -> PipelineRun:
    """Persist a single adapter payload as a PipelineRun and refresh summary/dataset."""

    descriptor = descriptor if isinstance(descriptor, dict) else all_seeds().get(ean, {}) or {}
    run_results_dir = Path(results_dir) if results_dir else DEFAULT_RESULTS_DIR
    ensure_results_dir(run_results_dir)

    now = datetime.now(PARIS_TZ)
    status_value = status or payload.get("status") or "UNKNOWN"

    ref_name = _reference_field(descriptor, "seed_primary_name", "name")
    ref_desc = descriptor.get("description")
    ref_brand = descriptor.get("brand")
    ref_qty = _reference_field(descriptor, "seed_primary_quantity", "quantity")
    ref_image = descriptor.get("image")
    ref_source = descriptor.get("source")

    raw = RawAdapterResult(
        adapter=adapter,
        status=status_value,
        payload=payload,
        started_at=now,
        finished_at=now,
        script_path=str(Path(command[0]).resolve()) if command else __file__,
        command=command or [],
        env=env or {},
        exit_code=0 if status_value.upper() in {"OK", "EQUIVALENT", "NO_PRICE"} else 1,
        stdout="",
        stderr=None,
        error=payload.get("error"),
        metadata={"auto_ingest": True},
    )

    run = PipelineRun(
        ean=ean,
        image_path=ref_image,
        started_at=now,
        finished_at=now,
        adapter_results=[raw],
        reference_title=ref_name,
        reference_description=ref_desc,
        reference_source=ref_source,
        reference_brand=ref_brand,
        reference_quantity=ref_qty,
        reference_image=ref_image,
        reference_categories=descriptor.get("categories"),
        reference_nutriscore_grade=descriptor.get("nutriscore_grade"),
        reference_nutriscore_score=_safe_int(descriptor.get("nutriscore_score")),
        reference_nutriscore_image=descriptor.get("nutriscore_image"),
        reference_ecoscore_grade=descriptor.get("ecoscore_grade"),
        reference_ecoscore_image=descriptor.get("ecoscore_image"),
        reference_nova_group=descriptor.get("nova_group"),
        finder=None,
    )

    update_summary(run, results_dir=run_results_dir)
    save_run(run, results_dir=run_results_dir)
    export_dataset_snapshot(run, results_dir=run_results_dir)
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description="Persist a single adapter result to results/summary.json")
    parser.add_argument("--ean", required=True, help="EAN concerné")
    parser.add_argument("--adapter", required=True, help="Nom de l'adaptateur (ex: leclerc)")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Répertoire results/ à mettre à jour")
    parser.add_argument("--payload-file", help="Chemin JSON à ingérer (sinon stdin)")
    args = parser.parse_args()

    if args.payload_file:
        payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    else:
        payload = json.load(sys.stdin)

    if not isinstance(payload, dict):
        raise SystemExit("Payload JSON invalide (dict attendu)")

    run = ingest_adapter_result(
        ean=args.ean.strip(),
        adapter=args.adapter.strip(),
        payload=payload,
        results_dir=args.results_dir,
        env={"EAN": args.ean.strip()},
        command=[sys.executable, __file__],
    )
    print(json.dumps(run.as_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
