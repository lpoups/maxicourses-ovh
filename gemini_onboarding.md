# Gemini Onboarding: Maxicourses Project Status (December 2025)

**This document serves as the "State of the Union" for the next Gemini agent picking up the project.**
> **Mission**: Build the perfect Price Comparator requiring B2B precision and B2C intelligence (Smart Substitution).
tout les tests en modifications de codes doivent etre réalisé directement sur le serveur OVH et non sur le serveur de ma machine locale!

tout les tests doivent etre réalisés avec le tunnel SSH entre mon ordi et le serveur OVH afin que je puisse controler ce qui est réellement fait ainsi que le control des resultats et définir si ils sont probants!

---
Carrefour City/Market/Super auchan, chronodrive, courseu, g20 sont strictement recherche EAN
Intermarche recherche par mots cles et validation avec l'ean produit qui se trouve dans le lien "href" de la fiche produit (donc devient magasin seed dès validation de l'ean produit )
Casino et spar recherche par mots cles et validation de l'EAN present dans la page produit (donc deviennent magasin seed des validation de l'ean produit) !
Leclerc recherche par mots cles et validation par EAN visible dans le lien "Informations pratiques" si ean pas present alors validation par "matching image magasin seed"
Monoprix recherche par mots cles et validation uniquement par "matching d'image magasin seed" les mots clés de recherche pour monoprix ne doivent pas comporter de quantité de poids ou de volume mais doivent intégrer la quantité de produit exemple 6x33cl et attention il ne doit pas y avoir d'espace entre la quantite exemple 500g ou 1.75l ou 33cl et toujours en minuscule il faut que l'IA analyse l'ensemble de ces informations afin de déterminer une méthode de recherche pour chaque magasin car chaques magasin a ses propres methodes de recherche!
nous devons enregistrer en base de données chaque descriptifs de chaque magasins seed (produit trouvé et ean validé) cela veut dire que tout les magasin peuvent etre seed sauf monoprix car on ne peut pas recupérer l'ean sur le site!
l'ensemble des descriptifs de chaque magasins doit etre envoyé à l'IA via API OpenAI (on entend par descriptif produit : le nom du produit, la marque du produit, type de produit, le gout du produit, quantité de produit, etc...) en général le descriptif du produit répresente entre 5 et 10 mots.
chaque combinaison de mots cles ayant permis de trouver un produit doit etre ajouter à la base données de l'ean afin de permettre d'avoir des recherches plus rapides pour les futurs magasins ne permettant pas de recherche EAN direct.

Il reste à corriger le bug concernant la collecte et le stockage en base de données des images des produits afin d'afficher le thumbnail dans la fiche produit du dashboard et l'image sert également d'image seed pour le matching d'image sur monoprix et si besoin leclerc
Il reste encore à régler le bug empéchant d'effacer une fiche produit dans le dashboard : https://api.maxicourses.fr/index.html (index_ovh_prod.html)

# Rappel descriptif de Maxicourses.fr et Maxicourses APP
Ok, nous allons donc lancer le site MaxiCourse. Le projet est de mettre en place un comparateur de prix pour les enseignes de la grande distribution, par exemple Carrefour, Leclerc, Auchan, Intermarché, courseU, G20, chronodrive, Colruyt, Lidl, Aldi, Picard, et plein d'autres à la suite. Aujourd'hui ce que nous allons mettre en place c'est un proof of concept, c'est à dire à démontrer que le système fonctionne. Le principe de MaxiCourse c'est in fine, d'avoir la possibilité de scanner avec son iPhone un code-barre, de l'envoyer sur un serveur, ensuite à partir de ce serveur on va checker le descriptif du produit, ensuite comparer les prix sur les différentes plateformes. Une fois qu'on a le descriptif, on a le code-barre, on a le descriptif, donc on peut aller chercher sur toutes les plateformes

LIRE le fichier : 

LIRE TOUS LES FICHIERS dans "docs"

les fichiers de maxicourses ovh se trouve dans maxicourses-ovh

Lire le fichier MIGRATION_OVH.md

# IMPORTANT!!!
ajouter ICI toutes les informations pour la maintenance et le fonctionnement de maxicourses sur le serveur OVH comment il fonctionne ce qu'il faut savoir pour les prochains GPT!!!


# à partir de maintenant maxicourses.fr fonctionne à partir du serveur OVH page accueil : http://api.maxicourses.fr/index.html toutes les information de connexion 
sont disponibles dans le fichier : OVH_SERVER_SETUP.md

Bien s'assurer que c'est bien "chrome debug 9222" qui est installé sur le serveur OVH et pas "chromium"

Trouver les bugs de collecte chez leclerc! 

TODO
Corriger le bug de collete de lerclerc : Les mots cles de recherche sont excellent mais lors du resultat de recherche aucun produit n'est selectionné et de nouveau mots cles de recherche et toujours pareil aucun produit n'est selectionné alors que le bon produit est présent dans la liste de resultat à chaque recherche. Cela prouve que la selection des mots cles est bonne mais le robot ne fait pas le travail!

---

