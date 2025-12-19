import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))
from descriptor_store import ProductRepository

repo = ProductRepository()
entry = {
    "ean": "3092718637033",
    "image": "https://media.carrefour.fr/medias/011ef995a0f24adba2decbc518cc9ed7/p_200x200/03092718637033_C1N1_s03.png",
    "source": "carrefour_market", # High priority
    "title": "Sirop Menthe Verte TEISSEIRE",
    "quantity": "60cL"
}
print(f"Upserting: {entry}")
repo.upsert_product("3092718637033", entry)
print("Done. Retrieving verification:")
doc = repo.get_product("3092718637033")
print(doc)
