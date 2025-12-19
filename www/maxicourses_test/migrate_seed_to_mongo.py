#!/usr/bin/env python3
"""
migrate_seed_to_mongo.py
Migre tous les produits de seed_catalog.py vers MongoDB.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_catalog import SEED_CATALOG
from descriptor_store import ProductRepository

def migrate():
    repo = ProductRepository()
    if not repo.enabled:
        print("[ERROR] MongoDB non connecté!")
        return
    
    total = 0
    migrated = 0
    skipped = 0
    
    for ean, data in SEED_CATALOG.items():
        total += 1
        
        # Skip removed products
        if data.get("removed"):
            print(f"[SKIP] {ean} - marqué removed")
            skipped += 1
            continue
        
        # Skip products without name
        if not data.get("name") and not data.get("description"):
            print(f"[SKIP] {ean} - pas de nom/description")
            skipped += 1
            continue
        
        # Prepare product data
        product = {
            "ean": ean,
            "title": data.get("name") or data.get("description"),
            "brand": data.get("brand"),
            "quantity": data.get("quantity"),
            "image": data.get("image"),
            "source": data.get("source", "seed_catalog"),
            "note": data.get("note"),
            "nutriscore_grade": data.get("nutriscore_grade"),
            "nutriscore_image": data.get("nutriscore_image"),
            "ecoscore_grade": data.get("ecoscore_grade"),
            "ecoscore_image": data.get("ecoscore_image"),
            "nova_group": data.get("nova_group"),
            "categories": data.get("categories"),
            "queries": data.get("queries", {}),
            "negatives": data.get("negatives", {}),
            "seed_query": data.get("seed_query"),
            "seed_primary_name": data.get("seed_primary_name"),
            "seed_primary_quantity": data.get("seed_primary_quantity"),
        }
        
        # Add keywords
        keywords = []
        if data.get("primary_keywords"):
            keywords.extend(data["primary_keywords"])
        if data.get("secondary_keywords"):
            keywords.extend(data["secondary_keywords"])
        if data.get("leclerc_queries"):
            keywords.extend(data["leclerc_queries"])
        product["keywords"] = list(set(keywords))
        
        # Add store URLs
        stores = {}
        if data.get("auchan_url"):
            stores["auchan"] = {"url": data["auchan_url"]}
        if data.get("courseu_url"):
            stores["courseu"] = {"url": data["courseu_url"]}
        if stores:
            product["stores"] = stores
        
        # Add canonical if exists
        if data.get("canonical"):
            product["canonical"] = data["canonical"]
        
        # Upsert to MongoDB
        success = repo.upsert_product(ean, product)
        if success:
            print(f"[OK] {ean} - {product['title'][:50]}...")
            migrated += 1
        else:
            print(f"[FAIL] {ean}")
    
    print(f"\n{'='*50}")
    print(f"MIGRATION COMPLETE")
    print(f"Total: {total}")
    print(f"Migrated: {migrated}")
    print(f"Skipped: {skipped}")
    print(f"{'='*50}")

if __name__ == "__main__":
    migrate()
