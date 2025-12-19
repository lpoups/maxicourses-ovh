
import sys
import os
from pathlib import Path

# Add project root to path
current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir.parent))

from maxicourses_test.descriptor_store import ProductRepository

def check_product(ean):
    repo = ProductRepository()
    if not repo.enabled:
        print("[ERROR] MongoDB not enabled.")
        return

    product = repo.get_product(ean)
    if not product:
        print(f"[ERROR] Product {ean} not found in DB.")
        return

    print(f"--- Product {ean} ---")
    print(f"Source: {product.get('source')}")
    
    queries = product.get("queries")
    print(f"Queries Raw: {queries}")
    
    if isinstance(queries, dict):
        inter = queries.get("intermarche")
        print(f"Intermarché Queries: {inter}")
    else:
        print("Queries field is not a dict or missing.")

if __name__ == "__main__":
    check_product("3124480200433") # Orangina
