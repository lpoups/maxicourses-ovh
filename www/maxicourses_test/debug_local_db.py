from descriptor_store import ProductRepository
import sys

repo = ProductRepository()
ean = "3092718637033"
print(f"Checking EAN {ean} in DB...")
try:
    doc = repo.get_product(ean)
    print(f"Result: {doc}")
except Exception as e:
    print(f"Error: {e}")

# Check count
try:
    print(f"Total docs: {repo.products.count_documents({})}")
except Exception as e:
    print(f"Count Error: {e}")
