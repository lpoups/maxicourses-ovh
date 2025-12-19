
import sys
import os
import json
from pathlib import Path

# Add the project root to sys.path
current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir.parent))

try:
    from maxicourses_test.server import ensure_manual_descriptor
    from maxicourses_test.descriptor_store import ProductRepository
except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)

def test_ean(ean):
    print(f"\n--- Testing EAN: {ean} ---")
    
    # Check if DB is reachable
    repo = ProductRepository()
    if not repo.enabled:
        print("WARNING: MongoDB not enabled/reachable. Test relies on DB.")
        return

    try:
        descriptor = ensure_manual_descriptor(ean)
        print("[OK] Descriptor retrieved.")
        
        # Check source
        print(f"Source: {descriptor.get('source')}")
        
        # Check Intermarché data
        queries = descriptor.get('queries', {})
        inter_queries = queries.get('intermarche', [])
        print(f"Intermarché Queries: {inter_queries}")
        
        inter_url = descriptor.get('intermarche_url')
        print(f"Intermarché URL: {inter_url}")
        
        # Verify if we have what we expect (assuming DB has data)
        if inter_queries or inter_url:
            print("[SUCCESS] Data found (likely from MongoDB).")
        else:
            print("[INFO] No Intermarché specific data found in this descriptor.")
            
    except Exception as e:
        print(f"[ERROR] Failed to get descriptor: {e}")

if __name__ == "__main__":
    # Test with Orangina EAN known to have data
    test_ean("3124480200433")
