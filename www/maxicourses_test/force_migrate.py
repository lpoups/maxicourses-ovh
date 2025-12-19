
import sys
import os
from descriptor_store import ProductRepository
from seed_catalog import all_seeds

repo = ProductRepository()

print("🚀 STARTING MIGRATION: Seed Catalog -> MongoDB")

if not repo.enabled:
    print("❌ DB Not Connected. Aborting.")
    sys.exit(1)

seeds = all_seeds()
total = len(seeds)
count = 0

for ean, data in seeds.items():
    print(f"[{count+1}/{total}] Migrating {ean}...")
    
    # Clean data: Remove None/Empty to prevent overwriting existing good data with garbage
    # But for migration, we want to ENFORCE seed data if it exists.
    # Actually, repo.upsert_product now (after my next edit) will be safe.
    # We just push the data.
    
    # We use direct update_one with upsert=True to bypass any "smart" logic for this raw import
    # Or strict upsert.
    
    # Let's use repo.upsert_product to benefit from standardized handling if any
    # But wait, we want to force this data IN.
    
    # Filter out 'removed' entries?
    if data.get('removed'):
        print(f"Skipping removed item {ean}")
        continue
        
    repo.upsert_product(ean, data)
    count += 1

print(f"✅ MIGRATION COMPLETE. {count} products imported.")
