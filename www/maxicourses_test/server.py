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

import subprocess
import functools
from flask import Flask, request, jsonify, send_from_directory, abort, session, redirect, url_for, render_template_string

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
RESULTS_ROOT = ROOT / "results"
GLOBAL_SUMMARY_PATH = RESULTS_ROOT / "summary.json"
OPENFOODFACTS_ENDPOINT = "https://world.openfoodfacts.org/api/v2/product/{ean}.json"
OFF_TIMEOUT_SECONDS = 10
EAN_REQUIRED_LENGTH = 13
UPLOADS_DIR = ROOT.parent / "uploads_ean"
PIPELINE_TIMEOUT_SECONDS = int(os.getenv("PIPELINE_TIMEOUT_SECONDS", "900"))

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


def fix_json_paths(data: Any) -> Any:
    """Recursively fix paths in JSON data to be relative to server root."""
    if isinstance(data, dict):
        return {k: fix_json_paths(v) for k, v in data.items()}
    if isinstance(data, list):
        return [fix_json_paths(v) for v in data]
    if isinstance(data, str):
        # Fix absolute paths from local machine or previous runs
        if "/results/" in data:
            # Keep only the part starting with results/
            try:
                index = data.find("results/")
                if index != -1:
                    return data[index:]
            except Exception:
                pass
        # Fix broken URLs (e.g. spaces in extension)
        if data.startswith("http") and " " in data:
            return data.replace(" ", "")
    return data


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


def load_descriptor_cache() -> Dict[str, Any]:
    """Load enriched descriptors from pipeline/descriptor_cache.json.
    
    This cache contains keywords and metadata generated during global collections,
    including leclerc_queries, primary_keywords, and other enriched fields.
    """
    cache_path = ROOT / "pipeline" / "descriptor_cache.json"
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def load_manual_descriptor(ean: str) -> Dict[str, Any]:
    """Load descriptor for an EAN, merging data from seed_catalog and descriptor_cache.
    
    Priority order:
    1. seed_catalog (base data)
    2. descriptor_cache (enriched keywords from global collections)
    
    This ensures solo collections can reuse the optimized keywords generated during
    global collections rather than falling back to generic OpenFoodFacts data.
    """
    descriptor = load_descriptor_from_store(ean)
    descriptor.setdefault("ean", ean)
    
    # Merge enriched data from descriptor_cache if available
    cache = load_descriptor_cache()
    cached_descriptor = cache.get(ean)
    if isinstance(cached_descriptor, dict):
        # Prioritize these cached fields as they contain optimized keywords
        priority_fields = [
            "leclerc_query",
            "leclerc_queries", 
            "primary_keywords",
            "secondary_keywords",
            "seed_query",
            "seed_primary_name",
            "seed_primary_quantity",
            "canonical",
            "queries",  # Store-specific queries
            "negatives",  # Store-specific negative keywords
        ]
        for field in priority_fields:
            if field in cached_descriptor and cached_descriptor[field]:
                descriptor[field] = cached_descriptor[field]
    
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
    
    # Merge descriptor_cache.json data (URLs, keywords)
    cache_path = Path(__file__).parent / "pipeline" / "descriptor_cache.json"
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_data = cache.get(ean, {})
            if isinstance(cached_data, dict):
                for key, value in cached_data.items():
                    # Merge cached values for _url keys and query/keyword keys
                    if key.endswith("_url") or "queries" in key or "query" in key or "keywords" in key:
                        if value:  # Only if not None/empty
                            entry[key] = value
        except Exception:
            pass
    
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
    return RESULTS_ROOT / f"test-{ean}"


