from descriptor_store import ProductRepository
import sys

repo = ProductRepository()
entry = {
    "ean": "3092718637033",
    "image": "https://media.carrefour.fr/medias/011ef995a0f24adba2decbc518cc9ed7/p_200x200/03092718637033_C1N1_s03.png",
    "source": "carrefour_market",
    "brand": "Teisseire",
    "title": "Sirop Menthe Verte TEISSEIRE",
    "quantity": "60cL"
}
print(f"Upserting 3092718637033...")
repo.upsert_product("3092718637033", entry)
print(f"Count now: {repo.products.count_documents({})}")
