#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from flask import Flask, jsonify, request

from decode_ean import decode_image_to_ean
from descriptor_store import (
    all_descriptors as descriptor_catalog,
    descriptor_exists,
    get_descriptor as load_descriptor_from_store,
    removed_eans,
    set_removed_flag,
)

ROOT = Path(__file__).resolve().parent
PIPELINE_SCRIPT = ROOT / "pipeline" / "run_pipeline.py"
GLOBAL_SUMMARY_PATH = ROOT / "results" / "summary.json"
OPENFOODFACTS_ENDPOINT = "https://world.openfoodfacts.org/api/v2/product/{ean}.json"
OFF_TIMEOUT_SECONDS = 10
EAN_REQUIRED_LENGTH = 13
UPLOADS_DIR = ROOT.parent / "uploads_ean"

STOPWORDS = {
    "a",
    "au",
    "aux",
    "avec",
    "base",
    "de",
    "des",
    "du",
    "et",
    "la",
    "le",
    "les",
    "pour",
    "sur",
}


def _clean_string(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _to_ascii_lower(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.lower()


def fetch_openfoodfacts_descriptor(ean: str) -> Optional[Dict[str, Any]]:
    """Best-effort retrieval of brand/name/quantity via OpenFoodFacts."""
    url = OPENFOODFACTS_ENDPOINT.format(ean=ean)
    try:
        with urlopen(url, timeout=OFF_TIMEOUT_SECONDS) as response:
            data = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None

    product = data.get("product") if isinstance(data, dict) else None
    if not isinstance(product, dict):
        return None

    brand = _clean_string(product.get("brands"))
    if brand:
        # Keep only the first brand in the comma-separated list.
        brand = brand.split(",")[0].strip()

    grade = _clean_string(product.get("nutriscore_grade")).lower()
    eco_grade = _clean_string(product.get("ecoscore_grade")).lower()
    nova_group = product.get("nova_group")
    if nova_group is not None:
        try:
            nova_group = str(int(nova_group)).strip()
        except (ValueError, TypeError):
            nova_group = str(nova_group).strip() or None

    descriptor = {
        "ean": ean,
        "brand": brand,
        "name": _clean_string(product.get("product_name")),
        "quantity": _clean_string(product.get("quantity")),
        "categories": _clean_string(product.get("categories")),
        "nutriscore_grade": grade or None,
        "nutriscore_image": f"https://static.openfoodfacts.org/images/attributes/nutriscore-{grade}.svg"
        if grade
        else None,
        "ecoscore_grade": eco_grade or None,
        "ecoscore_image": f"https://static.openfoodfacts.org/images/attributes/ecoscore-{eco_grade}.svg"
        if eco_grade in {"a", "b", "c", "d", "e"}
        else None,
        "nova_group": nova_group,
        "source": "openfoodfacts",
        "note": f"Descriptor importé depuis OpenFoodFacts le {datetime.utcnow().replace(microsecond=0).isoformat()}Z",
    }

    # Remove keys that are still empty strings to avoid polluting manual descriptors.
    cleaned: Dict[str, Any] = {"ean": ean, "source": descriptor["source"], "note": descriptor["note"]}
    for key in (
        "brand",
        "name",
        "quantity",
        "categories",
        "nutriscore_grade",
        "nutriscore_image",
        "ecoscore_grade",
        "ecoscore_image",
        "nova_group",
    ):
        value = descriptor.get(key)
        if isinstance(value, str):
            value = value.strip()
        if value:
            cleaned[key] = value

    if len(cleaned) <= 3:  # only metadata, no useful descriptive fields
        return None
    return cleaned


GENERIC_CONTAINERS = {
    "bouteille",
    "pack",
    "packs",
    "lot",
    "lot(s)",
    "sachet",
    "sachets",
    "boite",
    "boîte",
    "boites",
    "boîtes",
    "paquet",
    "paquets",
    "flacon",
    "flacons",
}


def _normalize_quantity(quantity: str) -> str:
    cleaned = _clean_string(quantity)
    if not cleaned:
        return ""
    tokens = cleaned.replace("℮", "").replace("·", " ").split()
    filtered = [token for token in tokens if token.lower() not in GENERIC_CONTAINERS]
    normalized = " ".join(filtered).strip()
    if not normalized:
        return ""
    normalized = normalized.replace(",", ".")
    return normalized


def _tokenize_for_query(value: str, seen: Set[str]) -> list[str]:
    ascii_lower = _to_ascii_lower(value)
    ascii_lower = ascii_lower.replace(",", ".")
    raw_tokens = re.split(r"[^0-9a-z\.]+", ascii_lower)
    tokens: list[str] = []
    for token in raw_tokens:
        token = token.strip().strip('.')
        if not token:
            continue
        if token in STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def merge_descriptor_fields(base: Dict[str, Any], updates: Dict[str, Any]) -> bool:
    """Merge non-empty fields from updates into base; return True if something changed."""
    changed = False
    for key, value in updates.items():
        if key == "ean":
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if base.get(key):
            continue
        base[key] = value
        changed = True
    return changed


def load_manual_descriptor(ean: str) -> Dict[str, Any]:
    descriptor = load_descriptor_from_store(ean)
    descriptor.setdefault("ean", ean)
    return descriptor


def ensure_manual_descriptor(ean: str) -> Dict[str, Any]:
    entry = load_manual_descriptor(ean)
    entry.setdefault("ean", ean)
    entry.setdefault("source", entry.get("source") or ("seed" if descriptor_exists(ean) else "auto"))

    off_updates = fetch_openfoodfacts_descriptor(ean)
    if off_updates:
        if merge_descriptor_fields(entry, off_updates):
            entry.setdefault("note", off_updates.get("note"))
            entry["source"] = off_updates.get("source", entry.get("source"))

    if not entry.get("name"):
        entry.setdefault(
            "note",
            "Stub incomplet – lancer une collecte seed Carrefour/Auchan pour remplir le descriptif.",
        )
        entry.setdefault("description", entry.get("description") or "Entrée générée automatiquement – descriptif requis.")

    entry.setdefault("brand", entry.get("brand") or "")
    entry.setdefault("name", entry.get("name") or entry.get("title") or "")
    entry.setdefault("quantity", entry.get("quantity") or "")
    entry.setdefault("categories", entry.get("categories") or "")
    entry.setdefault("image", entry.get("image"))
    entry.setdefault("nutriscore_grade", entry.get("nutriscore_grade"))
    entry.setdefault("nutriscore_image", entry.get("nutriscore_image"))
    entry.setdefault("ecoscore_grade", entry.get("ecoscore_grade"))
    entry.setdefault("ecoscore_image", entry.get("ecoscore_image"))
    entry.setdefault("nova_group", entry.get("nova_group"))
    entry["removed"] = bool(entry.get("removed"))
    entry.setdefault("source", entry.get("source") or "auto")
    entry.setdefault("note", entry.get("note") or "")
    entry.setdefault("description", entry.get("description") or "")
    return dict(entry)


def decode_image_ean(image_path: str) -> Optional[str]:
    try:
        result = decode_image_to_ean(image_path)
        if not result:
            print(f"[decode_image_ean] unable to decode {image_path}", file=sys.stderr)
        return result
    except Exception:
        return None


def build_seed_query(ean: str, descriptor: Dict[str, Any]) -> str:
    manual_seed = descriptor.get("seed_query")
    if isinstance(manual_seed, str) and manual_seed.strip():
        tokens = []
        seen: Set[str] = set()
        for token in _tokenize_for_query(manual_seed, seen):
            tokens.append(token)
        if tokens:
            return " ".join(tokens)

    brand = descriptor.get("brand") or ""
    name = descriptor.get("name") or descriptor.get("title") or ""
    quantity = _normalize_quantity(descriptor.get("quantity") or "")

    tokens: list[str] = []
    seen: Set[str] = set()

    for fragment in (brand, name, quantity):
        if not fragment:
            continue
        tokens.extend(_tokenize_for_query(fragment, seen))

    if tokens:
        return " ".join(tokens)
    return ean


def results_dir_for(ean: str) -> Path:
    return ROOT / "results" / f"test-{ean}"


def purge_results(ean: str) -> None:
    dataset_dir = results_dir_for(ean)
    if dataset_dir.exists():
        try:
            shutil.rmtree(dataset_dir)
        except Exception:
            pass
    results_root = ROOT / "results"
    if results_root.exists():
        for run_file in results_root.glob(f"run-{ean}-*.json"):
            try:
                run_file.unlink()
            except Exception:
                pass
    remove_global_summary_entry(ean)


def load_global_summary() -> Dict[str, Any]:
    if not GLOBAL_SUMMARY_PATH.exists():
        return {}
    try:
        data = json.loads(GLOBAL_SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def upsert_global_summary(ean: str, entry: Optional[Dict[str, Any]]) -> None:
    if not ean or not isinstance(entry, dict):
        return
    summary = load_global_summary()
    summary[ean] = entry
    try:
        GLOBAL_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def remove_global_summary_entry(ean: str) -> None:
    summary = load_global_summary()
    if ean in summary:
        summary.pop(ean, None)
        try:
            GLOBAL_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def set_descriptor_removed_flag(ean: str, removed: bool) -> Dict[str, Any]:
    set_removed_flag(ean, removed)
    payload = ensure_manual_descriptor(ean)
    payload["removed"] = bool(removed)
    return payload


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


@app.get("/api/descriptors")
def api_descriptors():
    ean = _clean_string(request.args.get("ean"))
    if ean:
        descriptor = ensure_manual_descriptor(ean)
        return jsonify({"status": "OK", "descriptor": descriptor})
    descriptors = descriptor_catalog()
    return jsonify({"status": "OK", "descriptors": descriptors, "removed": sorted(removed_eans())})


@app.post("/api/collect")
def api_collect():
    image_mode = False

    stored_path: Optional[Path] = None

    if request.content_type and 'multipart/form-data' in request.content_type:
        file_storage = request.files.get('image')
        if not file_storage or not file_storage.filename:
            return jsonify({"error": "image_requise"}), 400

        try:
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            return jsonify({"error": "uploads_dir_unavailable"}), 500

        original_name = Path(file_storage.filename).name or "upload"
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", original_name).strip("._") or "upload"
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        unique_name = f"{timestamp}_{uuid.uuid4().hex}_{safe_name}"
        stored_path = UPLOADS_DIR / unique_name

        try:
            file_storage.save(stored_path)
        except Exception:
            return jsonify({"error": "image_save_failed"}), 500

        decoded = decode_image_ean(str(stored_path))
        if not decoded:
            return jsonify({"error": "image_ean_decode_fail", "uploaded_path": str(stored_path)}), 400

        ean = re.sub(r"\D", "", decoded)
        if len(ean) != EAN_REQUIRED_LENGTH:
            return (
                jsonify(
                    {
                        "error": "ean_format_invalid",
                        "message": f"EAN doivent contenir {EAN_REQUIRED_LENGTH} chiffres (reçu: {decoded.strip()})",
                        "uploaded_path": str(stored_path),
                    }
                ),
                400,
            )
        image_mode = True
        payload = {}
    else:
        payload = request.get_json(silent=True) or {}
        raw_ean = (payload.get("ean") or request.args.get("ean") or "").strip()
        ean = re.sub(r"\D", "", raw_ean)
        if not ean:
            return jsonify({"error": "ean_requis"}), 400
        if len(ean) != EAN_REQUIRED_LENGTH:
            return (
                jsonify(
                    {
                        "error": "ean_format_invalid",
                        "message": f"EAN doivent contenir {EAN_REQUIRED_LENGTH} chiffres (reçu: {raw_ean})",
                    }
                ),
                400,
            )

    descriptor = load_manual_descriptor(ean)
    if not descriptor:
        descriptor = ensure_manual_descriptor(ean)

    preview_only = False
    preview_sources = []
    if isinstance(payload, dict):
        preview_sources.append(payload.get("preview_only"))
    if request.form:
        preview_sources.append(request.form.get("preview_only"))
    preview_sources.append(request.args.get("preview_only"))
    for flag in preview_sources:
        if isinstance(flag, bool) and flag:
            preview_only = True
            break
        if isinstance(flag, str) and flag.lower() in {"1", "true", "yes"}:
            preview_only = True
            break

    headed = bool(payload.get("headed", True))
    adapters = payload.get("adapters")
    if adapters and not isinstance(adapters, list):
        adapters = None
    if not adapters:
        adapters = [
            "carrefour_city",
            "carrefour_market",
            "carrefour_super",
            "auchan",
            "chronodrive",
            "courseu",
            "g20",
            "intermarche",
            "leclerc",
            "monoprix",
        ]
    proxy = payload.get("proxy") or request.args.get("proxy")

    extra_env: Dict[str, str] = {}
    for key in ("CDP_URL", "LECLERC_DRIVE_URL", "CHRONODRIVE_STORE_URL", "COURSEU_STORE_URL", "COURSEU_STORE_NAME"):
        value = payload.get(key) or request.args.get(key.lower())
        if value:
            extra_env[key] = value

    if preview_only:
        response_payload = {
            "status": "PREVIEW",
            "ean": ean,
            "descriptor": descriptor,
            "uploaded_image_path": str(stored_path) if stored_path else None,
        }
        return jsonify(response_payload)

    purge_results(ean)

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

    summary_entry = summary.get(ean) if isinstance(summary, dict) else None
    upsert_global_summary(ean, summary_entry)

    descriptor = set_descriptor_removed_flag(ean, False)

    return jsonify(
        {
            "status": "OK",
            "ean": ean,
            "descriptor": descriptor,
            "query": build_seed_query(ean, descriptor),
            "latest": latest,
            "summary": summary_entry,
            "stdout": stdout,
            "from_image": image_mode,
            "uploaded_image_path": str(stored_path) if stored_path else None,
        }
    )


@app.post("/api/remove")
def api_remove():
    payload = request.get_json(silent=True) or {}
    raw_ean = payload.get("ean") or ""
    ean = re.sub(r"\D", "", str(raw_ean))
    if len(ean) < 8 or len(ean) > 14:
        return (
            jsonify(
                {
                    "error": "ean_format_invalid",
                    "message": f"EAN doivent contenir entre 8 et 14 chiffres (reçu: {raw_ean})",
                }
            ),
            400,
        )

    descriptor = set_descriptor_removed_flag(ean, True)
    remove_global_summary_entry(ean)

    return jsonify(
        {
            "status": "OK",
            "ean": ean,
            "descriptor": descriptor,
        }
    )


@app.get("/")
def home():
    return "MaxiCourses API: POST /api/collect {ean: ...}"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
