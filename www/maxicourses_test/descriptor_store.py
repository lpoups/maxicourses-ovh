# descriptor_store.py
# Source de vérité des descriptifs produits : MongoDB (Golden Record)
# Fallback : seed_catalog.py (Bootstrap seulement)

from __future__ import annotations

import os
import copy
import logging
from typing import Any, Dict, Optional, Set, List
from datetime import datetime

# Try importing pymongo, fail gracefully if not installed (for transitional states)
try:
    from pymongo import MongoClient
    from pymongo.collection import Collection
    HAS_MONGO = True
except ImportError:
    HAS_MONGO = False



# Feature Flag for Transition
USE_MONGO = os.getenv("USE_MONGO", "true").lower() in {"1", "true", "yes"}
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("MONGO_DB", "maxicourses")

try:
    from pipeline.normalizer import normalize_product
except ImportError:
    def normalize_product(d): return ""

logger = logging.getLogger("ProductRepository")

class ProductRepository:
    _instance = None
    
    def find_substitutes(self, ean: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Find cheaper valid substitutes for a given EAN."""
        if not self.enabled or self.products is None:
            return []
            
        # 1. Get Source Product
        source = self.get_product(ean)
        if not source:
            return []
            
        # 2. Get Signature
        sig = source.get("canonical", {}).get("normalized_signature")
        if not sig:
            # Try to compute it on the fly if missing
            sig = normalize_product(source)
            if not sig:
                return []
                
        # 3. Query
        # We want same signature, different EAN
        # Sort logic: we don't track price in Golden Record directly yet (stored in stores json?).
        # Ideally we'd sort by price.
        # For MVP, just return matching products.
        cursor = self.products.find({
            "canonical.normalized_signature": sig,
            "ean": {"$ne": ean},
            "removed": {"$ne": True}
        }).limit(limit)
        
        return list(cursor)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ProductRepository, cls).__new__(cls)
            cls._instance._init_db()
        return cls._instance

    def _init_db(self):
        self.db = None
        self.products: Optional[Collection] = None
        self.enabled = False

        if not HAS_MONGO:
            print("WARNING:ProductRepository:pymongo not installed, Repository disabled.")
            return

        if not USE_MONGO:
            print("WARNING:ProductRepository:USE_MONGO=False, Repository disabled.")
            return

        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
            # Quick check
            client.server_info()
            self.db = client[DB_NAME]
            self.products = self.db["products"]
            self.enabled = True
            print(f"INFO:ProductRepository:Connected to MongoDB [{DB_NAME}]")
            
            # Ensure index on EAN
            self.products.create_index("ean", unique=True)
            self.products.create_index("keywords")
            
            # Phase 7: Canonical Index for Substitution
            self.products.create_index("canonical.normalized_signature")
            
            # Phase 8: AI & Scale
            self.products.create_index("status")
            self.products.create_index("ai_enriched")
            
        except Exception as e:
            print(f"ERROR:ProductRepository:Connection failed: {e}")
            self.enabled = False

    def get_cheapest_substitute(self, ean: str) -> Optional[Dict[str, Any]]:
        """
        Finds the absolute cheapest substitute across all stores.
        Returns a dict with: {product_title, brand, store, price, unit_price, url, is_substitute}
        """
        if not self.enabled:
            return None
            
        # 1. Source Product
        source = self.get_product(ean)
        if not source:
            return None
            
        # 2. Get Substitutes (Phase 7)
        # Using a limit of 10 to check a good range, though more candidates = better price chance.
        substitutes = self.find_substitutes(ean, limit=20)
        
        candidates = [source] + substitutes
        offers = [] # List of tuples/dicts to sort
        
        for p in candidates:
            # Check fields
            p_ean = p.get("ean", "")
            p_title = p.get("title", "Unknown")
            p_brand = p.get("brand", "Unknown")
            p_image = p.get("image") or p.get("image_url")
            
            is_sub = (p_ean != ean)
            
            stores = p.get("stores", {})
            for store_name, data in stores.items():
                price = data.get("price")
                if not isinstance(price, (int, float)):
                     # Try parsing "1.20€" ? Usually we store floats/null.
                     continue
                
                # We assume quantities are normalized for substitutes (same canonical signature)
                # So we can compare price directly.
                # Ideally we calculate price_per_unit if quantity is known.
                
                offers.append({
                    "ean": p_ean,
                    "title": p_title,
                    "brand": p_brand,
                    "image": p_image,
                    "store": store_name,
                    "price": float(price),
                    "url": data.get("url"),
                    "is_substitute": is_sub
                })
        
        if not offers:
            return None
            
        # Sort by Price ASC
        offers.sort(key=lambda x: x["price"])
        
        return offers[0]

    def _init_db(self):
        self.db = None
        self.products: Optional[Collection] = None
        self.enabled = False

        if not HAS_MONGO:
            print("WARNING:ProductRepository:pymongo not installed, Repository disabled.")
            return

        if not USE_MONGO:
            print("WARNING:ProductRepository:USE_MONGO=False, Repository disabled.")
            return

        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
            # Quick check
            client.server_info()
            self.db = client[DB_NAME]
            self.products = self.db["products"]
            self.enabled = True
            print(f"INFO:ProductRepository:Connected to MongoDB [{DB_NAME}]")
            
            # Ensure index on EAN
            self.products.create_index("ean", unique=True)
            self.products.create_index("keywords")
            
            # Phase 7: Canonical Index for Substitution
            self.products.create_index("canonical.normalized_signature")
            
        except Exception as e:
            print(f"ERROR:ProductRepository:Connection failed: {e}")
            self.enabled = False

    def get_product(self, ean: str) -> Optional[Dict[str, Any]]:
        """Retrieve a product by EAN (Classic Dict format)."""
        ean = _normalize_ean(ean)
        if not self.enabled or self.products is None:
            return None
        
        try:
            doc = self.products.find_one({"ean": ean})
            if doc:
                 return self._serialize(doc)
        except Exception as e:
            logger.error(f"DB Read Error {ean}: {e}")

        # No fallback, strict DB logic
        return None

    def get_product_field(self, ean: str, field: str) -> Any:
        """Retrieve a specific field (dot notation supported) from a product."""
        ean = _normalize_ean(ean)
        if not self.enabled or self.products is None:
            return None
        
        try:
            doc = self.products.find_one({"ean": ean}, {field: 1, "_id": 0})
            if not doc:
                return None
            
            # Navigate nested result
            parts = field.split('.')
            current = doc
            for p in parts:
                if isinstance(current, dict):
                    current = current.get(p)
                else:
                    return None
            return current
        except Exception as e:
            logger.error(f"DB Read Field Error {ean} {field}: {e}")
            return None

    def update_product_field(self, ean: str, field: str, value: Any) -> bool:
        """Update a specific field (or dot.notation path) for a product."""
        ean = _normalize_ean(ean)
        if not ean or not self.enabled or self.products is None:
            return False
            
        try:
             self.products.update_one(
                 {"ean": ean}, 
                 {"$set": {field: value, "updated_at": datetime.utcnow()}}, 
                 upsert=True
             )
             return True
        except Exception as e:
             logger.error(f"DB Field Update Error {ean} {field}: {e}")
             return False

    def upsert_product(self, ean: str, data: Dict[str, Any]) -> bool:
        """Create or Update a product Golden Record."""
        ean = _normalize_ean(ean)
        if not ean or not self.enabled or self.products is None:
            return False

        now = datetime.utcnow()
        payload = copy.deepcopy(data)
        
        # PROTECT CRITICAL FIELDS: Do not allow empty strings to overwrite existing data via $set
        protected_fields = {"image", "title", "name", "brand", "quantity", "image_url"}
        
        # Prepare specific fields ensuring schemas match
        update_doc = {
            "$set": {
                "ean": ean,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now
            }
        }
        
        # Merge top level known fields with Protection
        for field in ["title", "brand", "quantity", "image_url", "image", "source", "note", "raw_text", "nutriscore_grade", "nutriscore_image", "ecoscore_grade", "ecoscore_image", "nova_group", "categories", "status", "ai_enriched", "last_ai_check"]:
            if field in payload: 
                val = payload[field]
                # HARDENING: If field is critical and value is empty, SKIP IT.
                if field in protected_fields and not val:
                    continue
                
                # [NEW] IMAGE PRIORITY LOGIC
                if field == "image" or field == "image_url":
                    # Priority config (Higher is better)
                    PRIORITY_MAP = {
                        "carrefour": 10,
                        "courseu": 9,
                        "chronodrive": 8,
                        "auchan": 7,
                        "g20": 6,
                        "generic": 1  # Default for unknown
                    }
                    
                    # Determine new source priority
                    new_source = payload.get("store") or payload.get("source") or "generic"
                    new_source_norm = str(new_source).split()[0].lower() # e.g. "carrefour market" -> "carrefour"
                    new_prio = 0
                    for k, p in PRIORITY_MAP.items():
                        if k in new_source_norm:
                            new_prio = p
                            break
                    
                    # Determine existing source priority
                    # Requires fetching existing 'image_source' or inferring from history?
                    # For now, we store 'image_source' in DB.
                    existing_doc = self.products.find_one({"ean": ean}, {"image_source": 1, "image": 1})
                    
                    should_update = True
                    if existing_doc and existing_doc.get("image"):
                        existing_src_val = existing_doc.get("image_source", "generic")
                        existing_prio = 0
                        for k, p in PRIORITY_MAP.items():
                             if k in existing_src_val:
                                 existing_prio = p
                                 break
                        
                        # LOGIC: Only overwrite if New Priority > Existing Priority
                        # Exception: If priority is equal, we can update? Maybe not to avoid thrashing.
                        # Strict User Request: Priority Order.
                        if new_prio < existing_prio:
                            should_update = False
                            # print(f"DEBUG: Skipping image update from {new_source} ({new_prio}) vs {existing_src_val} ({existing_prio})")

                    if should_update:
                        update_doc["$set"][field] = val
                        # Also save the source of this image for future comparisons
                        update_doc["$set"]["image_source"] = new_source_norm
                    
                    continue


                update_doc["$set"][field] = val
                
        # Merge complex fields like 'stores' (links) and 'keywords'
        if "keywords" in payload:
            update_doc["$set"]["keywords"] = payload["keywords"]
            
        if "queries" in payload:
            if isinstance(payload["queries"], dict):
                for k, v in payload["queries"].items():
                    update_doc["$set"][f"queries.{k}"] = v
            else:
                 update_doc["$set"]["queries"] = payload["queries"]

        if "stores" in payload:
            update_doc["$set"]["stores"] = payload["stores"]
            
        if "confirmed_titles" in payload:
            if isinstance(payload["confirmed_titles"], dict):
                for k, v in payload["confirmed_titles"].items():
                    update_doc["$set"][f"confirmed_titles.{k}"] = v
            else:
                 update_doc["$set"]["confirmed_titles"] = payload["confirmed_titles"]
        
        # Canonical Form
        current_name = payload.get("title") or payload.get("name")
        current_qty = payload.get("quantity")
        if current_name:
            sig = normalize_product({"name": current_name, "quantity": current_qty})
            if sig:
                update_doc["$set"]["canonical.normalized_signature"] = sig
                
        # Removed flag
        if "removed" in payload:
             update_doc["$set"]["removed"] = bool(payload["removed"])

        try:
             self.products.update_one({"ean": ean}, update_doc, upsert=True)
             return True
        except Exception as e:
             logger.error(f"DB Write Error {ean}: {e}")
             return False

    def mark_removed(self, ean: str, removed: bool = True) -> bool:
        return self.upsert_product(ean, {"removed": removed})

    def _serialize(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Mongo doc to App Dict."""
        out = dict(doc)
        if "_id" in out:
            out["_id"] = str(out["_id"])
        
        # Convert datetime to str and fix asset paths
        for k, v in out.items():
            if isinstance(v, datetime):
                out[k] = v.isoformat()
            if isinstance(v, str) and (k == "image" or k.endswith("_image")):
                if v.startswith("../assets"):
                    out[k] = v.replace("../assets", "/assets", 1)
                elif v.startswith("./assets"):
                    out[k] = v.replace("./assets", "/assets", 1)
        return out



# ---------------------------------------------------------------------------
# Compat / Legacy Interface (for existing code support)
# ---------------------------------------------------------------------------

_repo = ProductRepository()

def _normalize_ean(ean: Any) -> str:
    value = "".join(ch for ch in str(ean) if ch.isdigit())
    return value.strip()

def descriptor_exists(ean: Any) -> bool:
    data = _repo.get_product(ean)
    return bool(data) and not data.get("removed")

def get_descriptor(ean: Any) -> Dict[str, Any]:
    data = _repo.get_product(ean)
    if data:
        return data
    # Empty default matching old behavior
    return {"ean": _normalize_ean(ean), "source": "unknown"}

def set_removed_flag(ean: Any, removed: bool) -> Dict[str, Any]:
    _repo.mark_removed(ean, removed)
    return get_descriptor(ean)

def all_descriptors() -> Dict[str, Dict[str, Any]]:
    # Caution: This might be heavy if DB is huge.
    # Used mainly for debugging or bulk operations.
    
    results = {}
    
    # 1. Load from DB
    if _repo.enabled and _repo.products is not None:
        try:
            cursor = _repo.products.find({})
            for doc in cursor:
                ean = doc.get("ean") or doc.get("_id")
                if doc.get("removed"):
                    results.pop(ean, None)
                else:
                    results[ean] = _repo._serialize(doc)
        except Exception:
            pass
            
    return results

def removed_eans() -> Set[str]:
    if _repo.enabled and _repo.products is not None:
        try:
             docs = _repo.products.find({"removed": True}, {"ean": 1, "_id": 0})
             return {str(d.get("ean", "")) for d in docs if d.get("ean")}
        except:
            return set()
    return set()

def add_dynamic_seed_entry(entry: Dict[str, Any]) -> None:
    ean = entry.get("ean")
    if ean:
        _repo.upsert_product(ean, entry)


# ---------------------------------------------------------------------------
# Image Management Functions (Phase 8: Images Seed → MongoDB)
# ---------------------------------------------------------------------------

from pathlib import Path
import urllib.request
import ssl

def get_image_assets_dir() -> Path:
    """Return the path to the pipeline/assets directory."""
    base = Path(__file__).parent
    assets_dir = base / "pipeline" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir


def save_product_image(ean: str, image_data: bytes, extension: str = "jpg") -> Optional[str]:
    """
    Save image bytes to local assets folder and update MongoDB.
    Returns normalized path (/assets/{ean}.{ext}) or None on failure.
    """
    ean = _normalize_ean(ean)
    if not ean or not image_data:
        return None
    
    try:
        assets_dir = get_image_assets_dir()
        image_path = assets_dir / f"{ean}.{extension}"
        
        with open(image_path, "wb") as f:
            f.write(image_data)
        
        normalized_path = f"/assets/{ean}.{extension}"
        _repo.update_product_field(ean, "image", normalized_path)
        
        logger.info(f"Saved image for EAN {ean}: {normalized_path}")
        return normalized_path
    except Exception as e:
        logger.error(f"Failed to save image for EAN {ean}: {e}")
        return None


def download_and_save_image(ean: str, image_url: str) -> Optional[str]:
    """Download image from URL and save locally."""
    ean = _normalize_ean(ean)
    if not ean or not image_url:
        return None
    
    assets_dir = get_image_assets_dir()
    for ext in ["jpg", "jpeg", "png", "webp"]:
        if (assets_dir / f"{ean}.{ext}").exists():
            normalized = f"/assets/{ean}.{ext}"
            _repo.update_product_field(ean, "image", normalized)
            return normalized
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(image_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
            image_data = response.read()
        
        ext = "jpg"
        if ".png" in image_url.lower():
            ext = "png"
        elif ".webp" in image_url.lower():
            ext = "webp"
        
        return save_product_image(ean, image_data, ext)
    except Exception as e:
        logger.error(f"Failed to download image for EAN {ean}: {e}")
        return None


def ensure_product_has_image(ean: str, fallback_url: Optional[str] = None) -> Optional[str]:
    """Ensure a product has a local image. Download if missing."""
    ean = _normalize_ean(ean)
    if not ean:
        return None
    
    assets_dir = get_image_assets_dir()
    for ext in ["jpg", "jpeg", "png", "webp"]:
        local_path = assets_dir / f"{ean}.{ext}"
        if local_path.exists():
            normalized = f"/assets/{ean}.{ext}"
            current = _repo.get_product_field(ean, "image")
            if current != normalized:
                _repo.update_product_field(ean, "image", normalized)
            return normalized
    
    if fallback_url:
        return download_and_save_image(ean, fallback_url)
    
    product = _repo.get_product(ean)
    if product:
        for url_field in ["image_url", "image"]:
            url = product.get(url_field)
            if url and url.startswith("http"):
                result = download_and_save_image(ean, url)
                if result:
                    return result
        
        stores = product.get("stores", {})
        for store_data in stores.values():
            img_url = store_data.get("image_url") or store_data.get("image")
            if img_url and img_url.startswith("http"):
                result = download_and_save_image(ean, img_url)
                if result:
                    return result
    
    return None


def sync_all_images_to_mongodb() -> Dict[str, Any]:
    """Synchronize all local asset images to MongoDB."""
    assets_dir = get_image_assets_dir()
    stats = {"found": 0, "updated": 0, "missing_product": 0}
    
    for ext in ["jpg", "jpeg", "png", "webp"]:
        for img_file in assets_dir.glob(f"*.{ext}"):
            ean = img_file.stem
            if not ean.isdigit():
                continue
            
            stats["found"] += 1
            normalized_path = f"/assets/{img_file.name}"
            
            product = _repo.get_product(ean)
            if not product:
                stats["missing_product"] += 1
                continue
            
            current = product.get("image")
            if current != normalized_path:
                _repo.update_product_field(ean, "image", normalized_path)
                stats["updated"] += 1
    
    logger.info(f"Image sync complete: {stats}")
    return stats
