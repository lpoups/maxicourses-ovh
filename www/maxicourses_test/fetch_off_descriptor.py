#!/usr/bin/env python3
import json
import os
import sys
import urllib.request


def main():
    ean = os.environ.get("EAN") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not ean:
        print("USAGE: fetch_off_descriptor.py <EAN>")
        sys.exit(2)
    url = f"https://world.openfoodfacts.org/api/v2/product/{ean}.json"
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.load(r)
    p = data.get("product", {})
    out = {
        "brand": p.get("brands"),
        "name": p.get("product_name"),
        "quantity": p.get("quantity"),
        "categories": p.get("categories"),
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main()

