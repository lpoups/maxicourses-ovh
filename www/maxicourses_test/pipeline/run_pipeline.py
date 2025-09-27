#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover - optional dependency when --image n/a
    Image = None  # type: ignore

try:
    import zxingcpp  # type: ignore
except ImportError:  # pragma: no cover - optional dependency when --image n/a
    zxingcpp = None  # type: ignore

ROOT_DIR = Path(__file__).resolve().parent.parent

if __package__ in (None, ""):
    sys.path.append(str(ROOT_DIR))
    from pipeline.models import PipelineRun, RawAdapterResult  # type: ignore
else:  # pragma: no cover - executed when package imports are available
    from .models import PipelineRun, RawAdapterResult
DEFAULT_RESULTS_DIR = ROOT_DIR / "results"
MANUAL_DESCRIPTOR_PATH = ROOT_DIR / "manual_descriptors.json"

ADAPTER_SCRIPTS: Dict[str, Dict[str, Any]] = {
    "carrefour_city": {
        "script": ROOT_DIR / "fetch_carrefour_price_city.py",
        "env": lambda: {
            "CARREFOUR_STATE_VARIANT": os.getenv("CARREFOUR_CITY_STATE", "carrefour_city"),
        },
    },
    "carrefour_market": {
        "script": ROOT_DIR / "fetch_carrefour_price_market.py",
        "env": lambda: {
            "CARREFOUR_STATE_VARIANT": os.getenv("CARREFOUR_MARKET_STATE", "carrefour_market"),
        },
    },
    "leclerc": {
        "script": ROOT_DIR / "fetch_leclerc_drive_price.py",
        "env": lambda: {
            "STORE_URL": os.getenv(
                "LECLERC_DRIVE_URL",
                "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx",
            ),
        },
    },
    "intermarche": {
        "script": ROOT_DIR / "fetch_intermarche_price.py",
        "env": lambda: {
            "HOME_URL": os.getenv("INTERMARCHE_HOME_URL", "https://www.intermarche.com/accueil"),
        },
    },
    "auchan": {
        "script": ROOT_DIR / "fetch_auchan_price.py",
        "env": lambda: {
            "HOME_URL": os.getenv("AUCHAN_HOME_URL", "https://www.auchan.fr"),
        },
    },
    "chronodrive": {
        "script": ROOT_DIR / "fetch_chronodrive_price.py",
        "env": lambda: {
            "STORE_URL": os.getenv(
                "CHRONODRIVE_STORE_URL",
                "https://www.chronodrive.com/magasin/le-haillan-422",
            ),
        },
    },
}

DEFAULT_ADAPTER_ORDER = [
    "carrefour_city",
    "carrefour_market",
    "leclerc",
    "intermarche",
    "auchan",
    "chronodrive",
]


def decode_ean(image_path: Path) -> str:
    if Image is None or zxingcpp is None:
        raise RuntimeError("Lecture d'image indisponible (Pillow/zxingcpp manquants)")
    img = Image.open(image_path).convert("RGB")
    result = zxingcpp.read_barcode(img)
    if not result or not result.text:
        raise RuntimeError(f"Impossible d'extraire un EAN depuis {image_path}")
    return result.text.strip()


def load_manual_descriptor(ean: str) -> Optional[Dict[str, str]]:
    manual = fetch_manual_descriptor(ean)
    if not manual:
        return None
    descriptor = dict(manual)
    descriptor.setdefault("source", "manual")
    descriptor.setdefault("ean", ean)
    return descriptor


