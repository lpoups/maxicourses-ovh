#!/usr/bin/env python3
"""
Synchronisation des images locales avec MongoDB.
Usage: python3 sync_images.py
"""
import sys
import os

# Ensure we can import from parent directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from descriptor_store import sync_all_images_to_mongodb, get_image_assets_dir

if __name__ == "__main__":
    print("=" * 60)
    print("SYNCHRONISATION IMAGES → MONGODB")
    print("=" * 60)
    
    assets_dir = get_image_assets_dir()
    print(f"Dossier assets: {assets_dir}")
    print()
    
    stats = sync_all_images_to_mongodb()
    
    print()
    print("RÉSULTATS:")
    print(f"  - Images trouvées: {stats['found']}")
    print(f"  - MongoDB mis à jour: {stats['updated']}")
    print(f"  - Produits manquants (EAN sans fiche): {stats['missing_product']}")
    print()
    print("✓ Synchronisation terminée")
