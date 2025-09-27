#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parent
MANUAL_DESCRIPTOR_PATH = ROOT / "manual_descriptors.json"
PIPELINE_SCRIPT = ROOT / "pipeline" / "run_pipeline.py"


def load_manual_descriptor(ean: str) -> Dict[str, Any]:
    if not MANUAL_DESCRIPTOR_PATH.exists():
        return {}
    try:
        data = json.loads(MANUAL_DESCRIPTOR_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entry = data.get(ean)
    if not isinstance(entry, dict):
        return {}
    payload = dict(entry)
    payload.setdefault("ean", ean)
    payload.setdefault("source", "manual")
    return payload


def ensure_manual_descriptor(ean: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if MANUAL_DESCRIPTOR_PATH.exists():
        try:
            data = json.loads(MANUAL_DESCRIPTOR_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}

    entry = data.get(ean)
    if not isinstance(entry, dict):
        timestamp = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        entry = {
            "ean": ean,
            "brand": "",
            "name": f"Produit {ean}",
            "quantity": "",
            "categories": "",
            "image": None,
            "source": "auto",
            "description": "Entrée générée automatiquement lors d'une collecte.",
            "note": f"Stub créé automatiquement le {timestamp}"
        }
        data[ean] = entry
        try:
            MANUAL_DESCRIPTOR_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
    payload = dict(entry)
    payload.setdefault("ean", ean)
    payload.setdefault("source", "auto")
    return payload


def build_seed_query(ean: str, descriptor: Dict[str, Any]) -> str:
    brand = (descriptor.get("brand") or "").strip()
    name = (descriptor.get("name") or descriptor.get("title") or "").strip()
    quantity = (descriptor.get("quantity") or "").strip()
    parts = [part for part in (brand, name, quantity) if part]
    if parts:
        return " ".join(parts)
    return ean


def results_dir_for(ean: str) -> Path:
    return ROOT / "results" / f"test-{ean}"


def run_pipeline_collect(
    *,
    ean: str,
    headed: bool = True,
    adapters: Optional[list[str]] = None,
    proxy: Optional[str] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    if not PIPELINE_SCRIPT.exists():
        raise RuntimeError("pipeline/run_pipeline.py introuvable")

    cmd = [
        sys.executable,
        str(PIPELINE_SCRIPT),
        "--ean",
        ean,
        "--results-dir",
        str(results_dir_for(ean)),
    ]
    if headed:
        cmd.append("--headed")
    if adapters:
        cmd.extend(["--adapters", *adapters])
    if proxy:
        cmd.extend(["--proxy", proxy])

    env = os.environ.copy()
    env.setdefault("USE_CDP", "1")
    if extra_env:
        env.update(extra_env)

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60 * 8,
    )
    return proc


app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    return response


@app.route("/api/collect", methods=["OPTIONS"])
def api_collect_options():
    return ('', 204)


@app.post("/api/collect")
def api_collect():
    payload = request.get_json(silent=True) or {}
    ean = (payload.get("ean") or request.args.get("ean") or "").strip()
    if not ean:
        return jsonify({"error": "ean_requis"}), 400

    descriptor = load_manual_descriptor(ean)
    if not descriptor:
        descriptor = ensure_manual_descriptor(ean)

    headed = bool(payload.get("headed", True))
    adapters = payload.get("adapters")
    if adapters and not isinstance(adapters, list):
        adapters = None
    proxy = payload.get("proxy") or request.args.get("proxy")

    extra_env: Dict[str, str] = {}
    for key in ("CDP_URL", "LECLERC_DRIVE_URL", "CHRONODRIVE_STORE_URL"):
        value = payload.get(key) or request.args.get(key.lower())
        if value:
            extra_env[key] = value

    proc = run_pipeline_collect(
        ean=ean,
        headed=headed,
        adapters=adapters,
        proxy=proxy,
        extra_env=extra_env or None,
    )

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    if proc.returncode != 0:
        return (
            jsonify(
                {
                    "error": "pipeline_failed",
                    "exit_code": proc.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                }
            ),
            500,
        )

    latest_path = results_dir_for(ean) / "latest.json"
    summary_path = results_dir_for(ean) / "summary.json"
    if not latest_path.exists():
        return (
            jsonify(
                {
                    "error": "missing_results",
                    "message": f"latest.json introuvable dans {latest_path.parent}",
                    "stdout": stdout,
                    "stderr": stderr,
                }
            ),
            500,
        )

    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    summary: Optional[Dict[str, Any]] = None
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            summary = None

    return jsonify(
        {
            "status": "OK",
            "ean": ean,
            "descriptor": descriptor,
            "query": build_seed_query(ean, descriptor),
            "latest": latest,
            "summary": summary.get(ean) if isinstance(summary, dict) else None,
            "stdout": stdout,
        }
    )


@app.get("/")
def home():
    return "MaxiCourses API: POST /api/collect {ean: ...}"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