## 🧪 MODE TEST MAXICOURSES

> **⚠️ TOUS LES TESTS DOIVENT SE FAIRE VIA LE DASHBOARD OVH !**

### Architecture de Test
```
Machine Locale (IP résidentielle)
    ↓ Tunnel SSH port 9222
Serveur OVH
    ├── Chrome Debug (port 9222) ← utilise le tunnel
    ├── MongoDB (port 27017) ← local au serveur
    ├── server.py (port 5001) ← API
    └── Dashboard (index.html) ← Interface de test
```

### Ce que fait le tunnel SSH
- **Port 9222** : Chrome debug - permet aux scrapers de naviguer avec une IP résidentielle
- **Le tunnel NE COUVRE PAS MongoDB** - MongoDB est uniquement accessible depuis OVH

### Comment tester
1. Ouvrir le dashboard : `http://api.maxicourses.fr/index.html`
2. Lancer une collecte depuis le dashboard
3. Les scripts s'exécutent sur OVH avec accès MongoDB
4. Chrome utilise l'IP locale via le tunnel SSH

### ❌ Ne PAS faire
- Ne pas lancer les scripts Python en local (pas d'accès MongoDB)
- Ne pas essayer de tester Monoprix/Leclerc en local

---

## 🔒 ARCHITECTURE IMAGES - 100% OVH (14/12/2025)

> **⚠️ AUCUN FICHIER LOCAL ! Tout est URL dans MongoDB.**

### Comment ça marche
1. **Collecte** → Le scraper extrait l'URL de l'image produit
2. **Stockage** → L'URL HTTP est stockée directement dans `descriptor.image` dans MongoDB
3. **Matching** → Monoprix/Leclerc comparent via HTTP (hash distant vs hash candidat)

### Fonctions modifiées
- `run_pipeline.py` ligne 3095+ : **Stocke directement l'URL** (pas de téléchargement)
- `ensure_local_image_asset` : **Garde l'URL HTTP** sans téléchargement local

### Pourquoi c'est important
- Le serveur OVH n'a pas accès au dossier `assets/` local
- Le téléchargement échouait souvent (403, timeout)
- Les URLs HTTP fonctionnent partout

---

## 🔒 MÉTHODE COURSE U - NE JAMAIS MODIFIER !

> **⚠️ ATTENTION: Cette méthode fonctionne parfaitement. NE PAS LA MODIFIER sauf lors du passage en mode collecte full serveur OVH.**

### Architecture actuelle (Phase de test)
```
Dashboard OVH → server.py → run_pipeline.py → fetch_courseu_price.py
                    ↓
            CDP_URL=http://127.0.0.1:9223
                    ↓
            Tunnel SSH (OVH:9223 → Local:9222)
                    ↓
            Chrome debug local (IP résidentielle)
```

### Étapes de collecte Course U (fetch_courseu_price.py)

1. **Connexion CDP** au port 9223 (tunnel vers Chrome local 9222)
2. **Reset cache/cookies/storage** OBLIGATOIRE avant chaque collecte (anti-Cloudflare)
   ```python
   await ctx.clear_cookies()
   client = await page.context.new_cdp_session(page)
   await client.send("Network.clearBrowserCache")
   await client.send("Storage.clearDataForOrigin", {
       "origin": "https://www.coursesu.com",
       "storageTypes": "all"
   })
   ```
3. **Navigation** vers `https://www.coursesu.com/drive-superu-eysines`
4. **Acceptation cookies** via sélecteur `button:has-text('Accepter & Fermer')`
5. **Recherche EAN** dans le champ `input[id='q']`
6. **Clic sur le premier produit** `a[href*='/p/']`
7. **Extraction prix** via sélecteur CSS `.product-price`
   - Le texte contient: `"3,88 €\n0,65 €/l"`
   - Première ligne = prix pack
   - Deuxième ligne = prix unitaire
8. **Extraction métadonnées** via JSON-LD (EAN, titre, image, marque)

### Sélecteurs clés Course U
| Élément | Sélecteur |
|---------|-----------|
| Prix pack + unitaire | `.product-price` |
| Bouton cookies | `button:has-text('Accepter & Fermer')` |
| Champ recherche | `input[id='q']` |
| Lien produit | `a[href*='/p/']` |

### Pourquoi le reset cache est OBLIGATOIRE
- Cloudflare bloque les sessions avec cookies/cache corrompus
- Sans reset → blocage CF même avec IP résidentielle
- Avec reset → navigation fluide, pas de blocage

### Résultat attendu (testé le 14/12/2025)
```json
{
  "status": "MATCHED",
  "price": "3,88 €",
  "unit_price": "0,65 €/l",
  "title": "Eau minérale naturelle gazeuse PERRIER - 6x1L",
  "matched_ean": "7613035833289",
  "image": "https://www.coursesu.com/dw/image/..."
}
```

---

## 1. Core Architecture Shift: OVH Centric & Database Driven
> [!IMPORTANT]

> **MAXICOURSES IS NOW 100% OVH-CENTRIC & DATABASE BACKED.**
> There is **no local development** logic. Code is pushed to OVH (`vps-222a760c`) where the real action happens.

*   **Infrastructure**: MongoDB 7.0 is now the Heart of the system ("The Memory").
*   **Production Codebase**: Located on OVH server.
*   **Local Codebase**: Staging area only. Sync via `deploy_ovh.sh`.

---

## 2. The Master Plan (Roadmap to Perfection)

### Phase 1-4: The Foundation (DONE ✅)
*   **Infrastructure**: VPS Setup, SSH Tunneling, `playwright` anti-bot bypass.
*   **Collection**: Robust scrapers for Carrefour (JSON parsing), Auchan (Human clicks), Drive etc.
*   **Finder**: `finder.py` uses Real Fetchers (subprocesses) to guarantee data parity. No more external APIs.

### Phase 5: The Memory (DONE ✅ - Dec 9, 2025)
> *Replacing the fragile JSON/TXT cache with a robust Database.*
*   **DB Setup**: MongoDB installed on OVH + SSH Tunneling for remote access/visualization.
*   **Backend**: `descriptor_store.py` refactored to use `pymongo`.
*   **Migration**: `migrate_to_mongo.py` successfully imported Seed Catalog + Cache into DB.
*   **Status**: The "Brain" is ready. It remembers 30+ products and their "Golden Records".

### Phase 6: The Wiring (DONE ✅ - Dec 9, 2025)
> *Connecting the App to its new Memory.*
*   **Result**: `run_pipeline.py` now reads/writes directly to MongoDB.
*   **Disabled**: `descriptor_cache.json` reads (shimmed to no-op).
*   **Enabled**: Auto-Learning (Brand inference, Keyword refinement) now persists to Golden Records.

### Phase 7: The Intelligence (DONE ✅) 
> *The "Smart Substitution" Engine.*
*   **Engine**: `normalizer.py` computes Need States (e.g. `cola 1.5l`).
*   **Result**: System can now substitute National Brands with Private Labels.
*   **Verified**: `test_substitution.py` confirms Coke -> Bryce Cola match.

### Phase 8: Visual Intelligence (DONE ✅)
> *The Eyes of the Comparator.*
*   **Engine**: `pipeline/vision.py` implements Histogram Similarity.
*   **Result**: Pipeline now double-checks Found Images against Seed Image.
*   **Metric**: Scores computed and logged in `metadata` for verification.

### Phase 9: Smart Comparison UI (NEXT IMPERATIVE 🚨)
> *The Payoff.*
*   **Goal**: Display "Cheapest Cola = Bryce Cola at Leclerc (1.20€)".
*   **Tech**: Aggregate Prices from Source + Substitutes -> Sort -> Display.

---

## 3. Remote Collection & SSH Tunnel Visualization
The user's favorite feature is "Real Time Visualization". This allows them to verify what the bot is doing on the remote server by seeing it inside their **local** Chrome browser.

**Key Configuration:**
*   `run_pipeline.py` is patched to force `CDP_URL="http://127.0.0.1:9223"`.
*   **Database Access**: Tunnel `Local:27017 -> Remote:27017` to view/edit MongoDB content.

---

## 4. File Inventory & Critical Paths

| File Path | Purpose | Status |
| :--- | :--- | :--- |
| `docs/PRODUCT_MANIFESTO.md` | **THE LAW**. The Vision, Rules, and Architecture. Read this first. | **NEW** |
| `www/maxicourses_test/descriptor_store.py` | **MEMORY**. MongoDB Repository. The source of truth for Products. | **NEW** |
| `infra/ovh/install_mongo_ovh.sh` | **INFRA**. Setup script for DB. | **DONE** |
| `www/maxicourses_test/fetch_carrefour_price.py` | **CORE**. Main Carrefour logic (JSON parsing). | **PROD READY** |
| `www/maxicourses_test/fetch_auchan_price.py` | **CORE**. Main Auchan logic (Human Click). | **PROD READY** |

---

## 5. Next Steps for Gemini
If you are picking up this project:
1.  **Check the Wiring**: Ensure `run_pipeline.py` is using `ProductRepository` (DB). If not, **Do it immediately**.
2.  **Respect the Vision**: Refer to `PRODUCT_MANIFESTO.md` for any functional question.
3.  **Deploy First**: Always push changes to OVH before testing.

## 6. Critical Reading List for Next Agent (MUST READ)
To understand the current state and logic, you **MUST** read these files in order:
1.  `www/maxicourses_test/server.py`: The entry point (API & process management).
2.  `www/maxicourses_test/pipeline/run_pipeline.py`: The orchestrator of data collection.
3.  `www/maxicourses_test/pipeline/finder.py`: The logic for matching and validating products types (Fixed "AttributeError" here).
4.  `www/maxicourses_test/descriptor_store.py`: The MongoDB interface (Golden Records).
5.  tout les tests de collectes doivent impérativement passer par le chrome debug 9222 de ma machine vien le tunnel SSH entre mon ordi et ovh afin que je puisse controler ce qui est réellement fait ainsi que le control des resultats et définir si ils sont probants!

