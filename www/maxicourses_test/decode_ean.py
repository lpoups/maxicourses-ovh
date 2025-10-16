#!/usr/bin/env python3
"""Utility helpers to decode EAN barcodes from images."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, Optional

from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import zxingcpp


PREFERRED_LENGTHS: tuple[int, ...] = (13,)


def _edge_based_regions(image: Image.Image) -> list[Image.Image]:
    """Heuristically crop areas with strong vertical edges (likely barcode zone)."""

    grey = ImageOps.grayscale(image)
    edges = ImageOps.autocontrast(grey.filter(ImageFilter.FIND_EDGES))
    width, height = edges.size
    data = list(edges.getdata())
    if not data:
        return []

    row_sums = [0] * height
    col_sums = [0] * width
    for idx, value in enumerate(data):
        row = idx // width
        col = idx % width
        row_sums[row] += value
        col_sums[col] += value

    max_row = max(row_sums) if row_sums else 0
    max_col = max(col_sums) if col_sums else 0
    if max_row == 0 or max_col == 0:
        return []

    regions: list[Image.Image] = []
    seen: set[tuple[int, int, int, int]] = set()

    for row_ratio, col_ratio in ((0.55, 0.55), (0.45, 0.45), (0.35, 0.35)):
        row_threshold = max_row * row_ratio
        col_threshold = max_col * col_ratio

        row_indices = [i for i, val in enumerate(row_sums) if val >= row_threshold]
        col_indices = [i for i, val in enumerate(col_sums) if val >= col_threshold]
        if not row_indices or not col_indices:
            continue

        top = max(0, min(row_indices) - 12)
        bottom = min(height, max(row_indices) + 12)
        left = max(0, min(col_indices) - 12)
        right = min(width, max(col_indices) + 12)

        if bottom - top < 40 or right - left < 80:
            continue

        box = (left, top, right, bottom)
        if box in seen:
            continue
        seen.add(box)

        regions.append(image.crop(box))

    return regions


def _sanitize_digits(value: str) -> str:
    return ''.join(ch for ch in value if ch.isdigit())


def _add_margin(image: Image.Image, left: int, top: int, right: int, bottom: int, fill) -> Image.Image:
    width, height = image.size
    new_img = Image.new(image.mode, (width + left + right, height + top + bottom), fill)
    new_img.paste(image, (left, top))
    return new_img


def _augment_variant(image: Image.Image) -> list[Image.Image]:
    """Generate pre-processing variants that help ZXing decode stubborn barcodes."""

    augmented: list[Image.Image] = []
    width, height = image.size
    min_side = max(1, min(width, height))
    border = max(12, int(min_side * 0.12))
    fill = 255 if image.mode in ("L", "I", "F") else (255, 255, 255)

    try:
        augmented.append(ImageEnhance.Sharpness(image).enhance(2.0))
    except Exception:
        pass
    try:
        augmented.append(image.filter(ImageFilter.SHARPEN))
    except Exception:
        pass
    try:
        augmented.append(ImageOps.autocontrast(image))
    except Exception:
        pass
    try:
        augmented.append(ImageOps.expand(image, border=border, fill=fill))
    except Exception:
        pass
    try:
        augmented.append(_add_margin(image, border * 2, border, border, border, fill))
    except Exception:
        pass
    try:
        augmented.append(_add_margin(image, border * 3, border * 2, border, border * 2, fill))
    except Exception:
        pass
    for factor in (2.3, 2.6, 3.0):
        try:
            augmented.append(ImageEnhance.Contrast(image).enhance(factor))
        except Exception:
            pass
    try:
        augmented.append(image.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=3)))
    except Exception:
        pass
    for factor in (0.9, 1.1):
        try:
            augmented.append(ImageEnhance.Brightness(image).enhance(factor))
        except Exception:
            pass
    return [img for img in augmented if img is not None]


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
    ordered_lengths = tuple(dict.fromkeys(list(preferred_lengths) + [13]))

    seen_candidates: list[str] = []

    def _debug_candidate(value: str) -> None:
        if value and value not in seen_candidates:
            seen_candidates.append(value)

    def _read_barcodes(image: Image.Image):
        common_kwargs = {
            "formats": formats,
            "try_rotate": True,
            "try_downscale": True,
        }
        extended_kwargs = dict(common_kwargs)
        extended_kwargs.update({"try_harder": True, "try_invert": True})
        try:
            return zxingcpp.read_barcodes(image, **extended_kwargs)
        except TypeError:
            return zxingcpp.read_barcodes(image, **common_kwargs)

    def _read_barcode(image: Image.Image):
        common_kwargs = {"formats": formats}
        extended_kwargs = dict(common_kwargs)
        extended_kwargs.update({"try_harder": True})
        try:
            return zxingcpp.read_barcode(image, **extended_kwargs)
        except TypeError:
            return zxingcpp.read_barcode(image, **common_kwargs)

    candidate_votes: dict[str, int] = {}

    def register_candidate(value: str) -> None:
        if not value:
            return
        candidate_votes[value] = candidate_votes.get(value, 0) + 1

    def attempt(image: Image.Image) -> None:
        results = _read_barcodes(image)
        for res in results:
            digits = _sanitize_digits(res.text or '')
            if not digits:
                continue
            if len(digits) == 13 and res.format == zxingcpp.BarcodeFormat.EAN13:
                register_candidate(digits)
                continue
            _debug_candidate(digits)
        res = _read_barcode(image)
        if res and res.text:
            digits = _sanitize_digits(res.text)
            if digits and len(digits) == 13 and res.format == zxingcpp.BarcodeFormat.EAN13:
                register_candidate(digits)
                return
            _debug_candidate(digits)
        return

    base = img.convert('RGB')
    grayscale = base.convert('L')

    base = img.convert('RGB')
    grayscale = base.convert('L')

    variants = [
        base,
        grayscale,
        ImageOps.autocontrast(grayscale),
        ImageOps.equalize(grayscale),
        ImageEnhance.Contrast(grayscale).enhance(1.8),
        ImageEnhance.Contrast(grayscale).enhance(2.3),
    ]

    enriched_variants: list[Image.Image] = []
    for variant in variants:
        enriched_variants.append(variant)
        enriched_variants.extend(_augment_variant(variant))
        try:
            enriched_variants.append(ImageOps.mirror(variant))
        except Exception:
            pass
    variants = enriched_variants

    # Try focused crops around edge-heavy areas (likely barcode zone)
    for region in _edge_based_regions(base):
        grey_region = ImageOps.grayscale(region)
        variants.extend(
            [
                region,
                grey_region,
                ImageOps.autocontrast(grey_region),
                ImageOps.equalize(grey_region),
                ImageEnhance.Contrast(grey_region).enhance(2.0),
            ]
        )
        for extra in _augment_variant(grey_region):
            variants.append(extra)
        for extra in _augment_variant(region):
            variants.append(extra)

    for variant in variants:
        for scale in (1.0, 1.35, 1.5, 1.75, 2.0, 2.5, 3.0):
            for stretch in (1.0, 1.12, 1.25):
                if scale != 1.0 or stretch != 1.0:
                    width, height = variant.size
                    scaled = variant.resize((int(width * scale * stretch), int(height * scale)), Image.BICUBIC)
                else:
                    scaled = variant
                attempt(scaled)
                for angle in (-10, -8, -6, -5, -4, -3, -2, -1, 0.5, 1, 2, 3, 4, 5, 6, 8, 10, 90, 180, 270):
                    rotated = scaled.rotate(angle, expand=True)
                    attempt(rotated)
                if candidate_votes:
                    break
        if candidate_votes:
            break
    if candidate_votes:
        best = max(candidate_votes.items(), key=lambda item: (item[1], item[0]))
        if best[1] > 1:
            return best[0]
        # single vote → prefer first candidate in votes order
        return best[0]
    if seen_candidates:
        print(f"[decode_image_to_ean] rejected candidates: {seen_candidates}", file=sys.stderr)
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