def purge_results(ean: str) -> None:
    dataset_dir = results_dir_for(ean)
    if dataset_dir.exists():
        try:
            shutil.rmtree(dataset_dir)
        except Exception:
            pass
    if RESULTS_ROOT.exists():
        for run_file in RESULTS_ROOT.glob(f"run-{ean}-*.json"):
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
    env["USE_CDP"] = "1"
    env["LECLERC_MAX_DURATION_S"] = "45"
    env["LECLERC_FAST_MODE"] = "1"
    env["LECLERC_NO_DELAY"] = "1"
    if extra_env:
        env.update(extra_env)

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=PIPELINE_TIMEOUT_SECONDS,
    )
    return proc


app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
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


@app.post("/api/update-price")
def api_update_price():
    """Quick price update using cached URLs (no search needed)."""
    payload = request.get_json(silent=True) or {}
    raw_ean = (payload.get("ean") or request.args.get("ean") or "").strip()
    ean = re.sub(r"\D", "", raw_ean)
    if not ean:
        return jsonify({"error": "ean_requis"}), 400
    if len(ean) != EAN_REQUIRED_LENGTH:
        return jsonify({
            "error": "ean_format_invalid",
            "message": f"EAN doivent contenir {EAN_REQUIRED_LENGTH} chiffres (reçu: {raw_ean})",
        }), 400

    descriptor = ensure_manual_descriptor(ean)
    
    headed = bool(payload.get("headed", False))
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
            "casino",
            "spar",
            "intermarche",
            "leclerc",
            "monoprix",
        ]
    
    proxy = payload.get("proxy") or request.args.get("proxy")
    
    extra_env: Dict[str, str] = {"USE_CACHED_URLS": "1"}
    for key in ("CDP_URL", "LECLERC_DRIVE_URL", "CHRONODRIVE_STORE_URL", "COURSEU_STORE_URL", "COURSEU_STORE_NAME"):
        value = payload.get(key) or request.args.get(key.lower())
        if value:
            extra_env[key] = value

    if descriptor:
        try:
            extra_env["INITIAL_DESCRIPTOR_JSON"] = json.dumps(descriptor, ensure_ascii=False)
        except Exception:
            pass

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
        return jsonify({
            "error": "pipeline_failed",
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }), 500

    latest_path = results_dir_for(ean) / "latest.json"
    summary_path = results_dir_for(ean) / "summary.json"
    if not latest_path.exists():
        return jsonify({
            "error": "missing_results",
            "message": f"latest.json introuvable dans {latest_path.parent}",
            "stdout": stdout,
            "stderr": stderr,
        }), 500

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

    return jsonify({
        "status": "OK",
        "ean": ean,
        "descriptor": descriptor,
        "latest": fix_json_paths(latest),
        "summary": fix_json_paths(summary_entry),
        "stdout": stdout,
        "mode": "quick_price_update",
    })


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

    # IMPORTANT: Toujours appeler ensure_manual_descriptor pour enrichir le descriptor
    # via OpenFoodFacts si nécessaire (brand, name, quantity, etc.)
    # Cela garantit que même en mode solo, on aura les données nécessaires pour générer des keywords
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
            "casino",
            "spar",
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

    if descriptor:
        try:
            extra_env["INITIAL_DESCRIPTOR_JSON"] = json.dumps(descriptor, ensure_ascii=False)
        except Exception:
            pass

    if preview_only:
        response_payload = {
            "status": "PREVIEW",
            "ean": ean,
            "descriptor": descriptor,
            "uploaded_image_path": str(stored_path) if stored_path else None,
        }
        return jsonify(response_payload)

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
            "latest": fix_json_paths(latest),
            "summary": fix_json_paths(summary_entry),
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


@app.get("/results/<path:subpath>")
def serve_results(subpath: str):
    safe_root = RESULTS_ROOT.resolve()
    try:
        target = (safe_root / subpath).resolve()
    except Exception:
        abort(404)
    if not str(target).startswith(str(safe_root)):
        abort(404)
    if not target.exists() or target.is_dir():
        abort(404)
    relative = target.relative_to(safe_root)
    return send_from_directory(safe_root, str(relative))


