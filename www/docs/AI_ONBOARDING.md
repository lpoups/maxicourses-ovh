# 🚀 MAXICOURSES — DOCUMENTATION TECHNIQUE IA (Décembre 2025)

> **Ce document est la SEULE source de vérité technique.**  
> **Lecture OBLIGATOIRE avant toute action.**

---

## ⚠️ RÈGLE ABSOLUE : MISE À JOUR OBLIGATOIRE

**Toutes les heures**, ce document doit être mis à jour avec :
- Les nouveaux problèmes rencontrés
- Les solutions trouvées (barrer le problème + indiquer la solution)

Format : ~~Problème résolu~~ → Solution appliquée

---

## 📋 SOMMAIRE
1. [Concept Maxicourses](#1-concept-maxicourses)
2. [Connexion & Infrastructure OVH](#2-connexion--infrastructure-ovh)
3. [Tunnel SSH Inverse](#3-tunnel-ssh-inverse)
4. [Base de Données MongoDB](#4-base-de-données-mongodb)
5. [Collecte par Enseigne](#5-collecte-par-enseigne)
6. [Génération Mots-Clés (API OpenAI)](#6-génération-mots-clés-api-openai)
7. [Matching d'Images](#7-matching-dimages)
8. [Commandes Bash Essentielles](#8-commandes-bash-essentielles)
9. [Problèmes à Résoudre (Suivi Horaire)](#9-problèmes-à-résoudre-suivi-horaire)
10. [Application iOS](#10-application-ios)
11. [Règles de Développement](#11-règles-de-développement)
12. [Sauvegarde GitHub](#12-sauvegarde-github)

---

## 1. CONCEPT MAXICOURSES

### Vision Produit
**MaxiCourses = Comparateur de prix pour la grande distribution française**

```
┌─────────────────────────────────────────────────────────────────┐
│  1. L'utilisateur scanne un CODE-BARRE (EAN)                    │
│  2. Le système collecte les prix sur 12 enseignes               │
│  3. Affichage du prix le moins cher + Smart Substitution        │
│     (ex: Coca → Cola MDD moins cher)                            │
└─────────────────────────────────────────────────────────────────┘
```

### Double Objectif
1. **Exactitude B2B/B2C** : Prix EXACT du produit scanné dans TOUS les magasins
2. **Smart Substitution** : Proposer l'alternative la moins chère (même catégorie, format similaire)

---

## 2. CONNEXION & INFRASTRUCTURE OVH

### ⚠️ IMPORTANT : Tout fonctionne à 100% sur le serveur OVH

Le code local est uniquement pour le développement. Toutes les collectes s'exécutent sur le VPS OVH.

### Informations de Connexion

| Élément | Valeur |
|---------|--------|
| **Hôte SSH** | `vps-a4a36a41.vps.ovh.net` |
| **IP** | `91.134.133.156` |
| **Utilisateur** | `ubuntu` |
| **Mot de passe** | `PxuJkPxe8jEn!2025` |
| **Alias SSH** | `ovh-server` (configuré dans `~/.ssh/config`) |
| **Dashboard** | https://api.maxicourses.fr/index.html |
| **Dashboard (alias)** | https://api.maxicourses.fr/index_ovh_prod.html |

### Connexion SSH
```bash
# Connexion simple
ssh ubuntu@vps-a4a36a41.vps.ovh.net

# Ou avec l'alias configuré
ssh ovh-server
```

### Structure sur le serveur
```
/home/ubuntu/maxicourses-prod/
├── maxicourses_test/
│   ├── server.py              # API Flask (:5001)
│   ├── pipeline/
│   │   ├── run_pipeline.py    # Orchestrateur collectes
│   │   ├── finder.py          # Génération mots-clés
│   │   └── assets/            # Images produits
│   ├── seed_catalog.py        # Catalogue produits (Python dict)
│   ├── descriptor_store.py    # Repository MongoDB
│   ├── fetch_*.py             # Scripts de collecte par enseigne
│   ├── .chrome-debug/         # Profil Chrome persistent
│   └── state/                 # États cookies par enseigne
└── www/docs/                   # Documentation
```

---

## 3. TUNNEL SSH INVERSE

### Concept
Un tunnel SSH inverse permet au serveur OVH d'utiliser **l'IP résidentielle** de ta machine locale pour éviter les blocages anti-bot.

### Commande Tunnel
```bash
# Sur ta machine locale (Mac)
ssh -R 9223:localhost:9222 ovh-server
```

**Explication :**
- `-R 9223:localhost:9222` : Le port 9223 sur OVH redirige vers le port 9222 de ta machine
- Le serveur OVH peut ainsi piloter TON Chrome local avec TON IP résidentielle
- Port 9223 (et pas 9222) pour éviter les conflits avec Chrome sur OVH

### Configuration Tunnel MongoDB (pour visualisation)
```bash
# Tunnel pour accéder à MongoDB depuis ta machine locale
ssh -L 27017:127.0.0.1:27017 ubuntu@vps-a4a36a41.vps.ovh.net
```

---

## 4. BASE DE DONNÉES MONGODB

### ⚠️ RÈGLE ABSOLUE : Plus RIEN en JSON, TOUT dans MongoDB

### Configuration
| Élément | Valeur |
|---------|--------|
| **Base** | `mongodb://localhost:27017/` |
| **DB Name** | `maxicourses` |
| **Collection** | `products` |

### État de synchronisation (17/12/2025)
| Statistique | Valeur |
|-------------|--------|
| **Produits dans seed_catalog.py** | 19 actifs |
| **Produits dans MongoDB** | 31 total |
| **Synchronisation** | ✅ 100% complète |

### Structure Golden Record COMPLÈTE (document MongoDB)
```javascript
{
  "_id": ObjectId("..."),
  "ean": "5000112611861",              // Code-barre (clé unique)
  
  // ═══════════════════════════════════════════════════
  // IDENTITÉ PRODUIT
  // ═══════════════════════════════════════════════════
  "brand": "Coca-Cola",
  "name": "Soda COCA-COLA Original - Bouteille 1,75L",
  "description": "Soda COCA-COLA Original - Bouteille 1,75L",
  "quantity": "1,75 L",
  
  // ═══════════════════════════════════════════════════
  // IMAGE (pour matching Monoprix/Leclerc)
  // ═══════════════════════════════════════════════════
  "image": "./assets/5000112611861.jpg",   // Chemin local
  
  // ═══════════════════════════════════════════════════
  // SCORES NUTRITIONNELS
  // ═══════════════════════════════════════════════════
  "nutriscore_grade": "unknown",           // a, b, c, d, e ou unknown
  "nutriscore_image": "../assets/nutriscore/nutriscore-unknown.svg",
  
  // ═══════════════════════════════════════════════════
  // MOTS-CLÉS DE RECHERCHE (générés par IA ou manuels)
  // ═══════════════════════════════════════════════════
  "keywords": ["Cola 1.75 L"],             // Mots-clés génériques
  "primary_keywords": ["Cola 1.75 L"],     // Prioritaires
  "secondary_keywords": ["Goût", "Original", "COCA", "Bouteille"],
  
  // Mots-clés spécifiques Leclerc
  "leclerc_queries": [
    "Cola 1.75 L",
    "Cola Soda 1.75 L",
    "Coca-Cola Original 1.75L"
  ],
  "leclerc_query": "Cola 1.75 L",          // Requête principale Leclerc
  
  // Mots-clés par enseigne (généré par IA)
  "queries": {
    "intermarche": ["coca-cola 1,75l", "coca cola original"],
    "leclerc": ["coca-cola 1,75l", "coca-cola original"],
    "monoprix": ["coca-cola extraits"],     // ⚠️ Jamais de quantité !
    "casino": ["coca cola 1,75l", "soda coca 1,75l"],
    "spar": ["coca cola 1,75l"]
  },
  
  // ═══════════════════════════════════════════════════
  // MOTS NÉGATIFS (variantes à REJETER)
  // ═══════════════════════════════════════════════════
  "negatives": {
    "intermarche": ["sans sucre", "vanille", "light", "zero", "cherry", "2.25l", "promo", "lot"],
    "leclerc": ["sans sucre", "vanille", "light", "zero", "cherry", "citron", "framboise"],
    "monoprix": ["sans sucre", "vanille", "light", "zero", "cherry", "promo", "lot"]
  },
  
  // ═══════════════════════════════════════════════════
  // DONNÉES PAR MAGASIN (prix, liens, descriptifs)
  // ═══════════════════════════════════════════════════
  "stores": {
    "auchan": {
      "url": "https://www.auchan.fr/coca-cola-boisson-...",
      "price": 2.38,                       // Prix collecté
      "unit_price": "1.36 €/L",
      "title": "Coca-Cola Soda 1,75L",      // Titre exact sur le site
      "last_update": "2025-12-17T15:30:00Z"
    },
    "carrefour_city": {
      "url": "https://www.carrefour.fr/p/soda-au-cola-...",
      "price": 2.45,
      "title": "COCA-COLA Original 1,75L"
    },
    "leclerc": {
      "url": "https://fd12-courses.leclercdrive.fr/...",
      "price": 2.29
    },
    "monoprix": {
      "url": "https://courses.monoprix.fr/products/...",
      "price": 2.69,
      "matched_by": "image"                // Méthode de validation
    }
    // + courseu, chronodrive, casino, spar, intermarche...
  },
  
  // ═══════════════════════════════════════════════════
  // URLs DIRECTES (legacy, migré vers stores.X.url)
  // ═══════════════════════════════════════════════════
  "courseu_url": "https://www.coursesu.com/p/soda-coca-cola-original/...",
  "auchan_url": "https://www.auchan.fr/coca-cola-boisson/...",
  
  // ═══════════════════════════════════════════════════
  // SIGNATURE CANONIQUE (pour Smart Substitution)
  // ═══════════════════════════════════════════════════
  "canonical": {
    "normalized_signature": "cola 1.75l",  // Signature normalisée
    "brand": "Coca-Cola",
    "size_value": 1.75,
    "size_unit": "l"
  },
  
  // ═══════════════════════════════════════════════════
  // HISTORIQUE PRIX (à implémenter)
  // ═══════════════════════════════════════════════════
  "price_history": [
    {"date": "2025-12-01", "auchan": 2.45, "carrefour": 2.50},
    {"date": "2025-12-15", "auchan": 2.38, "carrefour": 2.50}
  ],
  
  // ═══════════════════════════════════════════════════
  // MÉTADONNÉES
  // ═══════════════════════════════════════════════════
  "source": "courseu",                     // Enseigne seed d'origine
  "note": "2025-10-31T13:07:56Z · Super U Eysines",
  "created_at": ISODate("2025-12-17T15:55:41Z"),
  "updated_at": ISODate("2025-12-17T18:24:05Z"),
  "removed": false
}
```


### Repository (descriptor_store.py)
```python
from descriptor_store import ProductRepository

repo = ProductRepository()

# Lire un produit
product = repo.get_product("5000112611861")

# Mettre à jour un champ spécifique
repo.update_product_field("5000112611861", "stores.auchan.price", 2.38)

# Upsert complet
repo.upsert_product("5000112611861", {
    "brand": "Coca-Cola",
    "title": "...",
    "queries": {"intermarche": ["coca-cola 1.75l"]}
})
```

---

## 5. COLLECTE PAR ENSEIGNE

### Classification des Enseignes

| Type | Enseignes | Méthode |
|------|-----------|---------|
| **SEED (EAN direct)** | Carrefour, Auchan, Chronodrive, Course U, G20 | Recherche EAN → Données fiables |
| **EAN + Validation** | Intermarché, Casino, Spar | Mots-clés → Vérification EAN dans URL/page |
| **Image Matching** | Leclerc, Monoprix | Mots-clés → Matching image OBLIGATOIRE |

---

### 🔵 CARREFOUR (City / Market / Super)

**Script** : `fetch_carrefour_price.py` + wrappers `_city.py`, `_market.py`, `_super.py`

**Méthode** : Recherche EAN STRICTE
1. Charge la page d'accueil Carrefour
2. Sélectionne le magasin via cookie `FRONTAL_STORE`
3. Recherche par EAN brut
4. Parse le JSON `window.__INITIAL_STATE__` pour extraire prix/titre/image
5. Si EAN trouvé → SEED validé

**Variables environnement** :
```bash
EAN=5000112611861
FRONTAL_STORE=800041        # City Bordeaux
# FRONTAL_STORE=1911        # Market Fondaudège
USE_CDP=1
HEADLESS=0
```

**Magasins configurés** :
| Variante | FRONTAL_STORE | Magasin |
|----------|---------------|---------|
| City | 800041 | Bordeaux Balguerie |
| Market | 1911 | Bordeaux Fondaudège |
| Super | (à configurer) | Lormont |

---

### 🔵 AUCHAN (Méthode "Chaîne de Confiance")

**Script** : `fetch_auchan_price.py`

**⚠️ BIBLE : Voir `docs/collecte_auchan.md` pour la procédure complète**

**Méthode** : Recherche EAN STRICTE + Comportement Humain

**Chaîne de Validation (CRITIQUE) :**
1. **Client API** → Envoie `POST /api/collect` à `server.py`
2. **server.py** → DOIT injecter `CDP_URL="http://127.0.0.1:9223"` dans l'environnement
3. **run_pipeline.py** → Transmet l'environnement au fetcher
4. **fetch_auchan_price.py** → Se connecte via CDP (PAS de playwright-stealth !)

**Points CRITIQUES du fetcher :**
```python
# ❌ INTERDIT : make_context() → injecte playwright-stealth = DÉTECTÉ
# ✅ OBLIGATOIRE : Connexion CDP pure
browser = await playwright.chromium.connect_over_cdp(cdp_url)
context = browser.contexts[0]  # Récupère la session existante
await context.clear_cookies()  # Nettoyage pré-session
```

**Clic Humain Randomisé (fonction `choose_drive`) :**
```python
# Le clic parfait au centre est une signature robot !
offset_x = random.uniform(-5, 5)
offset_y = random.uniform(-5, 5)

await page.mouse.move(target_x + offset_x, target_y + offset_y)
await page.wait_for_timeout(random.randint(150, 300))
await page.mouse.down()
await page.wait_for_timeout(random.randint(80, 150))
await page.mouse.up()
```

**Cycle Toast (obligatoire) :**
```python
# Auchan confirme avec un popup "C'est noté"
# Si on n'attend pas sa disparition, le store n'est pas persisté !
await toast.wait_for(state="visible", timeout=3000)
await toast.wait_for(state="hidden", timeout=15000)
```

**Variables environnement** :
```bash
EAN=5000112611861
AUCHAN_STORE_SLUG=auchan-drive-supermarche-talence-gallieni
AUCHAN_STORE_URL=https://www.auchan.fr/magasins/drive/auchan-drive-supermarche-talence-gallieni/s-6117
CDP_URL=http://127.0.0.1:9223
USE_CDP=1
```

---

### 🔵 CHRONODRIVE

**Script** : `fetch_chronodrive_price.py`

**Méthode** : Recherche EAN STRICTE
1. Navigue vers drive Le Haillan
2. Recherche par EAN
3. Si aucun résultat → fallback sur mots-clés seed
4. Extrait prix depuis PDP

---

### 🔵 COURSE U (Super U Eysines)

**Script** : `fetch_courseu_price.py`

**Méthode** : Recherche EAN STRICTE
1. Navigue vers Super U Eysines
2. Ferme overlay `div.mask` si présent
3. Recherche par EAN
4. Valide EAN dans URL produit

**⚠️ Problème fréquent** : Cloudflare et overlay marketing. Procédure :
```bash
# 1. Lancer Chrome debug
./start_chrome_debug.sh

# 2. Passer les protections manuellement dans le navigateur

# 3. Sauvegarder l'état
USE_CDP=1 python3 save_state_from_cdp.py courseu

# 4. Relancer la collecte
```

---

### 🟡 INTERMARCHÉ

**Script** : `fetch_intermarche_price.py` (1694 lignes)

**Méthode** : Recherche MOTS-CLÉS + Validation EAN dans URL
1. Navigue vers Intermarché (home)
2. Tape la requête dans la barre de recherche **caractère par caractère** (human-like)
3. Pour chaque résultat :
   - Extrait l'EAN depuis l'URL (`/produit/slug-XXXXXXXXXXXXXXX`)
   - Si EAN correspond → Valide et extrait le prix
   - Si EAN différent → Passe au suivant
4. Coupe après 8 mismatches EAN consécutifs

**⚠️ PROBLÈME ACTUEL : Détection anti-bot**
L'IP est bloquée après 2-3 collectes car la frappe n'est pas assez "humaine".
→ À corriger : Ajouter plus de délais aléatoires, mouvements souris, etc.

**Variables environnement** :
```bash
EAN=5000112611861
QUERY="coca-cola 1,75l"      # ou laisser vide pour utiliser les mots-clés seed
HOME_URL=https://www.intermarche.com/
USE_CDP=1
```

---

### 🟡 CASINO / SPAR

**Scripts** : `fetch_casino_price.py` et `fetch_spar_price.py` (même logique)

**Méthode** : Recherche MOTS-CLÉS + Validation EAN dans JSON-LD
1. Requête HTTP sur `/recherche/STORE_CODE?produit_recherche=query`
2. Parse les cartes produit
3. Ouvre chaque PDP
4. Lit le JSON-LD pour trouver `gtin13` (EAN)
5. Si EAN correspond → Valide

**Variables environnement** :
```bash
# Casino Shop Bègles
CASINO_STORE_CODE=TZ193
CASINO_STORE_SLUG=casino-shop-33130
CASINO_STORE_LABEL="Casino Shop · Bègles Pruniers"

# Spar Saint-Médard
CASINO_STORE_CODE=TL832
CASINO_STORE_SLUG=spar-33160
CASINO_STORE_LABEL="Spar Super · Saint-Médard-en-Jalles"
```

---

### 🔴 LECLERC DRIVE (Bruges)

**Scripts** : `fetch_leclerc_drive_price.py` + `manual_leclerc_cdp.py` (1371 lignes)

**Méthode** : Recherche MOTS-CLÉS + Validation EAN OU Image Matching
1. Navigue vers Leclerc Drive Bruges
2. Tape la requête **lentement** (human-like, 80-180ms entre caractères)
3. Attend les résultats (max 12 PDP testées)
4. Pour chaque carte :
   - Score basé sur tokens (marque, quantité, variante)
   - Ouvre la PDP, cherche lien "Informations pratiques"
   - Si EAN visible → Valide
   - Sinon → Fallback Image Matching avec image seed
5. Si aucun EAN exact, prend le meilleur `token_hits` avec `equivalent=true`

**⚠️ PROBLÈME : DataDome bloque l'IP OVH**
→ Nécessite proxy résidentiel ou tunnel SSH inverse (port 9223)

**Variables environnement** :
```bash
EAN=5000112611861
QUERY="Coca-Cola 1.75 L"
STORE_URL=https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx
USE_CDP=1
LECLERC_NO_DELAY=1           # Mode rapide (pour debug)
LECLERC_MAX_PDP=12           # Nombre max de PDP à tester
```

---

### 🔴 MONOPRIX

**Script** : `fetch_monoprix_price.py` (2952 lignes)

**Méthode** : Recherche MOTS-CLÉS + Image Matching OBLIGATOIRE

⚠️ **MONOPRIX NE SUPPORTE PAS LA RECHERCHE EAN**  
⚠️ **L'EAN N'EST JAMAIS VISIBLE SUR LES PAGES**  
→ La validation se fait **UNIQUEMENT** par comparaison d'images

1. Construit des requêtes courtes : `marque + type` (JAMAIS de poids/volume !)
   - ✅ Correct : "Hipro fraise", "Coca-Cola original"
   - ❌ Interdit : "Hipro 300g", "Coca-Cola 1.75L"
2. Tape la requête caractère par caractère
3. Pour chaque résultat :
   - Compare l'image candidate avec l'image seed (perceptual hash)
   - Vérifie les tokens de variante (amande, fraise, original...)
   - Vérifie la catégorie (yaourt, boisson, lessive...)
   - Vérifie la taille approximative
4. Si image match + tokens valides → Valide

**Variables environnement** :
```bash
EAN=5000112611861
QUERY="coca-cola original"   # PAS de quantité !
HOME_URL=https://courses.monoprix.fr/
USE_CDP=1
```

---

## 6. GÉNÉRATION MOTS-CLÉS (API OpenAI)

### Fonctionnement (ai_helpers.py)

Le module `ai_helpers.py` utilise l'API OpenAI pour générer des mots-clés de recherche intelligents.

### Activation
```bash
export USE_AI_ASSIST=true
export OPENAI_API_KEY="sk-..."
```

Ou dans `ai_helpers.toml` :
```toml
[openai]
api_key = "sk-..."
model_profile = "gpt-4o"
model_queries = "gpt-4o-mini"
```

### Processus
1. **Collecte Seeds** : Carrefour/Auchan/Chronodrive → titres, marques, descriptions
2. **summarize_product_seed()** : Envoie les seeds à OpenAI
3. **Prompt système** :
   ```
   Tu es un expert e-commerce. Génère des mots-clés pour retrouver un produit.
   FORMAT: "Marque + Produit + Poids/Vol"
   Ex: "Nutella Pâte à tartiner 400g", "Coca-Cola Soda 1.75L"
   ```
4. **Réponse** : JSON avec `profile` et `keywords` (3-5 variantes, ≤30 caractères)
5. **Post-traitement** (`_enforce_query_rules`) : Nettoie, déduplique, tronque

### Mots interdits (primary_keywords)
```python
_PRIMARY_FORBIDDEN = {
    "promo", "promotion", "lot", "pack", "offre", "produit",
    "adulte", "stérilisé", "senior", "course", "x2", "x3", ...
}
```

### Résultat stocké en MongoDB
```json
{
  "primary_keywords": ["Coca-Cola 1,75L", "Coca original"],
  "secondary_keywords": ["soda", "cola", "original", "1.75L"],
  "queries": {
    "leclerc": ["coca-cola 1,75l", "coca-cola original"],
    "monoprix": ["coca-cola original"]  // Sans quantité !
  }
}
```

---

## 7. MATCHING D'IMAGES

### Quand c'est utilisé
- **Monoprix** : TOUJOURS (pas d'EAN visible)
- **Leclerc** : Fallback si EAN introuvable

### Algorithme (image_matching.py + vision.py)

**Étape 1 : Perceptual Hash (aHash)**
```python
def _average_hash(image, hash_size=16):
    # 1. Convertir en niveaux de gris 16x16
    grayscale = image.convert("L").resize((16, 16))
    # 2. Calculer la moyenne des pixels
    avg = sum(pixels) / len(pixels)
    # 3. Créer un hash binaire (1 si pixel > moyenne)
    bits = 0
    for idx, pixel in enumerate(pixels):
        if pixel > avg:
            bits |= 1 << idx
    return bits
```

**Étape 2 : Variantes (full + center crop)**
```python
def _hash_variants(image):
    # Hash de l'image complète
    base = _average_hash(image)
    # Hash du centre (70%) pour ignorer les bords/ombres
    cropped = _center_crop(image, fraction=0.7)
    return [base, _average_hash(cropped)]
```

**Étape 3 : Distance de Hamming**
```python
def _hash_distance(a, b):
    return (a ^ b).bit_count()  # Nombre de bits différents
```

**Étape 4 : Comparaison couleur**
```python
def _color_signature(image):
    # Statistiques RGB sur différentes zones
    # (haut, milieu, gauche, droite)
    return tuple(stat_full + stat_upper + stat_mid + ...)
```

**Étape 5 : Décision**
```python
def compare_references(seed_ref, candidate_ref, threshold=16):
    # 1. Distance de hash ≤ 16 bits
    if min_distance > threshold:
        return False
    # 2. Delta couleur ≤ 25 (10% de 255)
    if min_color_delta > 25:
        return False
    return True
```

### Seuils
- **Hash distance** : ≤ 16 bits sur 256 → ~93% de similarité minimum
- **Color delta** : ≤ 25 sur 255 → ~10% de tolérance couleur

### Fonction principale
```python
from pipeline.image_matching import descriptor_matches_candidate

# Compare toutes les images seed avec l'image candidate
matches = descriptor_matches_candidate(
    descriptor={"image": "./assets/5000112611861.jpg"},
    candidate_ref="https://monoprix.fr/images/coca.jpg",
    ean="5000112611861",
    threshold=16
)
```

---

## 8. COMMANDES BASH ESSENTIELLES

### Sur le serveur OVH

```bash
# Connexion
ssh ubuntu@vps-a4a36a41.vps.ovh.net
cd ~/maxicourses-prod/maxicourses_test

# ═══════════════════════════════════════════════════
# DÉMARRAGE CHROME DEBUG (FAIRE EN PREMIER !)
# ═══════════════════════════════════════════════════
./start_chrome_debug.sh
# → Lance Chrome sur port 9222, profil .chrome-debug/

# Vérifier que Chrome tourne
curl -s http://127.0.0.1:9222/json/version | jq '.Browser'

# ═══════════════════════════════════════════════════
# DÉMARRAGE SERVER.PY
# ═══════════════════════════════════════════════════
USE_CDP=1 python3 server.py

# OU en arrière-plan :
USE_CDP=1 nohup python3 server.py > /tmp/server.log 2>&1 &

# ═══════════════════════════════════════════════════
# REDÉMARRAGE APRÈS MODIFICATION
# ═══════════════════════════════════════════════════
# ⚠️ OBLIGATOIRE après chaque modif de server.py !
pkill -f "server.py"
USE_CDP=1 python3 server.py

# OU pour Chrome aussi :
pkill -f chrome
./start_chrome_debug.sh
sleep 2
USE_CDP=1 python3 server.py

# ═══════════════════════════════════════════════════
# COLLECTE MANUELLE
# ═══════════════════════════════════════════════════
# Via API
curl -X POST http://127.0.0.1:5001/api/collect \
  -H 'Content-Type: application/json' \
  -d '{"ean":"5000112611861"}'

# Via script direct
USE_CDP=1 HEADLESS=0 python3 pipeline/run_pipeline.py \
  --ean 5000112611861

# Collecte une seule enseigne
USE_CDP=1 python3 pipeline/run_pipeline.py \
  --ean 5000112611861 \
  --adapters auchan

# ═══════════════════════════════════════════════════
# MàJ PRIX RAPIDE (URLs cachées)
# ═══════════════════════════════════════════════════
curl -X POST http://127.0.0.1:5001/api/update-price \
  -d '{"ean":"5000112611861"}'

# ═══════════════════════════════════════════════════
# SAUVEGARDER ÉTAT COOKIES
# ═══════════════════════════════════════════════════
USE_CDP=1 python3 save_state_from_cdp.py auchan
USE_CDP=1 python3 save_state_from_cdp.py courseu
USE_CDP=1 python3 save_state_from_cdp.py intermarche
```

### Sur ta machine locale (Mac)

```bash
# Tunnel pour Chrome distant
ssh -R 9223:localhost:9222 ovh-server

# Tunnel pour MongoDB
ssh -L 27017:127.0.0.1:27017 ubuntu@vps-a4a36a41.vps.ovh.net

# Lancer Chrome local pour le tunnel
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="./chrome-tunnel-profile"
```

---

## 9. PROBLÈMES À RÉSOUDRE (SUIVI HORAIRE)

**⚠️ MISE À JOUR OBLIGATOIRE TOUTES LES HEURES**

Quand un problème est résolu :
- ~~Le barrer~~
- Indiquer la solution en dessous

### 🟣 URGENT CRITIQUE (17/12/2025)

| Problème | Description | Impact |
|----------|-------------|--------|
| **🖥️ MongoDB = MATRICE CENTRALE** | TOUTES les données produit doivent être stockées en MongoDB. C'est la source de vérité unique pour le Backend OVH ET l'App iPhone | Architecture complète |
| **Images seed en BDD** | Les images doivent être collectées et stockées en MongoDB (binary ou URL) | Bloque matching Monoprix |
| **Affichage images dashboard** | Les thumbnails n'apparaissent pas dans index.html | UX + Validation impossible |

### 🔴 PRIORITÉ HAUTE (17/12/2025)

| Problème | Description | Impact |
|----------|-------------|--------|
| **Intermarché anti-bot** | IP bloquée après 2-3 collectes (frappe pas assez humaine) | Collecte Intermarché impossible |
| **Historique prix** | Non implémenté → Ajouter collection `price_history` | Impossible de suivre les fluctuations |
| **Collecte prix régulière** | Les champs `stores.*.price` sont souvent `null` | Comparaison impossible |

### 🟡 PRIORITÉ MOYENNE (17/12/2025)

| Problème | Description |
|----------|-------------|
| **Leclerc DataDome** | IP OVH bloquée → utiliser tunnel SSH inverse (port 9223) |
| **Carrefour Cloudflare** | Intermittent → relancer Chrome debug et sauvegarder état |

### ✅ RÉSOLU

| Problème | Solution |
|----------|----------|
| ~~Bouton supprimer~~ | Fonctionne correctement |
| ~~Sync seed_catalog → MongoDB~~ | 19/19 produits sync (17/12/2025) |

---

## 10. APPLICATION iOS

### Informations

| Élément | Valeur |
|---------|--------|
| **Dossier local** | `/Users/laurentpoupet/Sites/Maxicourses-IOS/Maxicourses_01_12_2025` |
| **Statut** | En développement actif |
| **Fonctionnalité** | Scanner code-barre + affichage prix |
| **Source de données** | MongoDB (via API OVH) |

### À développer
- Connexion API avec le backend OVH (`/api/product/{ean}`)
- Affichage comparatif des prix (lecture `stores.*.price`)
- Historique des scans (nouvelle collection `user_scans`)
- Push notifications promotions
- Interface utilisateur améliorée

### Architecture App ↔ MongoDB

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   iPhone App    │ ←──→ │   API OVH       │ ←──→ │   MongoDB       │
│   (Swift)       │      │   (server.py)   │      │   (maxicourses) │
└─────────────────┘      └─────────────────┘      └─────────────────┘
        │                        │                        │
        │  POST /api/scan        │  db.products.find()    │
        │  GET /api/product/EAN  │  db.user_scans.insert()│
        │  GET /api/compare/EAN  │  db.price_history...   │
        └────────────────────────┴────────────────────────┘
```

---

## 10.bis VISION FUTURE : IA PRÉDICTIVE

### Objectif
Transformer MongoDB en **matrice d'apprentissage** pour une IA qui :
1. Apprend les habitudes de consommation
2. Prédit les promotions
3. Suggère des substituts moins chers (Smart Substitution)
4. Envoie des notifications proactives

### Collections MongoDB prévues

```javascript
// Collection : products (existe déjà)
// → Données produits, prix, mots-clés

// Collection : price_history (À CRÉER)
{
  "ean": "5000112611861",
  "prices": [
    {"date": "2025-12-01", "auchan": 2.45, "carrefour": 2.50, "leclerc": 2.29},
    {"date": "2025-12-15", "auchan": 2.38, "carrefour": 2.50, "leclerc": 2.29}
  ]
}

// Collection : user_scans (À CRÉER - pour app iPhone)
{
  "user_id": "uuid-xxx",
  "ean": "5000112611861",
  "scanned_at": ISODate("2025-12-17T19:30:00Z"),
  "location": {"lat": 44.8378, "lng": -0.5792},  // Bordeaux
  "chosen_store": "auchan"
}

// Collection : substitutes (calculé automatiquement)
{
  "category": "cola 1.75l",  // Signature canonique
  "products": [
    {"ean": "5000112611861", "brand": "Coca-Cola", "avg_price": 2.40},
    {"ean": "3017620425035", "brand": "Pepsi", "avg_price": 2.20},
    {"ean": "3560070824984", "brand": "U Cola", "avg_price": 1.29}
  ],
  "best_value": "3560070824984"  // MDD le moins cher
}
```

### Smart Substitution (existe déjà dans le code)

```python
# descriptor_store.py
def find_substitutes(self, ean: str, limit: int = 5):
    """Trouve des substituts moins chers pour un EAN."""
    source = self.get_product(ean)
    sig = source.get("canonical", {}).get("normalized_signature")
    # ex: "cola 1.75l"
    
    # Cherche tous les produits avec la MÊME signature
    return self.products.find({
        "canonical.normalized_signature": sig,
        "ean": {"$ne": ean}  # Pas le même produit
    }).sort("stores.auchan.price", 1)  # Trier par prix
```

**Exemple** : 
- Input : Coca-Cola 1.75L (2.40€)
- Output : U Cola 1.75L (1.29€) → Économie 1.11€ !

### Notifications Push (futur)

| Trigger | Message |
|---------|---------|
| Prix baisse | "🔻 Coca-Cola est passé de 2.50€ à 2.20€ chez Leclerc !" |
| Meilleur prix | "💰 Ton Coca est à 2.40€ mais le U Cola équivalent est à 1.29€" |
| Promo prédite | "📅 Historiquement, ce produit est en promo fin de mois" |
| Stock faible | "⚠️ Dernières unités en stock pour ce produit" |

---

## 11. RÈGLES DE DÉVELOPPEMENT

### ⚠️ RÈGLE N°1 : VALIDATION OBLIGATOIRE

**Avant TOUT développement :**
1. Expliquer ce que tu vas faire
2. Attendre ma validation explicite ("OK", "Go", "Oui")
3. Ensuite seulement, coder

### ⚠️ RÈGLE N°2 : Demande toutes les heures

Toutes les heures, demande :
> "Souhaites-tu que j'enregistre les modifications dans GitHub ?"

### Après modification de fichiers critiques

| Fichier modifié | Action requise |
|-----------------|----------------|
| `server.py` | `pkill -f server.py && USE_CDP=1 python3 server.py` |
| `seed_catalog.py` | Redémarrer server.py |
| `fetch_*.py` | Tester avec un EAN connu |
| N'importe quel `.py` | Vérifier pas d'erreur de syntaxe |

---

## 12. SAUVEGARDE GITHUB

### Procédure

```bash
# 1. Vérifier les changements
git status
git diff

# 2. Ajouter les fichiers modifiés
git add -A

# 3. Commit avec date/heure
git commit -m "feat: <description> - $(date '+%Y-%m-%d %H:%M:%S')"
# Exemple : git commit -m "fix: collecte Intermarché - 2025-12-17 18:45:00"

# 4. Pousser
git push origin main
```

### Format des commits
```
<type>: <description courte> - YYYY-MM-DD HH:MM:SS

Types:
- feat: Nouvelle fonctionnalité
- fix: Correction de bug
- docs: Documentation
- refactor: Refactoring
- chore: Maintenance
```

### Fichiers à NE PAS commiter
- `.chrome-debug/` (profil Chrome)
- `*.log`
- `state/*.json` (cookies personnels)
- Clés API

---

## 📌 CHECKLIST AVANT TRAVAIL

- [ ] Tunnel MongoDB actif (`ssh -L 27017:...`)
- [ ] Chrome debug actif sur OVH (`./start_chrome_debug.sh`)
- [ ] server.py actif (`USE_CDP=1 python3 server.py`)
- [ ] Lire ce document
- [ ] Expliquer le développement prévu
- [ ] Attendre validation Laurent
- [ ] Coder
- [ ] Tester
- [ ] Demander si sauvegarde GitHub

---

> **Dernière mise à jour** : 2025-12-17 19:53 (Europe/Paris)  
> **Auteur** : Gemini (pour Laurent Poupet)
