# 🚀 MAXICOURSES — PLAN DE DÉVELOPPEMENT IA

> **Vision** : Créer le meilleur comparateur de prix de la grande distribution française,
> alimenté par l'Intelligence Artificielle.

**Date de création** : 2025-12-17  
**Auteur** : Gemini (pour Laurent Poupet)

---

## 📋 SOMMAIRE

1. [Vision Produit](#1-vision-produit)
2. [Architecture Technique Cible](#2-architecture-technique-cible)
3. [Roadmap par Phase](#3-roadmap-par-phase)
4. [Détails Techniques IA](#4-détails-techniques-ia)
5. [Stack Technologique](#5-stack-technologique)
6. [Métriques de Succès](#6-métriques-de-succès)

---

## 1. VISION PRODUIT

### Le Problème
Les consommateurs perdent de l'argent car :
- Ils ne connaissent pas les prix dans TOUS les magasins
- Ils ne savent pas qu'un produit MDD équivalent existe à -40%
- Ils comparent les packs et non les prix au kilo

### La Solution Maxicourses

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MAXICOURSES IA                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1️⃣ SCAN EAN                                                                │
│     └─ "Tu as scanné Coca-Cola 1.75L - Voici les prix :"                    │
│        • Auchan : 2.38€ (1.36€/L)                                           │
│        • Leclerc : 2.29€ (1.31€/L) ⭐ MEILLEUR PRIX                         │
│        • Carrefour : 2.50€ (1.43€/L)                                        │
│                                                                             │
│  2️⃣ SMART SUBSTITUTION (par prix au kilo/litre)                            │
│     └─ "Produits équivalents moins chers :"                                 │
│        • U Cola 1.75L → 1.29€ (0.74€/L) 💰 ÉCONOMIE 43%                     │
│        • Bryce Cola 1.5L → 0.99€ (0.66€/L) 💰 ÉCONOMIE 51%                  │
│                                                                             │
│  3️⃣ COMPARAISON INTELLIGENTE                                               │
│     └─ "Jambon Herta 4 tranches" (2.00€ = 14.29€/kg)                        │
│        vs "Jambon U 6 tranches" (2.20€ = 10.47€/kg)                         │
│        → "Prends le 6 tranches, tu économises 27% au kilo !"                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. ARCHITECTURE TECHNIQUE CIBLE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ARCHITECTURE MAXICOURSES IA                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────────────────────────────────────────────┐ │
│  │  iPhone App │───▶│              API Gateway (OVH)                      │ │
│  │  (Swift)    │    │              Flask / FastAPI                        │ │
│  └─────────────┘    └───────────────────────┬─────────────────────────────┘ │
│                                             │                               │
│                     ┌───────────────────────┼───────────────────────┐       │
│                     ▼                       ▼                       ▼       │
│  ┌─────────────────────────┐  ┌─────────────────────┐  ┌──────────────────┐ │
│  │   COLLECTE MODULE      │  │   IA MODULE         │  │   DATA MODULE    │ │
│  │   • Playwright CDP     │  │   • OpenAI API      │  │   • MongoDB      │ │
│  │   • Anti-bot bypass    │  │   • Embeddings      │  │   • Redis cache  │ │
│  │   • Price scrapers     │  │   • RAG Pipeline    │  │   • Price history│ │
│  │   • Image download     │  │   • Vision AI       │  │   • User prefs   │ │
│  └─────────────────────────┘  └─────────────────────┘  └──────────────────┘ │
│                                             │                               │
│                     ┌───────────────────────┴───────────────────────┐       │
│                     ▼                                               ▼       │
│  ┌─────────────────────────────────────┐  ┌────────────────────────────────┐│
│  │   ML MODELS (Future)               │  │   NOTIFICATION SERVICE        ││
│  │   • Price prediction (LSTM)        │  │   • Push notifications         ││
│  │   • Demand forecasting             │  │   • Email alerts               ││
│  │   • User behavior clustering       │  │   • SMS (promotions)           ││
│  │   • Image classification (CNN)     │  │                                ││
│  └─────────────────────────────────────┘  └────────────────────────────────┘│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. ROADMAP 6 SEMAINES (Déc 2025 → Fin Janvier 2026)

> **Objectif** : MVP complet avec IA fin janvier 2026

```
SEMAINE 1 (18-24 Déc) │ SEMAINE 2 (25-31 Déc) │ SEMAINE 3 (1-7 Jan)
─────────────────────┼──────────────────────┼────────────────────
MongoDB + Images     │ Prix Unitaire €/kg   │ Smart Substitution
                     │                      │
SEMAINE 4 (8-14 Jan) │ SEMAINE 5 (15-21 Jan)│ SEMAINE 6 (22-31 Jan)
─────────────────────┼──────────────────────┼────────────────────
Embeddings + RAG     │ App iPhone v1        │ Tests + Déploiement
```

---

### 📅 SEMAINE 1 : FONDATIONS (18-24 Décembre 2025)
**MongoDB = Matrice Centrale**

| Jour | Tâche | Durée |
|------|-------|-------|
| Mer 18 | ✅ Images seed → MongoDB (fichiers locaux + sync) | 1j |
| Jeu 19 | Fix dashboard affichage images | 1j |
| Ven 20 | Collecte prix régulière (cron 2x/jour) | 1j |
| Sam 21 | Fix Intermarché anti-bot (human typing) | 1j |
| Dim 22 | Collection `price_history` + migration | 1j |
| Lun 23-24 | Tests + corrections | 2j |

**Livrable** : Collecte stable 12 enseignes, données centralisées

---

### 📅 SEMAINE 2 : PRIX UNITAIRE (25-31 Décembre 2025)
**Normalisation €/kg, €/L**

| Jour | Tâche |
|------|-------|
| Mer 25 | Parser quantité intelligent (regex + fallback) |
| Jeu 26 | Calcul `unit_price_per_kg` automatique |
| Ven 27 | Stocker en MongoDB + index |
| Sam 28 | API `/api/compare/{ean}` |
| Dim 29-31 | Tests + validations |

**Livrable** : Tous les produits ont un prix au kilo normalisé

---

### 📅 SEMAINE 3 : SMART SUBSTITUTION (1-7 Janvier 2026)
**Trouver les équivalents MDD moins chers**

| Jour | Tâche |
|------|-------|
| Mer 1 | Créer taxonomy catégories (JSON) |
| Jeu 2 | Signature canonique améliorée |
| Ven 3 | Algorithme matching par catégorie |
| Sam 4 | Tri par prix au kilo |
| Dim 5 | API `/api/substitutes/{ean}` |
| Lun 6-7 | Tests avec vrais produits |

**Livrable** : API retourne top 3 substituts moins chers

---

### 📅 SEMAINE 4 : IA EMBEDDINGS + RAG (8-14 Janvier 2026)
**Recherche sémantique avec IA**

| Jour | Tâche |
|------|-------|
| Mer 8 | Générer embeddings OpenAI pour tous produits |
| Jeu 9 | Stocker vecteurs en MongoDB (Atlas Vector) |
| Ven 10 | Recherche sémantique (`$vectorSearch`) |
| Sam 11 | Pipeline RAG : query → embeddings → LLM |
| Dim 12 | API `/api/search?q=...` naturel |
| Lun 13-14 | Tests + optimisation |

**Livrable** : Recherche "jambon moins cher" → résultats intelligents

---

### 📅 SEMAINE 5 : APP IPHONE MVP (15-21 Janvier 2026)
**Application fonctionnelle**

| Jour | Tâche |
|------|-------|
| Mer 15 | Scan code-barre → appel API |
| Jeu 16 | Affichage prix tous magasins |
| Ven 17 | Affichage substituts recommandés |
| Sam 18 | Comparaison par prix au kilo |
| Dim 19 | UI polish + animations |
| Lun 20-21 | Tests sur iPhone réel |

**Livrable** : App iPhone MVP testable

---

### 📅 SEMAINE 6 : TESTS + DÉPLOIEMENT (22-31 Janvier 2026)
**Production ready**

| Jour | Tâche |
|------|-------|
| Mer 22-24 | Tests end-to-end complets |
| Ven 25 | Fix bugs critiques |
| Sam 26 | Documentation finale |
| Dim 27 | Déploiement production OVH |
| Lun 28-29 | Tests utilisateurs beta |
| Mar 30-31 | Ajustements finaux |

**Livrable** : 🎉 Maxicourses IA en production !

---

---

## 4. DÉTAILS TECHNIQUES IA

### Comparaison Prix Unitaire (Algorithme)

```python
def compare_by_unit_price(ean: str) -> list:
    source = db.products.find_one({"ean": ean})
    
    category = source["canonical"]["category"]
    product_type = source["canonical"]["type"]
    quantity_kg = source["quantity_normalized"]["in_kg"]
    unit_price = source["stores"]["auchan"]["unit_price_per_kg"]
    
    substitutes = db.products.find({
        "canonical.category": category,
        "canonical.type": product_type,
        "quantity_normalized.in_kg": {
            "$gte": quantity_kg * 0.5,
            "$lte": quantity_kg * 1.5
        },
        "ean": {"$ne": ean}
    }).sort("stores.auchan.unit_price_per_kg", 1)
    
    results = []
    for sub in substitutes[:5]:
        sub_unit_price = sub["stores"]["auchan"]["unit_price_per_kg"]
        savings = (1 - sub_unit_price / unit_price) * 100
        results.append({
            "ean": sub["ean"],
            "name": sub["name"],
            "unit_price_per_kg": sub_unit_price,
            "savings_percent": round(savings, 1)
        })
    
    return results
```

### Catégorisation Produits (Taxonomy)

```javascript
{
  "taxonomy": {
    "boissons": {
      "sodas": {"cola": [], "limonade": [], "energy": []},
      "eaux": {"plate": [], "gazeuse": []},
      "jus": {"orange": [], "multifruits": []}
    },
    "charcuterie": {
      "jambon": {"blanc": {"superieur": [], "standard": []}, "sec": []}
    },
    "produits_laitiers": {
      "yaourts": {"nature": [], "fruits": [], "grec": []}
    }
  }
}
```

---

## 5. STACK TECHNOLOGIQUE

| Composant | Technologie |
|-----------|-------------|
| **Backend** | Python + FastAPI |
| **Base de données** | MongoDB Atlas |
| **Cache** | Redis |
| **Scraping** | Playwright + CDP |
| **Embeddings** | OpenAI text-embedding-3-small |
| **LLM** | GPT-4o / Claude 3.5 |
| **Vision** | OpenAI Vision / TensorFlow |
| **ML** | scikit-learn / TensorFlow |
| **Mobile** | Swift (iOS) / React Native |
| **Notifications** | Firebase Cloud Messaging |
| **Hosting** | OVH VPS + Docker |

---

## 6. MÉTRIQUES DE SUCCÈS

### KPIs Phase 1-2
- [ ] 100% produits ont un prix unitaire normalisé
- [ ] < 5% d'erreur sur les prix collectés
- [ ] Collecte quotidienne automatique

### KPIs Phase 3-4
- [ ] > 80% de produits ont des substituts trouvés
- [ ] Précision substitution > 90%
- [ ] Temps de réponse API < 200ms

### KPIs Phase 5-7
- [ ] App Store rating > 4.5 ⭐
- [ ] > 10,000 utilisateurs actifs/mois
- [ ] Économie moyenne utilisateur > 15€/mois

---

> **Document vivant** - Mise à jour : 2025-12-17 22:16  
> **Version** : 2.0 (Timeline condensé 6 semaines)