@app.get("/")
def home():
    # Serve the frontend UI
    index_path = ROOT / "pipeline" / "index_ovh_prod.html"
    if index_path.exists():
        return send_from_directory(index_path.parent, index_path.name)
    return "MaxiCourses API: POST /api/collect {ean: ...} (Frontend not found)"

@app.get("/index.html")
def index_html():
    return home()


def fix_json_paths(data: Any) -> Any:
    """Recursively fix paths in JSON data to be relative to server root."""
    if isinstance(data, dict):
        return {k: fix_json_paths(v) for k, v in data.items()}
    if isinstance(data, list):
        return [fix_json_paths(v) for v in data]
    if isinstance(data, str):
        # Fix absolute paths from local machine or previous runs
        if "/results/" in data:
            # Keep only the part starting with results/
            try:
                index = data.find("results/")
                if index != -1:
                    return data[index:]
            except Exception:
                pass
        # Fix broken URLs (e.g. spaces in extension)
        if data.startswith("http") and " " in data:
            return data.replace(" ", "")
    return data


@app.get("/assets/<path:subpath>")
def serve_assets(subpath: str):
    # Assets are likely in ../../assets relative to this file (www/maxicourses_test/server.py)
    # Or just check common locations
    possible_roots = [
        ROOT.parent.parent / "assets", # ~/maxicourses-ovh/assets
        ROOT / "assets",               # ~/maxicourses-ovh/www/maxicourses_test/assets
        ROOT / "pipeline" / "assets",  # ~/maxicourses-ovh/www/maxicourses_test/pipeline/assets
    ]
    for root in possible_roots:
        target = (root / subpath).resolve()
        if target.exists() and str(target).startswith(str(root.resolve())):
             return send_from_directory(root, subpath)
    abort(404)

# --- Control Panel ---

app.secret_key = "maxicourses_secret_key_change_me"  # Needed for session
CONTROL_PASSWORD = "20851967!"

def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("ovh_control_login"))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/ovh_control/login", methods=["GET", "POST"])
def ovh_control_login():
    if request.method == "POST":
        if request.form.get("password") == CONTROL_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("ovh_control"))
        else:
            return render_template_string(LOGIN_TEMPLATE, error="Mot de passe incorrect")
    return render_template_string(LOGIN_TEMPLATE)

@app.route("/ovh_control/logout")
def ovh_control_logout():
    session.pop("logged_in", None)
    return redirect(url_for("ovh_control_login"))

@app.route("/ovh_control")
@login_required
def ovh_control():
    return render_template_string(CONTROL_TEMPLATE)

