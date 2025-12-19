
import os
import sys
import json
from pathlib import Path

# Fix path to import modules
sys.path.append(os.path.join(os.path.dirname(__file__)))

from descriptor_store import ProductRepository
from seed_catalog import all_seeds

def migrate():
    repo = ProductRepository()
    if not repo.enabled:
        print("MongoDB not enabled or pymongo missing. Aborting.")
        return

    print("--- Starting Migration to MongoDB ---")
    if repo.products is not None:
         print("0. Cleaning existing collection...")
         repo.products.drop()
         # Re-init index
         repo.products.create_index("ean", unique=True)
         repo.products.create_index("keywords")
    
    # 1. Import Seeds
    print("1. Importing Seed Catalog...")
    seeds = all_seeds()
    count_seeds = 0
    for ean, data in seeds.items():
        # Clean data for DB
        payload = dict(data)
        
        # Enrich Stores
        if "stores" in data and isinstance(data["stores"], dict):
            # Ensure we don't wipe existing stores if seed has some
            if "stores" not in payload:
                payload["stores"] = {}
            payload["stores"].update(data["stores"])
            
        # Enrich Keywords
        if "primary_keywords" in data and isinstance(data["primary_keywords"], list):
            payload["keywords"] = data["primary_keywords"]
            
        # Enrich Queries (The Memory of what search worked)
        queries_map = {}
        if "queries" in data and isinstance(data["queries"], dict):
            queries_map.update(data["queries"])
        
        # Legacy fields fallback
        if "leclerc_queries" in data and "leclerc" not in queries_map:
             queries_map["leclerc"] = data["leclerc_queries"]
        elif "leclerc_query" in data and "leclerc" not in queries_map:
             queries_map["leclerc"] = [data["leclerc_query"]]

        if queries_map:
            payload["queries"] = queries_map

        if repo.upsert_product(ean, payload):
            count_seeds += 1
    print(f"   -> Imported {count_seeds} seeds.")

    # 2. Import Cache
    cache_path = Path(__file__).parent / "pipeline" / "descriptor_cache.json"
    print(f"2. Importing Cache from {cache_path}...")
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            
            count_cache = 0
            for ean, data in cache.items():
                # Extract store URLs from cache (flat keys like 'carrefour_url' -> nested 'stores.carrefour.url')
                # The cache format is flat: {"ean":..., "carrefour_url": "...", "auchan_url": "..."}
                
                # Retrieve existing from DB first to merge? 
                # upsert_product merges fields, but we need to construct the 'stores' dict
                existing = repo.get_product(ean) or {}
                stores = existing.get("stores") or {}
                
                # Map flat keys to stores dict
                for key, val in data.items():
                    if key.endswith("_url") and val and "http" in str(val):
                        store_name = key.replace("_url", "")
                        if store_name not in stores:
                            stores[store_name] = {}
                        stores[store_name]["url"] = val
                        # Try to find price? Cache might not have price easily accessible here, 
                        # usually cache only stores descriptors.
                
                payload = {
                   "stores": stores
                }
                
                # If title/brand present in cache and not in seed (unlikely but possible for learned), add them
                if not existing.get("title") and data.get("title"):
                    payload["title"] = data.get("title")
                
                if repo.upsert_product(ean, payload):
                    count_cache += 1
            print(f"   -> Enriched {count_cache} products from cache.")
            
        except Exception as e:
            print(f"   -> Error reading cache: {e}")
    else:
        print("   -> Cache file not found.")

    print("--- Migration Complete ---")
    print(f"Total Products in DB: {repo.products.count_documents({})}")

if __name__ == "__main__":
    migrate()
