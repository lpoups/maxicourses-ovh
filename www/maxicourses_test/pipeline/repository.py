import os
import sys
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import logging

try:
    from pymongo import MongoClient, UpdateOne
    from pymongo.errors import PyMongoError
except ImportError:
    MongoClient = None
    PyMongoError = Exception

# Configure logging
logger = logging.getLogger("ProductRepository")

class ProductRepository:
    """
    Central repository for storing and retrieving product data (Golden Record).
    Handles:
    - Product upsert (consolidation from multiple sources)
    - Blacklisting failed queries
    - Retrieving product history
    """
    def __init__(self, uri: str = None, db_name: str = "maxicourses"):
        self.enabled = False
        self.db = None
        self.products = None
        self.failures = None

        if not MongoClient:
            logger.warning("pymongo not installed, Repository disabled.")
            return

        mongo_uri = uri or os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/")
        try:
            self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
            # Fast check
            self.client.admin.command('ping')
            self.db = self.client[db_name]
            self.products = self.db.products
            self.failures = self.db.failures
            
            # Ensure Indexes
            self.products.create_index("ean", unique=True)
            self.failures.create_index([("store", 1), ("query", 1)], unique=True)
            
            self.enabled = True
            print(f"[ProductRepository] Connected to {mongo_uri}/{db_name}", file=sys.stderr)
        except Exception as e:
            logger.warning(f"Failed to connect to MongoDB: {e}. Repository disabled.")
            print(f"[ProductRepository] MongoDB connection failed: {e}", file=sys.stderr)

    def upsert_product(self, ean: str, data: Dict[str, Any], source: str):
        """
        Update product information. merges new data with existing.
        """
        if not self.enabled or not ean:
            return

        now = datetime.now(timezone.utc)
        
        # Prepare fields to set
        set_fields = {
            "updated_at": now,
        }
        
        # Merge basic fields if present and not empty
        for field in ["title", "brand", "quantity", "image_url", "nutriscore_grade", "nova_group"]:
            val = data.get(field)
            if val:
                set_fields[f"data.{field}"] = val
                # Also set top-level for easier access if preferred, strictly data.* is cleaner but let's do both or pick one.
                # Let's stick to a flat structure for main attributes for simplicity
                set_fields[field] = val

        # Add source specific metadata
        if source:
            set_fields[f"sources.{source}.last_seen"] = now
            if data.get("url"):
                set_fields[f"sources.{source}.url"] = data.get("url")

        try:
            self.products.update_one(
                {"ean": ean},
                {
                    "$set": set_fields,
                    "$setOnInsert": {"created_at": now}
                },
                upsert=True
            )
            print(f"[ProductRepository] Upserted {ean} from {source}", file=sys.stderr)
        except Exception as e:
            print(f"[ProductRepository] Error upserting {ean}: {e}", file=sys.stderr)

    def get_product(self, ean: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        return self.products.find_one({"ean": ean})

    def record_failure(self, store: str, query: str):
        """Record a query that yielded 0 results for a store."""
        if not self.enabled:
            return
        try:
            self.failures.update_one(
                {"store": store, "query": query},
                {"$set": {"last_failed": datetime.now(timezone.utc)}, "$inc": {"count": 1}},
                upsert=True
            )
        except Exception:
            pass

    def is_query_blacklisted(self, store: str, query: str) -> bool:
        """Check if query is known to fail."""
        if not self.enabled:
            return False
        doc = self.failures.find_one({"store": store, "query": query})
        return doc is not None and doc.get("count", 0) >= 1