@app.route("/api/control/<action>", methods=["POST"])
@login_required
def api_control(action):
    try:
        output = ""
        status_code = "ok"
        
        # --- WEB SERVICE ---
        if action == "status_web":
            try:
                # Check if active
                subprocess.check_call(["systemctl", "is-active", "--quiet", "maxicourses-web.service"])
                output = "OK"
            except subprocess.CalledProcessError:
                output = "NO OK"
        elif action == "start_web":
            subprocess.check_call(["sudo", "systemctl", "start", "maxicourses-web.service"])
            output = "Service démarré."
        elif action == "restart_web":
            subprocess.check_call(["sudo", "systemctl", "restart", "maxicourses-web.service"])
            output = "Service redémarré."
        elif action == "stop_web":
            subprocess.check_call(["sudo", "systemctl", "stop", "maxicourses-web.service"])
            output = "Service arrêté."
        elif action == "logs_web":
             output = subprocess.check_output(["journalctl", "-u", "maxicourses-web.service", "-n", "50", "--no-pager"], stderr=subprocess.STDOUT, text=True)

        # --- CHROME SERVICE ---
        elif action == "status_chrome":
            try:
                subprocess.check_call(["systemctl", "is-active", "--quiet", "chrome-debug@ubuntu.service"])
                output = "OK"
            except subprocess.CalledProcessError:
                output = "NO OK"
        elif action == "start_chrome":
            subprocess.check_call(["sudo", "systemctl", "start", "chrome-debug@ubuntu.service"])
            output = "Chrome démarré."
        elif action == "restart_chrome":
            subprocess.check_call(["sudo", "systemctl", "restart", "chrome-debug@ubuntu.service"])
            output = "Chrome redémarré."
        elif action == "stop_chrome":
            subprocess.check_call(["sudo", "systemctl", "stop", "chrome-debug@ubuntu.service"])
            output = "Chrome arrêté."
            
        # --- SSH TUNNEL ---
        elif action == "status_tunnel":
            # Check for sshd listening on port 9223 (IPv4 or IPv6) - DEDICATED TUNNEL PORT
            cmd = "sudo ss -tulpn | grep :9223 | grep sshd"
            try:
                subprocess.check_output(cmd, shell=True, text=True)
                output = "OK"
            except subprocess.CalledProcessError:
                output = "NO OK"
        elif action == "start_tunnel":
            # Tunnels are initiated from the client, not the server
            output = "⚠️ Action requise côté client (Mac) :\n\nOuvrez un terminal sur votre Mac et lancez :\nssh -R 9223:localhost:9222 ovh-server\n\n(Cela connectera le port 9223 du serveur à votre Chrome Mac sur 9222)"
            status_code = "warning"
        elif action == "stop_tunnel" or action == "kill_tunnel":
            # Kill the sshd process listening on port 9223
            try:
                # Extract PID: users:(("sshd",pid=1234,fd=7)) -> 1234
                cmd = "sudo ss -lptn 'sport = :9223' | grep sshd | grep -o 'pid=[0-9]*' | cut -d'=' -f2 | xargs -r sudo kill"
                subprocess.check_call(cmd, shell=True)
                output = "Tunnel arrêté (processus tué)."
            except subprocess.CalledProcessError as e:
                output = f"Erreur lors de l'arrêt du tunnel: {e}"
            
        return jsonify({"status": status_code, "output": output})
    except subprocess.CalledProcessError as e:
        return jsonify({"status": "error", "output": e.output if e.output else str(e)})
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)})

