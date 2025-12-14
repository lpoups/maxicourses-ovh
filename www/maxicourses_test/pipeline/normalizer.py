import re
from typing import Dict, Any, Optional

# Basic Need State Categories
CATEGORIES = {
    "cola": ["cola", "coca"],
    "limonade": ["limonade", "sprite", "7up"],
    "eau_plate": ["eau de source", "eau minérale", "eau plate", "evian", "volvic", "cristaline", "vittel"],
    "eau_gazeuse": ["eau gazeuse", "eau pétillante", "perrier", "badoit"],
    "jus_orange": ["jus d'orange", "pur jus orange"],
    "jus_pomme": ["jus de pomme", "pur jus pomme"],
    "lait": ["lait entier", "lait demi-écrémé", "lait écrémé"],
    "beurre": ["beurre doux", "beurre demi-sel"],
    "creme": ["crème fraîche", "creme fraiche", "crème liquide"],
    "oeuf": ["oeufs", "oeuf plein air", "oeuf bio"],
    "pates": ["spaghetti", "penne", "coquillette", "fusilli"],
    "riz": ["riz basmati", "riz long", "riz rond"],
    "cafe": ["café moulu", "café grain", "capsule"],
    "the": ["thé vert", "thé noir", "infusion"],
}

def _normalize_quantity(qty_str: Optional[str]) -> Optional[str]:
    """Normalize quantity string to standard unit (L, KG, U)."""
    if not qty_str:
        return None
    raw = qty_str.lower().replace(" ", "").replace(",", ".")
    
    # Extract number and unit
    match = re.match(r"([\d\.]+)([a-z]+)", raw)
    if not match:
        return None
    
    val, unit = float(match.group(1)), match.group(2)
    
    if unit in ["ml", "milliliters"]:
        return f"{val/1000:g}l"
    if unit in ["cl", "centiliters"]:
        return f"{val/100:g}l"
    if unit in ["dl"]:
        return f"{val/10:g}l"
    if unit in ["l", "liters", "litre", "litres"]:
        return f"{val:g}l"
        
    if unit in ["g", "grammes", "grams"]:
        return f"{val/1000:g}kg"
    if unit in ["kg", "kilogrammes", "kilograms"]:
        return f"{val:g}kg"
        
    return f"{val:g}{unit}"

def _detect_category(text: str) -> Optional[str]:
    """Detect need state category from text."""
    text = text.lower()
    for cat, keywords in CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return cat
    return None

def normalize_product(descriptor: Dict[str, Any]) -> str:
    """
    Compute a 'Canonical Signature' for a product.
    Format: {category} {quantity_norm}
    Example: 'cola 1.5l'
    """
    name = descriptor.get("name") or descriptor.get("title") or ""
    qty = descriptor.get("quantity") or descriptor.get("size")
    
    # 1. Normalize Quantity
    qty_norm = _normalize_quantity(str(qty)) if qty else "unknown"
    
    # 2. Detect Category
    cat = _detect_category(name)
    if not cat:
        # Fallback: simple specific words check?
        # For now, if no category, use first 2 meaningful words?
        # Let's keep it strict: if no category, return "" (no substitution possible)
        return ""
        
    return f"{cat} {qty_norm}".strip()
