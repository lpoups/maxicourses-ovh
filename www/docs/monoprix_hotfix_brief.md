# Monoprix — Correctifs de matching et requêtes (brief unique)
Date: 2025-10-22 • Owner: Maxicourses (maxicourses.fr)

## Objectif
Corriger le biais Monoprix qui sélectionne **systématiquement “amande”** alors que le bon produit est visible. Imposer un **verrou de variante par seed**, renforcer les **veto** unitaires/catégorie/taille, et sécuriser les requêtes.

## Symptômes observés
- Seed vanille ou nature ⇒ choix “amande”.
- Le bon 500 g est listé, mais le ranking l’ignore.
- Raison: règles au niveau famille sans contrainte **seed-variant** + requêtes trop permissives.

## Règles obligatoires (globales)
- Unit family identique au seed, sinon **REJECT**.
- Catégorie compatible, sinon **REJECT**.
- Taille dans la tolérance (mass ±25 %, volume ±25 %, count ±1), sinon **REJECT**.
- Must-have: au moins 2 parmi brand, product_type, variant clé, sinon **REJECT**.
- Liste négative par seed (toutes les autres variantes), sinon faux positifs.
- Seuils inchangés: THRESH=7, DELTA=2. En cas de doute: **ABSTAIN**.

---

## A. Verrou “variant_lock” côté ranking
Implémenter une détection robuste de la variante candidate et une règle de veto **avant** le scoring.

**monoprix_ranking.py** (ou module commun décision) — ajouter:

```python
# Variants normalisés
VARIANTS = {
    "nature":  [r"\bnature\b", r"sans\s+sucres?", r"sans\s+ar[ôo]me", r"\boriginal\b"],
    "vanille": [r"\bvanill?e\b"],
    "amande":  [r"\bamandes?\b", r"\baux\s+amandes?\b"],
    "coco":    [r"\bnoix\s+de\s+coco\b", r"\bcoco\b"],
    "mangue":  [r"\bmangues?\b"],
    "chocolat":[r"\bchocolat\b"],
}

def detect_variant_from_text(text: str) -> str | None:
    import re
    text = (text or "").lower()
    hits = []
    for v, pats in VARIANTS.items():
        if any(re.search(p, text) for p in pats):
            hits.append(v)
    # Si "nature" + autre saveur, on garde la saveur non nature
    if "nature" in hits and len(hits) > 1:
        hits = [v for v in hits if v != "nature"]
    return hits[0] if hits else None
```

Dans l’évaluation de chaque candidat, détecter la variante sur **titre + description + OCR** et **veto** si non conforme:

```python
seed_variant = (seed.get("variant_norm") or "").strip().lower()
text_blob = " ".join(filter(None, [snapshot.title, snapshot.raw_text, " ".join(snapshot.ocr_tokens or [])]))
cand_variant = detect_variant_from_text(text_blob)

# Veto strict par seed
if seed_variant:
    if seed_variant == "nature":
        if cand_variant and cand_variant != "nature":
            verdict.veto("variant_mismatch")
        elif cand_variant is None:
            verdict.veto("variant_missing")
    else:
        if cand_variant and cand_variant != seed_variant:
            verdict.veto("variant_mismatch")
        elif cand_variant is None:
            verdict.veto("variant_missing")

verdict.snapshot.extras = verdict.snapshot.extras or {}
verdict.snapshot.extras.update({
    "seed_variant": seed_variant,
    "candidate_variant": cand_variant,
})
```

Conserver le bonus de score existant si la variante correspond, mais **le veto prime**.

---

## B. Requêtes Monoprix: verrouiller la variante et filtrer les autres
Renforcer le builder pour: (1) inclure la variante du seed dans les Q1/Q3, (2) ajouter une **liste négative dynamique** égal à “toutes les autres variantes”.

**query_builder.py** — ajouter un utilitaire simple:

```python
SEED_VARIANTS = ["nature","vanille","amande","coco","mangue","chocolat"]

def seed_variant_negatives(seed_variant: str) -> list[str]:
    v = (seed_variant or "").strip().lower()
    if not v:
        return []
    return [tok for tok in SEED_VARIANTS if tok != v]
```