def fetch_manual_descriptor(ean: str) -> Optional[Dict[str, str]]:
    if not MANUAL_DESCRIPTOR_PATH.exists():
        return None
    try:
        data = json.loads(MANUAL_DESCRIPTOR_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    entry = data.get(ean)
    if isinstance(entry, dict):
        return entry
    return None


def load_all_descriptors() -> Dict[str, Dict[str, Any]]:
    if not MANUAL_DESCRIPTOR_PATH.exists():
        return {}
    try:
        data = json.loads(MANUAL_DESCRIPTOR_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data


def save_manual_descriptor_entry(ean: str, entry: Dict[str, Any]) -> None:
    data = load_all_descriptors()
    data[ean] = entry
    try:
        MANUAL_DESCRIPTOR_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def merge_descriptor(base: Optional[Dict[str, Any]], updates: Dict[str, Any]) -> Dict[str, Any]:
    descriptor = dict(base or {})
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        descriptor[key] = value
    descriptor.setdefault("ean", updates.get("ean"))
    return descriptor


def descriptor_from_payload(ean: str, adapter: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not payload:
        return {}
    name = payload.get("title") or payload.get("name") or f"Produit {ean}"
    quantity = payload.get("quantity") or ""
    image = payload.get("image") or payload.get("image_path")
    descriptor = {
        "ean": ean,
        "name": name,
        "quantity": quantity,
        "categories": "",
        "image": image,
        "source": adapter,
        "description": payload.get("description") or name,
        "note": payload.get("note") or f"Collecte seed via {adapter}",
    }
    # attempt to guess brand from title if not provided
    brand = payload.get("brand")
    if not brand and isinstance(name, str):
        brand_candidate = name.split()[0]
        descriptor["brand"] = brand_candidate
    else:
        descriptor["brand"] = brand
    if payload.get("nutriscore_grade"):
        descriptor["nutriscore_grade"] = payload.get("nutriscore_grade")
    if payload.get("nutriscore_image"):
        descriptor["nutriscore_image"] = payload.get("nutriscore_image")
    seed_pieces: list[str] = []
    for key in ("brand", "name", "quantity"):
        value = descriptor.get(key)
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                seed_pieces.append(cleaned)
    seen_lower: set[str] = set()
    ordered: list[str] = []
    for piece in seed_pieces:
        lower = piece.lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)
        ordered.append(piece)
    if ordered:
        descriptor["seed_query"] = " ".join(ordered)
    elif isinstance(descriptor.get("description"), str) and descriptor["description"].strip():
        descriptor["seed_query"] = descriptor["description"].strip()
    return descriptor


def ensure_descriptor_via_seed(
    *,
    ean: str,
    descriptor: Optional[Dict[str, Any]],
    query: str,
    adapters: List[str],
    headed: bool,
    proxy: Optional[str],
) -> tuple[Dict[str, Any], Dict[str, RawAdapterResult], str]:
    seed_results: Dict[str, RawAdapterResult] = {}
    needs_descriptor = not descriptor or not descriptor.get("name")
    if not needs_descriptor:
        return descriptor or {"ean": ean}, seed_results, query

    seed_order = ["carrefour_city", "carrefour_market", "auchan", "chronodrive"]
    descriptor_current = dict(descriptor or {"ean": ean})

    for adapter in seed_order:
        if adapter not in adapters:
            continue
        if adapter in seed_results:
            continue
        print(f"[SEED] Tentative via {adapter}")
        res = run_adapter(
            adapter,
            ean,
            ean,
            headless=not headed,
            proxy=proxy,
        )
        seed_results[adapter] = res
        if res.status == "OK" and isinstance(res.payload, dict):
            updates = descriptor_from_payload(ean, adapter, res.payload)
            descriptor_current = merge_descriptor(descriptor_current, updates)
            save_manual_descriptor_entry(ean, descriptor_current)
            needs_descriptor = False
            break

    new_query = build_search_query(ean, descriptor_current)
    return descriptor_current, seed_results, new_query


def build_search_query(ean: str, descriptor: Optional[Dict[str, str]]) -> str:
    if not descriptor:
        return ean
    seed = (descriptor.get("seed_query") or "").strip()
    if seed:
        return seed
    name = (descriptor.get("name") or "").strip()
    brand = (descriptor.get("brand") or "").strip()
    quantity = (descriptor.get("quantity") or "").strip()
    pieces = [p for p in [brand, name, quantity] if p]
    if pieces:
        return " ".join(pieces)
    return ean


def run_adapter(
    adapter: str,
    ean: str,
    query: Optional[str],
    *,
    headless: bool,
    proxy: Optional[str],
    extra_env: Optional[Dict[str, str]] = None,
) -> RawAdapterResult:
    if adapter not in ADAPTER_SCRIPTS:
        raise ValueError(f"Adaptateur inconnu: {adapter}")
    entry = ADAPTER_SCRIPTS[adapter]
    script_path = entry["script"]
    if not script_path.exists():
        raise FileNotFoundError(f"Script introuvable pour {adapter}: {script_path}")

    env = os.environ.copy()
    configured_env = entry.get("env", {})
    if callable(configured_env):
        configured_env = configured_env()
    env.update(configured_env or {})
    if extra_env:
        env.update(extra_env)
    env["EAN"] = ean
    env["HEADLESS"] = "1" if headless else "0"
    env.setdefault("USE_CDP", "1")
    if "CDP_URL" not in env and os.getenv("CDP_URL"):
        env["CDP_URL"] = os.environ["CDP_URL"]
    if proxy:
        env["PROXY"] = proxy
    if query:
        env.setdefault("QUERY", query)

    command = [sys.executable, str(script_path)]
    started_at = datetime.utcnow()
    proc = subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        cwd=str(ROOT_DIR),
    )
    finished_at = datetime.utcnow()
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip() if proc.stderr else None

    payload: Dict[str, Any]
    status = "ERROR"
    error = None
    if stdout:
        brace_start = stdout.find('{')
        brace_end = stdout.rfind('}')
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            json_candidate = stdout[brace_start:brace_end + 1]
        else:
            json_candidate = ""
        try:
            payload = json.loads(json_candidate)
            status = payload.get("status", "UNKNOWN")
        except json.JSONDecodeError:
            sanitized = json_candidate.replace("\r", " ").replace("\n", " ")
            try:
                payload = json.loads(sanitized)
                status = payload.get("status", "UNKNOWN")
            except json.JSONDecodeError as exc:
                payload = {
                    "raw_stdout": stdout,
                    "last_line": json_candidate,
                }
                error = f"JSONDecodeError: {exc}"
    else:
        payload = {}
        error = "EMPTY_STDOUT"

    if proc.returncode != 0 and not error:
        error = f"exit_code={proc.returncode}"

    return RawAdapterResult(
        adapter=adapter,
        status=status,
        payload=payload,
        started_at=started_at,
        finished_at=finished_at,
        script_path=str(script_path),
        command=command,
        env={
            k: env.get(k, "")
            for k in [
                "EAN",
                "QUERY",
                "STORE_QUERY",
                "STORE_URL",
                "HOME_URL",
                "CARREFOUR_STATE_VARIANT",
                "HEADLESS",
                "PROXY",
            ]
            if env.get(k) is not None
        },
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        error=error,
        metadata={},
    )


def ensure_results_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_run(run: PipelineRun, *, results_dir: Path) -> Path:
    ensure_results_dir(results_dir)
    timestamp = run.finished_at.strftime("%Y%m%d-%H%M%S")
    fname = f"run-{run.ean}-{timestamp}.json"
    full_path = results_dir / fname
    with full_path.open("w", encoding="utf-8") as fh:
        json.dump(run.as_dict(), fh, ensure_ascii=False, indent=2)
    latest_path = results_dir / "latest.json"
    with latest_path.open("w", encoding="utf-8") as fh:
        json.dump(run.as_dict(), fh, ensure_ascii=False, indent=2)
    return full_path


def update_summary(run: PipelineRun, *, results_dir: Path) -> None:
    summary_path = results_dir / "summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            summary = {}
    else:
        summary = {}

    ean_entry = summary.setdefault(run.ean, {})
    for res in run.adapter_results:
        ean_entry[res.adapter] = {
            "status": res.status,
            "payload": res.payload,
            "updated_at": run.finished_at.isoformat(),
            "duration_seconds": (res.finished_at - res.started_at).total_seconds(),
            "error": res.error,
            "store_query": res.env.get("STORE_QUERY"),
        }

    summary[run.ean] = ean_entry
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline MaxiCourses (proof of concept)")
    parser.add_argument("--ean", help="EAN à traiter")
    parser.add_argument("--image", help="Chemin vers l'image contenant le code-barres")
    parser.add_argument("--proxy", help="Proxy Playwright (ex: socks5://user:pass@host:port)")
    parser.add_argument("--headed", action="store_true", help="Affiche les navigateurs (HEADLESS=0)")
    parser.add_argument("--adapters", nargs="*", choices=list(ADAPTER_SCRIPTS.keys()), help="Liste d'adaptateurs à exécuter")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Répertoire de sortie pour les JSON")
    parser.add_argument("--human", action="store_true", help="Active un mode debug humain (screenshots, timings)" )
    parser.add_argument("--human-debug-root", help="Répertoire parent pour stocker les captures du mode humain")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if not args.ean and not args.image:
        print("[ERREUR] Fournir --ean ou --image")
        return 2

    image_path = None
    ean = args.ean
    if args.image:
        image_path = Path(args.image)
        if not image_path.exists():
            print(f"[ERREUR] Image introuvable: {image_path}")
            return 2
        ean = decode_ean(image_path)
        print(f"EAN détecté depuis l'image: {ean}")

    if not ean:
        print("[ERREUR] Aucun EAN disponible")
        return 2

    descriptor = load_manual_descriptor(ean)
    if descriptor:
        print("Descriptor (manuel):", json.dumps(descriptor, ensure_ascii=False))
    else:
        print("[WARN] Aucun descriptif manuel pour", ean)

    query = build_search_query(ean, descriptor)

    started_at = datetime.utcnow()
    adapters = args.adapters or DEFAULT_ADAPTER_ORDER

    human_mode = args.human or args.headed
    debug_root: Optional[Path] = None
    if human_mode:
        base_debug = Path(args.human_debug_root) if args.human_debug_root else (Path(args.results_dir) / "debug")
        ensure_results_dir(base_debug)
        debug_root = base_debug / f"run-{ean}-{started_at.strftime('%Y%m%d-%H%M%S')}"
        debug_root.mkdir(parents=True, exist_ok=True)
    results: List[RawAdapterResult] = []

    descriptor, seed_results, query = ensure_descriptor_via_seed(
        ean=ean,
        descriptor=descriptor,
        query=query,
        adapters=adapters,
        headed=args.headed,
        proxy=args.proxy,
    )
    query = build_search_query(ean, descriptor)

    for adapter in adapters:
        print(f"\n=== Adaptateur {adapter} ===")
        if adapter in seed_results:
            res = seed_results[adapter]
            results.append(res)
            print(json.dumps(res.payload, ensure_ascii=False))
            if res.error:
                print(f"[WARN] {adapter} -> {res.error}")
            continue
        adapter_debug = None
        if debug_root:
            adapter_debug = debug_root / f"{len(results)+1:02d}-{adapter}"
            adapter_debug.mkdir(parents=True, exist_ok=True)

        res = run_adapter(
            adapter,
            ean,
            query,
            headless=not args.headed,
            proxy=args.proxy,
            extra_env={"HUMAN_DEBUG_DIR": str(adapter_debug)} if adapter_debug else None,
        )
        results.append(res)
        print(json.dumps(res.payload, ensure_ascii=False))
        if res.error:
            print(f"[WARN] {adapter} -> {res.error}")
        if adapter_debug:
            res.metadata["debug_dir"] = str(adapter_debug)

    finished_at = datetime.utcnow()

    nutri_score_value = None
    if descriptor:
        raw_score = descriptor.get("nutriscore_score")
        try:
            nutri_score_value = int(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            nutri_score_value = None

    run = PipelineRun(
        ean=ean,
        image_path=str(image_path) if image_path else None,
        started_at=started_at,
        finished_at=finished_at,
        adapter_results=results,
        reference_title=descriptor.get("name") if descriptor else None,
        reference_description=descriptor.get("description") if descriptor else None,
        reference_source=descriptor.get("source") if descriptor else None,
        reference_brand=descriptor.get("brand") if descriptor else None,
        reference_quantity=descriptor.get("quantity") if descriptor else None,
        reference_image=descriptor.get("image") if descriptor else None,
        reference_categories=descriptor.get("categories") if descriptor else None,
        reference_nutriscore_grade=descriptor.get("nutriscore_grade") if descriptor else None,
        reference_nutriscore_image=descriptor.get("nutriscore_image") if descriptor else None,
        reference_nutriscore_score=nutri_score_value,
    )

    if human_mode and debug_root:
        run.notes.append(f"Human debug captures dans {debug_root}")

    results_dir = Path(args.results_dir)
    update_summary(run, results_dir=results_dir)
    output_path = save_run(run, results_dir=results_dir)
    print(f"\nRésultats enregistrés dans {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
