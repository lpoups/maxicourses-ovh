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
    return cleaned or None


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


def _hash_distance(a: int, b: int) -> int:
    try:
        return (a ^ b).bit_count()
    except AttributeError:
        return bin(a ^ b).count("1")


@lru_cache(maxsize=256)
def _hash_local(path: Path) -> Optional[int]:
    if Image is None:
        return None
    try:
        with Image.open(path) as img:
            return _average_hash(img)
    except Exception:
        return None


@lru_cache(maxsize=256)
def _hash_remote(url: str) -> Optional[int]:
    if Image is None or requests is None:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
    try:
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
    except Exception:
        return None
    try:
        with Image.open(io.BytesIO(response.content)) as img:
            return _average_hash(img)
    except Exception:
        return None


def hash_reference(ref: Optional[str]) -> Optional[int]:
    """Return the perceptual hash for a reference string or None.

    The reference can be either a relative path (e.g. ``./assets/xxx.jpg``)
    or a remote HTTP(S) URL.
    """
    normalized = _normalize_ref(ref)
    if not normalized:
        return None
    if _is_url(normalized):
        return _hash_remote(normalized)
    local_path = _resolve_local_path(normalized)
    if local_path:
        return _hash_local(local_path)
    return None


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
def _color_local(path: Path) -> Optional[tuple]:
    if Image is None or ImageStat is None:
        return None
    try:
        with Image.open(path) as img:
            return _color_signature(img)
    except Exception:
        return None


@lru_cache(maxsize=256)
def _color_remote(url: str) -> Optional[tuple]:
    if Image is None or ImageStat is None or requests is None:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
    try:
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
    except Exception:
        return None
    try:
        with Image.open(io.BytesIO(response.content)) as img:
            return _color_signature(img)
    except Exception:
        return None


def color_reference(ref: Optional[str]) -> Optional[tuple]:
    normalized = _normalize_ref(ref)
    if not normalized:
        return None
    if _is_url(normalized):
        return _color_remote(normalized)
    local_path = _resolve_local_path(normalized)
    if local_path:
        return _color_local(local_path)
    return None


def compare_references(seed_ref: Optional[str], candidate_ref: Optional[str], *, threshold: int = 16) -> bool:
    """Compare two references (path or URL) and return True when distance ≤ threshold."""
    first = hash_reference(seed_ref)
    second = hash_reference(candidate_ref)
    if first is None or second is None:
        return False
    if _hash_distance(first, second) > threshold:
        return False
    seed_color = color_reference(seed_ref)
    candidate_color = color_reference(candidate_ref)
    if seed_color and candidate_color:
        color_delta = sum(abs(a - b) for a, b in zip(seed_color, candidate_color)) / 3.0
        if color_delta > 25:  # roughly 10% of 255 range
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
