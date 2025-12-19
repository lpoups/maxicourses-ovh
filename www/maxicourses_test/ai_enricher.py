#!/usr/bin/env python3
"""
AI Enricher Worker
------------------
Watches MongoDB for products seeking enrichment (status='NEW' or 'RETRY_ENRICHMENT').
Uses LLM (via ai_helpers) to generate:
- Normalized Brand
- Normalized Quantity
- Effective Search Keywords (for Drive retailers)
- Product Category

Usage:
  python3 ai_enricher.py [--loop]
"""
import sys
import os
import time
import argparse
import signal
from pathlib import Path

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__)))

from descriptor_store import ProductRepository
from ai_helpers import summarize_product_seed

def enrich_product(repo: ProductRepository, ean: str, data: dict):
    print(f"[ENRICH] Processing {ean} ({data.get('title')})...")
    
    # 1. Prepare Payload for AI
    seed_payload = {
        "brand": data.get("brand"),
        "name": data.get("title") or data.get("name"),
        "quantity": data.get("quantity"),
        "description": data.get("description")
    }
    
    # 2. Call LLM
    start = time.time()
    response = summarize_product_seed([seed_payload])
    duration = time.time() - start
    
    if response.status != "ok":
        print(f"[ERROR] AI Failed for {ean}: {response.error}")
        repo.upsert_product(ean, {"status": "ENRICHMENT_FAILED", "last_ai_check": time.time()})
        return False
        
    ai_data = response.data
    
    # 3. Construct Update
    # We trust AI to normalize brand/quantity better than Regex
    update_payload = {
        "status": "READY_FOR_COLLECTION",
        "ai_enriched": True,
        "last_ai_check": time.time(),
        "ai_profile": ai_data.get("profile"),
        "keywords": ai_data.get("keywords"),
        "categories": ai_data.get("category"),
        "primary_keywords": ai_data.get("primary_keywords"),
        # We also store the "Smart Queries" for each retailer
        "queries": {
            "leclerc": ai_data.get("primary_keywords", [])[:1], # Best guess
            "monoprix": ai_data.get("secondary_keywords", [])[:2], # Broader
            "intermarche": ai_data.get("primary_keywords", [])[:1]
        }
    }
    
    # Explicit override if high confidence
    if ai_data.get("profile"):
        p = ai_data["profile"]
        if p.get("brand"): update_payload["brand"] = p["brand"]
        if p.get("quantity"): update_payload["quantity"] = p["quantity"]
        
    # 4. Save
    repo.upsert_product(ean, update_payload)
    print(f"[SUCCESS] Enriched {ean} in {duration:.2f}s. Keywords: {len(update_payload['keywords'])}")
    return True

def run_loop(single_pass=False):
    repo = ProductRepository()
    if not repo.enabled:
        print("[FATAL] MongoDB not connected.")
        sys.exit(1)
        
    print("[WORKER] AI Enricher started. Waiting for products...")
    
    while True:
        # Fetch candidate
        # status can be missing (legacy), 'NEW', or 'RETRY'
        # We process legacy ones if 'ai_enriched' is not True
        candidate = repo.products.find_one({
            "$or": [
                {"status": "NEW"},
                {"status": "RETRY_ENRICHMENT"},
                {"ai_enriched": {"$ne": True}, "removed": {"$ne": True}}
            ]
        })
        
        if candidate:
            enrich_product(repo, candidate["ean"], candidate)
            time.sleep(1) # Rate limit protection
        else:
            if single_pass:
                break
            time.sleep(5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Run in continuous loop")
    args = parser.parse_args()
    
    run_loop(single_pass=not args.loop)
