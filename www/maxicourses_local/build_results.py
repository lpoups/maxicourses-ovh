#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent


def load_previous_results():
    path = ROOT / "results.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {item.get("ean"): item for item in data.get("items", []) if item.get("ean")}
    except Exception:
        return {}


def off_descriptor(ean: str):
    try:
        url = f"https://world.openfoodfacts.org/api/v2/product/{ean}.json"
        with urlopen(url, timeout=20) as r:
            data = json.load(r)
        p = data.get("product", {})
        return {
            "ean": ean,
            "brand": p.get("brands"),
            "name": p.get("product_name"),
            "quantity": p.get("quantity"),
            "image": p.get("image_front_url") or p.get("image_url"),
            "categories": p.get("categories"),
        }
    except Exception:
        return {"ean": ean}


def run_fetcher(script: str, env: dict):
    p = subprocess.run(
        [sys.executable, str(ROOT / script)],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = p.stdout.strip()
    try:
        return json.loads(out)
    except Exception:
        return {"status": "ERROR", "raw": out, "code": p.returncode}


def main():
    if len(sys.argv) < 2:
        print("USAGE: build_results.py <EAN>[,<EAN2>...]")
        sys.exit(2)
    eans = [s.strip() for s in sys.argv[1].split(',') if s.strip()]

    previous = load_previous_results()
    results = {"generated_at": datetime.utcnow().isoformat() + "Z", "items": []}

    for ean in eans:
        desc = off_descriptor(ean)
        item = {"ean": ean, "descriptor": desc}
        query = None
        if desc.get('brand') or desc.get('name'):
            raw_query = f"{desc.get('brand','')} {desc.get('name','')} {desc.get('quantity','')}"
            query = re.sub(r"[^\w\s]", " ", raw_query).strip()
        env = {"HEADLESS": "1", "EAN": ean}
        env_with_query = {**env, **({"QUERY": query} if query else {})}

        prev_vendors = {}
        if isinstance(previous.get(ean), dict):
            prev_vendors = previous[ean].get("vendors", {}) or {}

        def merge(vendor: str, result: dict):
            if result and isinstance(result, dict) and result.get("status") == "OK" and result.get("price"):
                return result
            return prev_vendors.get(vendor, result)

        item["vendors"] = {
            "carrefour": merge("carrefour", run_fetcher("fetch_carrefour_price.py", env)),
            "leclerc": merge("leclerc", run_fetcher("fetch_leclerc_price.py", env_with_query)),
            "leclerc_drive": merge(
                "leclerc_drive",
                run_fetcher("fetch_leclerc_drive_price.py", env_with_query),
            ),
            "auchan": merge("auchan", run_fetcher("fetch_auchan_price.py", env_with_query)),
            "intermarche": merge("intermarche", run_fetcher("fetch_intermarche_price.py", env_with_query)),
            "chronodrive": merge("chronodrive", run_fetcher("fetch_chronodrive_price.py", env_with_query)),
        }
        results["items"].append(item)

    out_path = ROOT / "results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"WROTE {out_path}")


if __name__ == "__main__":
    main()
