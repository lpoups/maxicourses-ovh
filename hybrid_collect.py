#!/usr/bin/env python3
"""
Hybrid Collection Orchestrator (Option A)
=========================================
This script runs on the LOCAL machine (Mac).
It orchestrates the collection to bypass IP blocks on OVH.

Logic:
1. Runs 'Blocked' stores (Carrefour, Intermarché) LOCALLY.
2. Syncs results (JSON + Images) to OVH.
3. Triggers 'Working' stores (Auchan, Monoprix, etc.) REMOTELY on OVH via SSH.
"""

import argparse
import subprocess
import sys
import json
import os
from pathlib import Path

# Configuration
OVH_HOST = "ovh-server"
REMOTE_DIR = "~/maxicourses-ovh/www/maxicourses_test"
LOCAL_DIR = Path(__file__).parent / "www" / "maxicourses_test"

# Stores definition
BLOCKED_STORES = ["carrefour_city", "carrefour_market", "carrefour_super", "intermarche"]
WORKING_STORES = ["auchan", "monoprix", "chronodrive", "leclerc"]

def run_local(ean, query, stores):
    """Runs collection locally for blocked stores sequentially."""
    print(f"🔵 [LOCAL] Starting collection for {stores}...")
    
    # Prepare environment
    env = os.environ.copy()
    env["HEADLESS"] = "0" # Force headed for blocked stores
    if query:
        env["QUERY"] = query

    for store in stores:
        print(f"  👉 Running {store}...")
        cmd = [
            sys.executable,
            "pipeline/run_pipeline.py",
            "--ean", ean,
            "--adapters", store
        ]
        try:
            # Add timeout to prevent hanging forever (e.g. 3 minutes per store)
            subprocess.run(cmd, cwd=LOCAL_DIR, env=env, check=False, timeout=180)
            print(f"  ✅ {store} finished.")
        except subprocess.TimeoutExpired:
            print(f"  ❌ {store} TIMED OUT (skipped).")
        except Exception as e:
            print(f"  ❌ {store} FAILED: {e}")

    print(f"✅ [LOCAL] All local collections finished.")

def sync_to_ovh(ean):
    """Syncs local results and assets to OVH."""
    print(f"blob [SYNC] Uploading results to OVH...")
    
    # Sync Results (JSONs)
    subprocess.run([
        "rsync", "-avz", 
        f"{LOCAL_DIR}/results/", 
        f"{OVH_HOST}:{REMOTE_DIR}/results/"
    ], check=True)
    
    # Sync Assets (Images)
    subprocess.run([
        "rsync", "-avz", 
        f"{LOCAL_DIR}/assets/", 
        f"{OVH_HOST}:{REMOTE_DIR}/assets/"
    ], check=True)
    
    print(f"✅ [SYNC] Upload finished.")

def trigger_remote(ean, query, stores):
    """Triggers collection on OVH for working stores."""
    print(f"☁️ [REMOTE] Triggering collection for {stores} on OVH...")
    
    stores_str = " ".join(stores)
    # Pass QUERY as env var in the SSH command
    query_env = f"export QUERY='{query}' &&" if query else ""
    
    ssh_cmd = f"""
        cd {REMOTE_DIR} && 
        source ../.venv/bin/activate && 
        export USE_CDP=1 CDP_URL='http://127.0.0.1:9222' && 
        {query_env} python3 pipeline/run_pipeline.py --ean {ean} --adapters {stores_str}
    """
    
    subprocess.run(["ssh", OVH_HOST, ssh_cmd], check=False)
    print(f"✅ [REMOTE] Collection finished.")

def main():
    parser = argparse.ArgumentParser(description="Hybrid Collection Orchestrator")
    parser.add_argument("--ean", required=True, help="EAN of the product")
    parser.add_argument("--query", help="Search query (optional)")
    args = parser.parse_args()

    print(f"🚀 Starting Hybrid Collection for EAN: {args.ean}")
    
    # 1. Run Blocked Stores Locally
    run_local(args.ean, args.query, BLOCKED_STORES)
    
    # 2. Sync Results
    sync_to_ovh(args.ean)
    
    # 3. Run Working Stores Remotely
    trigger_remote(args.ean, args.query, WORKING_STORES)
    
    print("\n✨ Hybrid Collection Complete!")
    print(f"👉 Check results at: https://maxicourses.fr/results/{args.ean}")

if __name__ == "__main__":
    main()
