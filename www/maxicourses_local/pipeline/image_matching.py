"""Image hashing utilities shared across fetchers and finder pipeline.

The goal is to provide a single place where we compute perceptual hashes
for product images so that both Leclerc and Monoprix can fall back to
visual similarity when the EAN is missing.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union
import html
import io
import os

try:
    from PIL import Image  # type: ignore
    from PIL import ImageStat  # type: ignore
except ImportError:  # pragma: no cover - Pillow optional
    Image = None  # type: ignore
    ImageStat = None  # type: ignore

try:
    import requests
except ImportError:  # pragma: no cover - requests always available in env today
    requests = None  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
ASSETS_DIR = PIPELINE_DIR / "assets"

HashableRef = Union[str, Path]


def _normalize_ref(ref: Optional[str]) -> Optional[str]:
    if not isinstance(ref, str):
        return None
    cleaned = html.unescape(ref).strip()
    if not cleaned:
        return None
    compact = cleaned.replace(" ", "")
    return compact if compact else None


def _is_url(ref: str) -> bool:
    return ref.lower().startswith(("http://", "https://"))


def _resolve_local_path(ref: str) -> Optional[Path]:
    candidate = Path(ref)
    attempts = []
    if candidate.is_absolute():
        attempts.append(candidate)
    attempts.append((PIPELINE_DIR / candidate).resolve())
    attempts.append((PROJECT_ROOT / candidate).resolve())
    if ref.startswith("./"):
        attempts.append((PIPELINE_DIR / ref.lstrip("./")).resolve())
        attempts.append((PROJECT_ROOT / ref.lstrip("./")).resolve())
    if ref.startswith("../"):
        attempts.append((PIPELINE_DIR / ref).resolve())
        attempts.append((PROJECT_ROOT / ref).resolve())
    for path in attempts:
        try:
            if path.exists():
                return path
        except Exception:
            continue
    return None


def _average_hash(image, hash_size: int = 16) -> int:
    resample = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
    grayscale = image.convert("L").resize((hash_size, hash_size), resample=resample)
    pixels = list(grayscale.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for idx, pixel in enumerate(pixels):
        if pixel > avg:
            bits |= 1 << idx
    return bits


def _center_crop(image, fraction: float = 0.7):
    """Crop the central square region to focus on the product itself."""
    if fraction <= 0 or fraction > 1:
        return image
    w, h = image.size
    side = max(4, int(min(w, h) * fraction))
    if side >= min(w, h):
        return image
    left = (w - side) // 2
    top = (h - side) // 2
    return image.crop((left, top, left + side, top + side))


def _hash_variants(image) -> List[int]:
    base = _average_hash(image)
    cropped = _center_crop(image)
    if cropped is image:
        return [base]
    return [base, _average_hash(cropped)]


def _hash_distance(a: int, b: int) -> int:
    try:
        return (a ^ b).bit_count()
    except AttributeError:
        return bin(a ^ b).count("1")


@lru_cache(maxsize=256)
def _hash_local(path: Path) -> List[int]:
    if Image is None:
        return []
    try:
        with Image.open(path) as img:
            return _hash_variants(img)
    except Exception:
        return []


@lru_cache(maxsize=256)
def _hash_remote(url: str) -> List[int]:
    if Image is None or requests is None:
        return []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
    try:
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
    except Exception:
        return []
    try:
        with Image.open(io.BytesIO(response.content)) as img:
            return _hash_variants(img)
    except Exception:
        return []


def hash_reference(ref: Optional[str]) -> Optional[int]:
    """Return the primary perceptual hash for a reference string or None."""
    variants = hash_reference_variants(ref)
    return variants[0] if variants else None


def hash_reference_variants(ref: Optional[str]) -> List[int]:
    """Return both full-frame and center-crop hashes for a reference (paths or URLs)."""
    normalized = _normalize_ref(ref)
    if not normalized:
        return []
    if _is_url(normalized):
        return _hash_remote(normalized)
    local_path = _resolve_local_path(normalized)
    if local_path:
        return _hash_local(local_path)
    return []


def _color_signature(image) -> tuple:
    resized = image.convert("RGB").resize((32, 32), getattr(Image, "LANCZOS", Image.BICUBIC))
    stat_full = ImageStat.Stat(resized).mean
    upper_band = resized.crop((0, 0, 32, 12))
    stat_upper = ImageStat.Stat(upper_band).mean
    mid_band = resized.crop((0, 16, 32, 28))
    stat_mid = ImageStat.Stat(mid_band).mean
    left_band = resized.crop((0, 8, 6, 30))
    right_band = resized.crop((26, 8, 32, 30))
    stat_left = ImageStat.Stat(left_band).mean
    stat_right = ImageStat.Stat(right_band).mean
    return tuple(stat_full + stat_upper + stat_mid + stat_left + stat_right)


@lru_cache(maxsize=256)
def _color_local(path: Path) -> List[tuple]:
    if Image is None or ImageStat is None:
        return []
    try:
        with Image.open(path) as img:
            cropped = _center_crop(img)
            if cropped is img:
                return [_color_signature(img)]
            return [_color_signature(img), _color_signature(cropped)]
    except Exception:
        return []


@lru_cache(maxsize=256)
def _color_remote(url: str) -> List[tuple]:
    if Image is None or ImageStat is None or requests is None:
        return []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
    try:
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
    except Exception:
        return []
    try:
        with Image.open(io.BytesIO(response.content)) as img:
            cropped = _center_crop(img)
            if cropped is img:
                return [_color_signature(img)]
            return [_color_signature(img), _color_signature(cropped)]
    except Exception:
        return []


def color_reference(ref: Optional[str]) -> Optional[tuple]:
    variants = color_reference_variants(ref)
    return variants[0] if variants else None


def color_reference_variants(ref: Optional[str]) -> List[tuple]:
    normalized = _normalize_ref(ref)
    if not normalized:
        return []
    if _is_url(normalized):
        return _color_remote(normalized)
    local_path = _resolve_local_path(normalized)
    if local_path:
        return _color_local(local_path)
    return []


def compare_references(seed_ref: Optional[str], candidate_ref: Optional[str], *, threshold: int = 16) -> bool:
    """Compare two references (path or URL) and return True when distance ≤ threshold.

    We hash both the full frame and a center crop to focus on the actual product,
    then take the best (minimal) distance. Color signatures are also compared
    on the closest match to avoid background/edge noise.
    """
    seed_hashes = hash_reference_variants(seed_ref)
    candidate_hashes = hash_reference_variants(candidate_ref)
    if not seed_hashes or not candidate_hashes:
        return False

    min_distance = min(_hash_distance(s, c) for s in seed_hashes for c in candidate_hashes)
    if min_distance > threshold:
        return False

    seed_colors = color_reference_variants(seed_ref)
    candidate_colors = color_reference_variants(candidate_ref)
    if seed_colors and candidate_colors:
        min_color_delta = min(
            sum(abs(a - b) for a, b in zip(sc, cc)) / 3.0 for sc in seed_colors for cc in candidate_colors
        )
        if min_color_delta > 25:  # roughly 10% of 255 range
            return False
    return True


def descriptor_image_refs(descriptor: Optional[dict], ean: Optional[str]) -> List[str]:
    refs: List[str] = []
    if isinstance(descriptor, dict):
        img = descriptor.get("image")
        if isinstance(img, str) and img.strip():
            refs.append(img.strip())
        canonical = descriptor.get("canonical")
        if isinstance(canonical, dict):
            for url in canonical.get("images") or []:
                if isinstance(url, str) and url.strip():
                    refs.append(url.strip())
        ref_images = descriptor.get("reference_images")
        if isinstance(ref_images, (list, tuple)):
            for url in ref_images:
                if isinstance(url, str) and url.strip():
                    refs.append(url.strip())
        elif isinstance(ref_images, str) and ref_images.strip():
            refs.append(ref_images.strip())
    if ean:
        fallback = ASSETS_DIR / f"{ean}.jpg"
        if fallback.exists():
            refs.append(f"./assets/{fallback.name}")
    return list(dict.fromkeys(refs))  # keep order, remove duplicates


def descriptor_matches_candidate(descriptor: Optional[dict], candidate_ref: Optional[str], *, ean: Optional[str], threshold: int = 16) -> bool:
    for seed_ref in descriptor_image_refs(descriptor, ean):
        if compare_references(seed_ref, candidate_ref, threshold=threshold):
            return True
    return False