# --- Templates ---

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Login - OVH Control</title>
    <style>
        body { font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f0f2f5; }
        .card { background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        input { padding: 0.5rem; margin-bottom: 1rem; width: 100%; box-sizing: border-box; }
        button { background: #007bff; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; width: 100%; }
        button:hover { background: #0056b3; }
        .error { color: red; margin-bottom: 1rem; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Connexion</h2>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="post">
            <input type="password" name="password" placeholder="Mot de passe" required autofocus>
            <button type="submit">Entrer</button>
        </form>
    </div>
</body>
</html>
"""

CONTROL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>OVH Control Panel</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; background: #f8fafc; color: #333; }
        .container { max-width: 600px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        h1 { font-size: 1.5rem; margin: 0; color: #1e293b; }
        .card { background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        h2 { margin: 0; font-size: 1.1rem; color: #475569; }
        .status-badge { padding: 4px 12px; border-radius: 999px; font-size: 0.85rem; font-weight: 600; }
        .status-ok { background: #dcfce7; color: #166534; }
        .status-nook { background: #fee2e2; color: #991b1b; }
        .status-unknown { background: #f1f5f9; color: #64748b; }
        
        .actions { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 10px; margin-top: 15px; }
        button { padding: 10px; border: none; border-radius: 6px; cursor: pointer; font-weight: 500; transition: all 0.2s; font-size: 0.9rem; }
        
        .btn-start { background: #22c55e; color: white; }
        .btn-start:hover { background: #16a34a; }
        
        .btn-restart { background: #f59e0b; color: white; }
        .btn-restart:hover { background: #d97706; }
        
        .btn-stop { background: #ef4444; color: white; }
        .btn-stop:hover { background: #dc2626; }
        
        .btn-logs { background: #3b82f6; color: white; }
        .btn-logs:hover { background: #2563eb; }

        .message-box { margin-top: 15px; padding: 10px; background: #f8fafc; border-radius: 6px; font-size: 0.85rem; color: #475569; display: none; border: 1px solid #e2e8f0; }
        .logout { color: #64748b; text-decoration: none; font-size: 0.9rem; }
        .logout:hover { color: #ef4444; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>OVH Control</h1>
            <a href="/ovh_control/logout" class="logout">Déconnexion</a>
        </div>

        <!-- Maxicourses Web -->
        <div class="card">
            <div class="card-header">
                <h2>Maxicourses Web</h2>
                <span id="status_web_badge" class="status-badge status-unknown">Checking...</span>
            </div>
            <div class="actions">
                <button class="btn-start" onclick="run('start_web')">Lancer</button>
                <button class="btn-restart" onclick="run('restart_web')">Redémarrer</button>
                <button class="btn-stop" onclick="run('stop_web')">Arrêter</button>
                <button class="btn-logs" onclick="run('logs_web')">Logs</button>
            </div>
            <div id="msg_web" class="message-box"></div>
        </div>

        <!-- Chrome Debug -->
        <div class="card">
            <div class="card-header">
                <h2>Chrome Debug</h2>
                <span id="status_chrome_badge" class="status-badge status-unknown">Checking...</span>
            </div>
            <div class="actions">
                <button class="btn-start" onclick="run('start_chrome')">Lancer</button>
                <button class="btn-restart" onclick="run('restart_chrome')">Redémarrer</button>
                <button class="btn-stop" onclick="run('stop_chrome')">Arrêter</button>
            </div>
            <div id="msg_chrome" class="message-box"></div>
        </div>

        <!-- SSH Tunnel -->
        <div class="card">
            <div class="card-header">
                <h2>Tunnel SSH</h2>
                <span id="status_tunnel_badge" class="status-badge status-unknown">Checking...</span>
            </div>
            <div class="actions">
                <button class="btn-start" onclick="run('start_tunnel')">Lancer</button>
                <button class="btn-stop" onclick="run('stop_tunnel')">Arrêter / Tuer</button>
            </div>
            <div id="msg_tunnel" class="message-box"></div>
        </div>
    </div>

    <script>
        // Auto-refresh status on load
        window.onload = function() {
            checkStatus('web');
            checkStatus('chrome');
            checkStatus('tunnel');
        };

        async function checkStatus(service) {
            const badge = document.getElementById('status_' + service + '_badge');
            try {
                const response = await fetch('/api/control/status_' + service, { method: 'POST' });
                const data = await response.json();
                
                if (data.output.trim() === 'OK') {
                    badge.textContent = 'OK';
                    badge.className = 'status-badge status-ok';
                } else {
                    badge.textContent = 'NO OK';
                    badge.className = 'status-badge status-nook';
                }
            } catch (e) {
                badge.textContent = 'Error';
                badge.className = 'status-badge status-nook';
            }
        }

        async function run(action) {
            const service = action.split('_')[1]; // web, chrome, tunnel
            const msgBox = document.getElementById('msg_' + service);
            
            msgBox.style.display = 'block';
            msgBox.textContent = "Exécution...";
            msgBox.style.color = '#475569';
            
            try {
                const response = await fetch('/api/control/' + action, { method: 'POST' });
                const data = await response.json();
                
                if (action.startsWith('logs')) {
                    msgBox.innerHTML = '<pre>' + data.output + '</pre>';
                } else {
                    msgBox.textContent = data.output;
                    // Refresh status after action (with small delay)
                    setTimeout(() => checkStatus(service), 2000);
                }
            } catch (e) {
                msgBox.textContent = "Erreur: " + e;
                msgBox.style.color = '#dc2626';
            }
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
