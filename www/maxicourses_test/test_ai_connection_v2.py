
import os
import sys
import json
from pathlib import Path
import logging

# Add project root to path
sys.path.append("/Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicourses_test")

# Mock Environment
os.environ["USE_AI_ASSIST"] = "1"

try:
    from ai_helpers import summarize_product_seed
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def test_ai():
    print("Testing AI connectivity with KEY...")
    
    seeds = [
        {
            "adapter": "carrefour_market",
            "payload": {
                "title": "Test Product",
                "brand": "TestBrand",
                "quantity": "100g",
                "description": "Just a test."
            }
        }
    ]
    
    context = {"descriptor": {"ean": "0000000000000"}}
    
    try:
        response = summarize_product_seed(seeds, context=context)
        print(f"Status: {response.status}")
        if response.status == "ok":
            print(" AI SUCCESS: Data received.")
        else:
            print(f" AI FAILURE: {response.error}")
    except Exception as e:
        print(f" Exception: {e}")

if __name__ == "__main__":
    test_ai()
