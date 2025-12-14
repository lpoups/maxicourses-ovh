import math
import shutil
import logging
from pathlib import Path
from typing import Optional, Tuple
from urllib.request import Request, urlopen
from PIL import Image, ImageChops

logger = logging.getLogger("VisionEngine")

def download_image(url: str, target_path: Path) -> bool:
    """Download image from URL to target path."""
    if not url or not target_path:
        return False
        
    try:
        # Fake User-Agent to avoid simple blockers
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=5) as response:
            if response.status != 200:
                return False
            data = response.read()
            target_path.write_bytes(data)
        return True
    except Exception as e:
        logger.warning(f"Failed to download image {url}: {e}")
        return False

def compare_images(path_a: Path, path_b: Path) -> float:
    """
    Compare two images and return a similarity score (0.0 to 1.0).
    Uses Histogram Intersection on normalized 64x64 grayscale images.
    """
    if not path_a.exists() or not path_b.exists():
        return 0.0
        
    try:
        # Open and normalize
        img1 = Image.open(path_a).convert("L").resize((64, 64))
        img2 = Image.open(path_b).convert("L").resize((64, 64))
        
        # Histograms
        h1 = img1.histogram()
        h2 = img2.histogram()
        
        # Histogram Intersection
        # Sum of min(h1[i], h2[i]) / Sum of h1[i]
        # This is a robust way to compare color/intensity distribution
        intersection = sum(min(a, b) for a, b in zip(h1, h2))
        union = sum(h1) # Should be 64*64
        
        if union == 0:
            return 0.0
            
        score = intersection / union
        return score
        
    except Exception as e:
        logger.error(f"Comparison failed: {e}")
        return 0.0
