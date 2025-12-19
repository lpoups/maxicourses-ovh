
import sys
import os
from descriptor_store import ProductRepository

ean = "8711000705094"
repo = ProductRepository()

print(f"Repairing {ean}...")
if repo.enabled:
    res = repo.products.update_one({"ean": ean}, {"$unset": {"image": ""}})
    print(f"Matched: {res.matched_count}, Modified: {res.modified_count}")
    
    # Verify
    prod = repo.get_product(ean)
    print(f"New Image: {prod.get('image')}")
else:
    print("DB Not enabled")
