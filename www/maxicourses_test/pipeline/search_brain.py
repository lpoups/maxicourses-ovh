
import os
import re
from typing import List, Dict, Any, Optional
import json

# Try to import from local modules, handling path if necessary
try:
    # Relative import when running as part of the package
    from ..ai_helpers import summarize_product_seed, USE_AI_ASSIST
    from .text_utils import normalize_text
    from ..descriptor_store import ProductRepository
except (ImportError, ValueError):
    try:
        # Fallback for when running from root or in weird context
        from maxicourses_test.ai_helpers import summarize_product_seed, USE_AI_ASSIST
        from maxicourses_test.pipeline.text_utils import normalize_text
        from maxicourses_test.descriptor_store import ProductRepository
    except ImportError:
         # Last resort (local dir same level)
         import sys
         # Hack for test scripts
         from ai_helpers import summarize_product_seed, USE_AI_ASSIST
         from pipeline.text_utils import normalize_text
         from descriptor_store import ProductRepository

class SearchBrain:
    """
    The Intelligence Center for generating search queries.
    Implements the 'Funnel Strategy':
    1. Golden Record (Previous Success)
    2. Strict Heuristics (Brand + Product + Size)
    3. Broad Heuristics (Brand + Product)
    4. AI Generation (Smart context analysis)
    """

    def __init__(self):
        self.repo = ProductRepository()

    def get_next_queries(self, descriptor: Dict[str, Any], store: str, iteration: int = 0) -> List[str]:
        """
        Returns a list of queries to try for a given iteration.
        Iteration 0: Golden Record (if any) or Best Heuristics.
        Iteration 1: Broader Heuristics.
        Iteration 2: AI Generation (if enabled).
        """
        
        ean = descriptor.get("ean")
        if not ean:
            return []

        # 1. Golden Record (Always priority if it exists and hasn't failed recently)
        if iteration == 0:
            golden = self.repo.get_product_field(ean, f"queries.{store}")
            if golden:
                # If we have a saved working query, allow it alone first
                return [golden] if isinstance(golden, str) else golden

        # Prepare basics
        brand = descriptor.get("brand") or ""
        name = descriptor.get("name") or descriptor.get("product_name") or ""
        quantity = descriptor.get("quantity") or ""
        
        # Clean up
        brand = brand.strip()
        # Remove 'Unknown' brands
        if brand.lower() in ["unknown", "generic", ""]:
            brand = ""
            
        # 2. Heuristic Strategies
        heuristics = []
        
        # Dispatch to store-specific heuristics if available
        if hasattr(self, f"_generate_{store}_heuristics"):
            heuristics = getattr(self, f"_generate_{store}_heuristics")(descriptor)
        else:
             heuristics = self._generate_default_heuristics(descriptor)

        # Clean duplicates and empty
        heuristics = sorted(list(set([h.strip() for h in heuristics if h.strip()])))

        if iteration == 0:
             # If no golden, return top 2 heuristics
             return heuristics[:2]
        
        if iteration == 1:
             # Return remaining heuristics
             return heuristics[2:]

        # 3. AI Strategy (The "Big Gun")

        # 3. AI Strategy (The "Big Gun")
        if iteration == 2:
            return self._generate_ai_queries(descriptor)

        # 3. Confirmed Store Titles (High Precision)
        if iteration == 0 and not heuristics:
             # Check if we have high-quality titles from other stores
             confirmed_titles = self.repo.get_product_field(ean, "confirmed_titles")
             if isinstance(confirmed_titles, dict):
                 for other_store, title in confirmed_titles.items():
                     if title and len(title) > 5:
                         heuristics.append(title)  # Use exact title from another store

        return []

    def _generate_ai_queries(self, descriptor: Dict[str, Any]) -> List[str]:
        """
        Uses OpenAI/Gemini to analyze context and generate smart queries.
        """
        # Ensure we have a list format for summarize_product_seed
        # It expects a list of seed payloads.
        seeds = [descriptor]
        
        print(f"[Brain] Invoking AI for EAN {descriptor.get('ean')}...")
        response = summarize_product_seed(seeds, context={"descriptor": descriptor})
        
        if response.status == "ok":
            print(f"[Brain] AI generated queries: {response.data.get('keywords')}")
            return response.data.get("keywords", [])
        else:
            print(f"[Brain] AI failed or disabled: {response.error}")
            return []

    def record_success(self, ean: str, store: str, query: str):
        """
        Saves the winning query to DB as a Golden Record.
        """
        if not query or not ean:
            return
        print(f"[Brain] 🎯 Saving WINNING query for {store}: '{query}'")
        self.repo.update_product_field(ean, f"queries.{store}", query)
    
    def record_confirmed_product_details(self, ean: str, store: str, title: str):
        """
        Saves the exact TITLE of a confirmed product.
        This allows future searches (for this or other stores) to use this high-quality signal.
        """
        if not title or not ean or not store:
            return
            
        print(f"[Brain] 🧠 Learning from success: {store} -> '{title}'")
        
        # 1. Save strictly as confirmed title for this store
        self.repo.update_product_field(ean, f"confirmed_titles.{store}", title)
        
        # 2. Also inject as a keyword if unique
        # This helps "Broad" searches for new stores
        normalized = normalize_text(title)
        if normalized:
             # Just add to keywords list
             # Ideally we use $addToSet but update_product_keywords handles logic?
             # For now, let's just push it to confirmed_titles, 
             # and let get_next_queries read from it.
             pass

    def _generate_default_heuristics(self, descriptor: Dict[str, Any]) -> List[str]:
        brand = descriptor.get("brand") or ""
        name = descriptor.get("name") or descriptor.get("product_name") or ""
        quantity = descriptor.get("quantity") or ""
        brand = brand.strip()
        
        if brand.lower() in ["unknown", "generic", ""]:
            brand = ""
            
        heuristics = []
        name_tokens = [w for w in re.split(r'\s+', name) if len(w) > 2 and not w.isdigit()]
        
        if brand:
            base = f"{brand} {' '.join(name_tokens[:2])}"
            heuristics.append(base)
            heuristics.append(f"{brand} {' '.join(name_tokens[:3])}")
            if len(brand) > 3 or quantity:
                heuristics.append(f"{brand} {quantity}")
        else:
            heuristics.append(f"{' '.join(name_tokens[:3])} {quantity}")
            heuristics.append(f"{' '.join(name_tokens[:4])}")
            
        return heuristics

    def _generate_monoprix_heuristics(self, descriptor: Dict[str, Any]) -> List[str]:
        """
        Monoprix Special: No weight/volume (500g, 1l) but KEEP pack counts (6x33cl).
        """
        brand = descriptor.get("brand") or ""
        name = descriptor.get("name") or descriptor.get("product_name") or ""
        quantity = descriptor.get("quantity") or ""
        
        if brand.lower() in ["unknown", "generic", ""]:
            brand = ""

        # Filter quantity
        # Regex for "number + unit" (plain), check text_utils
        # We want to exclude "750 g", "1.5 l"
        # But keep "6x33cl", "6 x 33 cl"
        
        is_pack = False
        if quantity:
             # Heuristic: contains 'x' or 'X' between numbers?
             if re.search(r'\d\s*[xX]\s*\d', quantity):
                 is_pack = True
        
        filtered_qty = quantity if is_pack else ""
        
        heuristics = []
        name_tokens = [w for w in re.split(r'\s+', name) if len(w) > 2 and not w.isdigit()]
        
        if brand:
            heuristics.append(f"{brand} {' '.join(name_tokens[:2])}")
            heuristics.append(f"{brand} {' '.join(name_tokens[:3])}")
            if filtered_qty:
                heuristics.append(f"{brand} {filtered_qty}")
        else:
             # If no brand, keeping quantity might be risky if we strip it, but allowed if pack
             if filtered_qty:
                 heuristics.append(f"{' '.join(name_tokens[:3])} {filtered_qty}")
             else:
                 heuristics.append(f"{' '.join(name_tokens[:3])}")
                 
        return heuristics
