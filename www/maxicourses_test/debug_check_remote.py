from descriptor_store import ProductRepository
import sys

repo = ProductRepository()
print(f"Checking count...")
try:
    c = repo.products.count_documents({})
    print(f"Total docs: {c}")
    print(f"Doc 3092718637033: {repo.get_product('3092718637033')}")
except Exception as e:
    print(f"Error: {e}")
