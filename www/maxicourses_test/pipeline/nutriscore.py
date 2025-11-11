"""Utilities to extract Nutri-score information from store HTML."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional, Tuple
from urllib.parse import urljoin


IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
SRC_RE = re.compile(r'src\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
ALT_RE = re.compile(r'alt\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
DATA_ATTR_RE = re.compile(r'data-nutri(?:score)?\s*=\s*["\']?([abcde])', re.IGNORECASE)
JSON_RE = re.compile(r'"nutri(?:score|_score|Score)"\s*:\s*"?([abcde])"?', re.IGNORECASE)
TEXT_RE = re.compile(r'nutri[\w\s-]*(?:score)?[^a-z0-9]{0,3}([abcde])', re.IGNORECASE)
CANDIDATE_IMG_RE = re.compile(r'nutri[\w\-]*([abcde])', re.IGNORECASE)


def _normalize_grade(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    letter = value.strip().lower()
    if not letter:
        return None
    if letter[0] in "abcde":
        return letter[0]
    return None


def _absolutize(url: str, base_url: Optional[str]) -> str:
    if url.startswith("//"):
        return "https:" + url
    if base_url and url.startswith("/"):
        return urljoin(base_url, url)
    return url


def extract_nutriscore_from_html(html: Optional[str], *, base_url: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Return (grade, image_url) extracted from HTML if present."""
    if not html:
        return None, None
    grade: Optional[str] = None
    image: Optional[str] = None

    # Direct data attributes or JSON blocks
    direct = DATA_ATTR_RE.search(html) or JSON_RE.search(html)
    if direct:
        grade = _normalize_grade(direct.group(1))

    if grade is None:
        text_match = TEXT_RE.search(html)
        if text_match:
            grade = _normalize_grade(text_match.group(1))

    for tag in IMG_TAG_RE.findall(html):
        if "nutri" not in tag.lower():
            continue
        src_match = SRC_RE.search(tag)
        alt_match = ALT_RE.search(tag)
        tag_grade = None
        if alt_match:
            tag_grade = _normalize_grade(alt_match.group(1))
        if tag_grade is None and src_match:
            src_value = src_match.group(1)
            tag_grade = _normalize_grade(src_value)
            if tag_grade is None:
                m = CANDIDATE_IMG_RE.search(src_value)
                if m:
                    tag_grade = _normalize_grade(m.group(1))
        if grade is None and tag_grade:
            grade = tag_grade
        if src_match and not image:
            image = _absolutize(src_match.group(1), base_url)
        if grade and image:
            break

    return grade, image