Dans `build_query_plan_from_descriptor(..., retailer="monoprix")`:
- Injecter la variante du seed comme **second token** des Q1/Q3.
- Exposer `negatives` au fetcher: `stage.negatives = seed_variant_negatives(canonical.variant)`.

**fetch_monoprix_price.py** — lorsque vous instanciez `base_payload` et lorsque vous filtrez les cartes produits, compléter:

```python
seed_variant = (descriptor_entry.get("canonical") or {}).get("variant") or ""
dynamic_negatives = (stage.get("negatives") or []) + _store_negatives(descriptor_entry)
if any(tok in (label_clean or "").lower() for tok in dynamic_negatives):
    continue
base_payload["seed_variant"] = seed_variant
base_payload["dynamic_negatives"] = dynamic_negatives
```

Cas “nature”: ajouter en `dynamic_negatives` toutes les autres saveurs.

---

## C. Veto unitaires, catégorie et taille
Appliquer **avant** scoring, sur snapshot enrichi:
- `unit_family` du candidat == seed, sinon veto `unit_family`.
- `category_ok` vrai, sinon veto `category`.
- `size_ratio` hors tolérance ⇒ veto `size_out_of_range`.

---

## D. Image matching
- pHash uniquement indicatif; aucune acceptation basée image seule.
- Si classif packaging disponible (pot vs brique) ⇒ veto `pack_mismatch` si différent.

---

## E. Télémétrie obligatoire
Dans `log_matching_snapshot(...)`, ajouter:
- `seed_variant`, `candidate_variant`.
- `variant_ok` = absence de `variant_mismatch` et `variant_missing`.

---

## F. Config famille “desserts_vegetaux”
```yaml
families:
  desserts_vegetaux:
    unit_family: mass
    size_tolerance: 0.25
    must_have: [alpro|sojasun|bjorg, dessert|desserts, vegetal|végétal, soja]
    neg_tokens: [boisson, avoine, lait, bouteille, 1l, brique, yaourt_a_boire]
    thresholds: { THRESH: 7, DELTA: 2 }
```
Ne pas mettre les saveurs ici; elles viennent du **seed**.

---

## G. Tests d’intégration rapides
```bash
# Amande (doit trouver amande)
USE_CDP=1 HEADLESS=1 python3 pipeline/run_pipeline.py --ean 5411188118961 --adapters monoprix
# Vanille (doit trouver vanille)
USE_CDP=1 HEADLESS=1 python3 pipeline/run_pipeline.py --ean 5411188103387 --adapters monoprix
```
Succès = `candidate_variant == seed_variant`, aucun veto `variant_*`, unit_family_ok=true, size_ok=true. Sinon **ABSTAIN**.

---

## H. Déploiement
Flag `feature_flags.variant_lock = true`. Canary Monoprix/desserts_vegetaux. Rollback si `fp_rate > 2 %` sur 500 décisions ou `abstain_rate > 40 %`.

---

## Mise à jour 2025-11-01 — Requêtes humanisées validées
- **Requêtes** : `build_query_terms()` injecte désormais en tête `Hipro fraise`, `Hipro fraise framboise`, `Hipro framboise`, `Hipro yaourt`. Les longues formulations historiques restent en secours.
- **Validation** : variantes `fraise`/`framboise` ajoutées dans `VARIANT_PATTERNS` + vérification `missing_tokens` assouplie (ignore chiffres, accepte singulier/pluriel). Plus de veto arbitraire.
- **Runs récents**
  - `5411188118961` (Hipro amande) : OK (tokens + image).
  - `3033491485756` (Hipro fraise/framboise) : OK (`run-3033491485756-20251101-104543.json`, 2,99 €, image match true).
  - `8712100731822` (Savora 385 g) : OK (`run-8712100731822-20251101-111349.json`, 2,75 €).
  - `3665468000312` (Destop 950 ml) : OK (`run-3665468000312-20251101-113240.json`, 4,39 €) après ajout d’un visuel Monoprix dédié.

### TODO immédiats
1. Étendre la même logique (tokens seed + image) aux autres enseignes textuelles si besoin.
2. Maintenir une librairie d’images seed → `pipeline/assets/<EAN>.jpg` synchronisée avec les runs récents (sans visuel, le matching image échoue).
