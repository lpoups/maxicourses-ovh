#!/usr/bin/env python3
"""Utility helpers to decode EAN barcodes from images."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, Optional

from PIL import Image, ImageOps
import zxingcpp


PREFERRED_LENGTHS: tuple[int, ...] = (13, 8)


def _sanitize_digits(value: str) -> str:
    return ''.join(ch for ch in value if ch.isdigit())


def _preferred_formats() -> zxingcpp.BarcodeFormats:
    formats = zxingcpp.BarcodeFormats(zxingcpp.BarcodeFormat.EAN13)
    for fmt in (
        zxingcpp.BarcodeFormat.EAN8,
        zxingcpp.BarcodeFormat.UPCA,
        zxingcpp.BarcodeFormat.UPCE,
    ):
        formats |= fmt
    return formats


def decode_image_to_ean(
    image_path: Path | str,
    *,
    preferred_lengths: Iterable[int] = PREFERRED_LENGTHS,
) -> Optional[str]:
    """Return the first detected EAN/UPC value, en essayant plusieurs rotations."""

    img = Image.open(image_path)
    formats = _preferred_formats()
    ordered_lengths = tuple(dict.fromkeys(list(preferred_lengths) + [13, 8]))

    def attempt(image: Image.Image) -> Optional[str]:
        results = zxingcpp.read_barcodes(image, formats=formats, try_rotate=True, try_downscale=True)
        for length in ordered_lengths:
            for res in results:
                digits = _sanitize_digits(res.text or '')
                if len(digits) == length:
                    return digits
        res = zxingcpp.read_barcode(image, formats=formats)
        if res and res.text:
            digits = _sanitize_digits(res.text)
            if digits:
                return digits
        return None

    base = img.convert('RGB')
    variants = []
    grayscale = base.convert('L')
    variants.append(base)
    variants.append(grayscale)
    variants.append(ImageOps.autocontrast(grayscale))
    variants.append(ImageOps.equalize(grayscale))

    for variant in variants:
        for scale in (1.0, 1.5, 2.0):
            if scale != 1.0:
                width, height = variant.size
                scaled = variant.resize((int(width * scale), int(height * scale)), Image.BICUBIC)
            else:
                scaled = variant
            result = attempt(scaled)
            if result:
                return result
            for angle in (90, 180, 270):
                rotated = scaled.rotate(angle, expand=True)
                result = attempt(rotated)
                if result:
                    return result
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("USAGE: decode_ean.py <image_path>")
        return 2

    path = Path(argv[1])
    if not path.exists():
        print("ERR: file not found")
        return 1

    result = decode_image_to_ean(path)
    if not result:
        print("NO_BARCODE")
        return 3
    print(result)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
