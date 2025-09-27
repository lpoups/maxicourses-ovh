#!/usr/bin/env python3
import sys
from pathlib import Path
from PIL import Image
import zxingcpp

def main():
    if len(sys.argv) < 2:
        print("USAGE: decode_ean.py <image_path>")
        sys.exit(2)
    p = Path(sys.argv[1])
    if not p.exists():
        print("ERR: file not found")
        sys.exit(1)
    img = Image.open(p).convert('RGB')
    res = zxingcpp.read_barcode(img)
    if not res:
        print("NO_BARCODE")
        sys.exit(3)
    print(res.text)

if __name__ == '__main__':
    main()

