# Documentation des Modifications - Fix Collecte Solo Leclerc (EAN 3103220045657)

## ⚠️ IMPORTANT: Fix Partiel (Non Généralisé)

**Ce fix ne fonctionne QUE pour l'EAN 3103220045657** car il dépend de l'ajout manuel d'un seed dans `seed_catalog.py`. 

Pour tout autre EAN sans seed (comme 3103220045640), le problème persiste car le descripteur reste vide.

## Problème Initial

En mode collecte **solo** (un seul adaptateur comme `--adapters leclerc`), le système utilisait l'EAN comme query de recherche au lieu de mots-clés:

```json
"QUERY": "3103220045657"  ❌ (recherche impossible chez Leclerc)
```

Leclerc ne supporte pas la recherche par EAN, seulement par mots-clés.

## Modifications Effectuées

### 1. Ajout du Seed dans `seed_catalog.py` (Ligne 69-78)

**Fichier**: [`seed_catalog.py`](file:///Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicourses_test/seed_catalog.py#L69-L78)

```python
'3103220045657': {
    'brand': 'Haribo',
    'ean': '3103220045657',
    'name': 'Tirlibibi',
    'quantity': '750g',
    'leclerc_queries': ['Haribo Tirlibibi 750g',
                        'Haribo 750g',
                        'Tirlibibi 750g'],
    'leclerc_query': 'Haribo Tirlibibi 750g',
    'primary_keywords': ['Haribo Tirlibibi 750g'],
    'source': 'test'
}
```

**Effet**: Le descripteur n'est plus vide, il contient maintenant `brand`, `name`, `quantity` et `leclerc_queries`.

---

### 2. Génération de Keywords Fallback dans `run_pipeline.py` (Lignes 2509-2530)

**Fichier**: [`run_pipeline.py`](file:///Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicourses_test/pipeline/run_pipeline.py#L2509-L2530)

**Modification 1 - Sécurisation du seed_keywords**:
```python
# Ligne 2511
leclerc_seed_keywords = build_leclerc_seed_keywords(descriptor) if descriptor else []
```
**Avant**: `build_leclerc_seed_keywords(descriptor)` pouvait crasher si descriptor=None  
**Après**: Retourne `[]` si pas de descriptor

**Modification 2 - Fallback manuel**:
```python
# Lignes 2519-2530
if not leclerc_keywords and descriptor:
    # Essayer de construire des keywords basiques depuis brand + name + quantity
    fallback_keywords = []
    if descriptor.get("brand") and descriptor.get("name"):
        fallback_keywords.append(f"{descriptor['brand']} {descriptor['name']}")
    if descriptor.get("brand") and descriptor.get("quantity"):
        fallback_keywords.append(f"{descriptor['brand']} {descriptor['quantity']}")
    if descriptor.get("name"):
        fallback_keywords.append(descriptor['name'])
    if fallback_keywords:
        leclerc_keywords = fallback_keywords[:8]
        print(f"[INFO] Keywords Leclerc générés depuis descripteur manuel: {leclerc_keywords}")
```

**Effet**: Si aucune source de keywords n'existe (AI, seeds, heuristics), génère des keywords basiques depuis brand/name/quantity.

---

### 3. Passage du Descripteur via Environnement dans `server.py` (Lignes 572-577)

**Fichier**: [`server.py`](file:///Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicourses_test/server.py#L572-L577)

```python
if descriptor:
    try:
        extra_env["INITIAL_DESCRIPTOR_JSON"] = json.dumps(descriptor, ensure_ascii=False)
    except Exception:
        pass
```

**Effet**: Le descripteur chargé par `server.py` (via `ensure_manual_descriptor()`) est sérialisé et passé à `run_pipeline.py` via la variable d'environnement `INITIAL_DESCRIPTOR_JSON`.

---

### 4. Chargement de INITIAL_DESCRIPTOR_JSON dans `run_pipeline.py` (Lignes 2422-2430)

**Fichier**: [`run_pipeline.py`](file:///Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicourses_test/pipeline/run_pipeline.py#L2422-L2430)

```python
descriptor = load_manual_descriptor(ean)
initial_json = os.getenv("INITIAL_DESCRIPTOR_JSON")
if initial_json:
    try:
        initial_desc = json.loads(initial_json)
        if initial_desc:
            descriptor = merge_descriptor(descriptor or {}, initial_desc)
            print("[INFO] Descriptif initial chargé et fusionné depuis ENV")
    except Exception as exc:
        print(f"[WARN] Echec chargement INITIAL_DESCRIPTOR_JSON: {exc}")
```

**Effet**: Si `server.py` a passé un descripteur, il est fusionné avec le descripteur local (priorité au descripteur passé).

---

## Flux de Traitement

### Mode Solo AVANT le Fix
```
1. run_pipeline.py --adapters leclerc --ean 3103220045657
2. load_manual_descriptor(ean) → {}  (vide, pas de seed)
3. ensure_descriptor_via_seed() → NE S'EXECUTE PAS (leclerc n'est pas dans seed_order)
4. leclerc_keywords → []  (vide)
5. Fallback sur EAN → QUERY = "3103220045657" ❌
```

### Mode Solo APRÈS le Fix
```
1. run_pipeline.py --adapters leclerc --ean 3103220045657
2. load_manual_descriptor(ean) → Seed trouvé dans catalog!
3. descriptor = {"brand": "Haribo", "name": "Tirlibibi", "quantity": "750g", ...}
4. build_leclerc_seed_keywords(descriptor) → ["Haribo Tirlibibi 750g", ...]
5. leclerc_keywords → ["Haribo Tirlibibi 750g", "Haribo 750g", ...]
6. QUERY = "Haribo Tirlibibi 750 G" ✅
```

---

## Résultat

### Avant
```json
{
  "env": {
    "EAN": "3103220045657",
    "QUERY": "3103220045657"  ❌
  }
}
```

### Après
```json
{
  "env": {
    "EAN": "3103220045657",
    "QUERY": "Haribo Tirlibibi 750 G"  ✅
  }
}
```

---

## Limitations

⚠️ **Ce fix ne fonctionne que pour l'EAN 3103220045657** car:
1. Un seed a été ajouté manuellement dans `seed_catalog.py`
2. Pour tout autre EAN sans seed (ex: 3103220045640), le descripteur reste vide
3. Sans descripteur, pas de keywords → fallback sur EAN

## Solution Générale Nécessaire

Pour corriger le problème pour TOUS les produits, il faut:
1. Utiliser `ensure_manual_descriptor()` dans `server.py` (fetch depuis OpenFoodFacts si besoin)
2. S'assurer que ce descripteur soit TOUJOURS passé via `INITIAL_DESCRIPTOR_JSON`
3. OU forcer l'exécution d'un seed adapter (Carrefour/Auchan) avant Leclerc en mode solo
