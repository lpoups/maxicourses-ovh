#!/usr/bin/env python3
"""
Bulk Ingest Tool
----------------
Ingests a CSV file (format: EAN;Name;Quantity) into MongoDB.
Sets status='NEW' to trigger AI Enrichment.

Usage:
  python3 ingest_csv.py /path/to/file.csv [--brand default_brand]
"""
import sys
import os
import csv
import argparse
from typing import Optional

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__)))

from descriptor_store import ProductRepository

def ingest_file(filepath: str, default_brand: Optional[str] = None):
    repo = ProductRepository()
    if not repo.enabled:
        print("[FATAL] MongoDB not connected.")
        sys.exit(1)
        
    count_new = 0
    count_skip = 0
    
    with open(filepath, 'r', encoding='utf-8') as f:
        # Auto-detect delimiter
        sample = f.read(1024)
        f.seek(0)
        sniffer = csv.Sniffer()
        try:
            dialect = sniffer.sniff(sample)
        except csv.Error:
            dialect = 'excel' # Fallback
            
        reader = csv.reader(f, dialect)
        
        for row in reader:
            if not row: continue
            
            # Basic Heuristic to map columns
            # Assumption: EAN is usually first or longest numeric
            # If header present, skip it?
            if "ean" in str(row[0]).lower():
                continue
                
            ean = row[0].strip()
            name = row[1].strip() if len(row) > 1 else "Unknown"
            quantity = row[2].strip() if len(row) > 2 else None
            
            # Check if exists
            existing = repo.get_product(ean)
            if existing:
                print(f"[SKIP] {ean} already exists.")
                count_skip += 1
                continue
                
            # Create Payload
            payload = {
                "ean": ean,
                "title": name,
                "quantity": quantity,
                "brand": default_brand,
                "source": "bulk_import",
                "status": "NEW", # Triggers AI
                "ai_enriched": False,
                "created_at": None # Will be set by store
            }
            
            if repo.upsert_product(ean, payload):
                print(f"[NEW] Imported {ean} - {name}")
                count_new += 1
                
    print(f"--- Import Complete ---")
    print(f"New: {count_new}")
    print(f"Skipped: {count_skip}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="Path to CSV file")
    parser.add_argument("--brand", help="Default brand if missing", default=None)
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"File not found: {args.file}")
        sys.exit(1)
        
    ingest_file(args.file, args.brand)
