# Handover Journal (Condensé)

Ce mémo remplace l’ancien journal volumineux. Il décrit l’état courant, les blocages critiques et la marche à suivre pour la prochaine session. Ajouter une nouvelle section datée à la fin à chaque relève.

---

## 2025-10-16T18:45 (Europe/Paris) – GPT (Codex CLI)

### Objectifs atteints
- Ajout complet de l’enseigne **Course U (Super U Eysines)** :
  - `fetch_courseu_price.py` (visionneuse Playwright + calcul prix/€ unitaire).
  - Intégration dans `run_pipeline.py`, `server.py`, `save_state_from_cdp.py`, `PROMPT_BOOTSTRAP.md`, `ONBOARDING.md`, `PRICE_COLLECTION_GUIDE.md` et `README.md`.
  - Support UI (`assets/logos/courseu.png`, logo + label dans `pipeline/index2.html`).
- Documentation purgée des anciens TODO : seules les consignes actuelles restent dans `ONBOARDING`, `PROMPT_BOOTSTRAP`, `PRICE_COLLECTION_GUIDE`, `README`.
- Journal présent (ce fichier) réduit aux éléments indispensables.

### État de l’enseigne Course U
- Les scripts fonctionnent mais se heurtent à deux protections :
  1. **Cloudflare** : nécessite un passage manuel dans Chrome 9222 (`start_chrome_debug.sh`) avant chaque run si la session a expiré.
  2. **Overlay marketing `div.mask`** : tant qu’il reste affiché, la barre de recherche est inutilisable. Playwright bascule alors sur `/recherche?q=…` → page promo (ex. lot Skip) → `status="NO_PRICE"` et `matched_ean` erroné.
- Nouvelle détection `CF_BLOCK` dans le fetcher + dumps HTML (`COURSEU_DUMP`) disponibles pour debug (`maxicourses_test/tmp/courseu`).

### Procédure Course U (à exécuter AVANT toute collecte)
1. `cd maxicourses_test && ./start_chrome_debug.sh`
2. Dans ce Chrome :
   - accepter cookies OneTrust / challenge Cloudflare,
   - fermer l’overlay `div.mask`,
   - saisir l’EAN Destop (ex. 3665468000312) et vérifier que la fiche Destop s’affiche (prix TTC + prix/L visibles).
3. Immédiatement sauvegarder l’état :  
   `USE_CDP=1 python3 save_state_from_cdp.py courseu`
4. Relancer la collecte :  
   `CHROME_USER_DATA=./.chrome-debug USE_CHROME=1 USE_CDP=1 HEADLESS=0 STORE_URL="https://www.coursesu.com/drive-superu-eysines" STORE_NAME="Super U Eysines" EAN=3665468000312 python3 fetch_courseu_price.py`
5. Vérifier que le JSON renvoie `status="OK"` + `matched_ean=3665468000312`.

### ToDo immédiat
1. Réaliser la procédure ci-dessus et valider un run complet Course U. Ajouter la preuve (`results/test-3665468000312/latest.json`, capture) + consigner l’horodatage.
2. Une fois Course U stabilisé, relancer `pipeline/run_pipeline.py --ean <EAN>` pour les EAN de référence (Orangina, Destop, etc.) afin de populater `results/summary.json`.
3. Reporter le succès/échec Course U (commande, statut, captures) dans ce fichier (nouvelle section datée) et dans `PROMPT_LOG.md` si des instructions utilisateur changent.
4. Si l’overlay réapparaît trop souvent : envisager l’enregistrement d’un parcours humain (`record_generic_navigation.py`) qui ferme la modale avant recherche.

### Rappels généraux
- Collecte seed : Carrefour Market → Carrefour City → Auchan → Chronodrive → Course U → Intermarché → Leclerc (drive) → Monoprix.
- Intermarché/Leclerc : toujours via Chrome 9222 (traces humaines).
- Toute modification doit être consignée dans `PROMPT_BOOTSTRAP.md`, `ONBOARDING.md` et dans ce journal.
- Pas de commits sans accord explicite.

---

(Ajouter les nouvelles sections ici)  

## 2025-11-01 – GPT (Codex CLI)

### Faits marquants
- Monoprix (`fetch_monoprix_price.py`) génère désormais en tête des requêtes humaines courtes : `Hipro fraise`, `Hipro fraise framboise`, `Hipro framboise`, `Hipro yaourt`. Les anciens termes verbeux restent en fallback si besoin.
- Ajout des variantes `fraise` / `framboise` dans `VARIANT_PATTERNS` + assouplissement du contrôle `missing_tokens` (ignore chiffres, accepte singulier/pluriel). Les fiches 300 g ne sont plus rejetées.
- Run de validation : `maxicourses_test/results/run-3033491485756-20251101-104543.json` (`status=OK`, prix 2,99 €, image match true).
- `manual_descriptors.json` (`3033491485756`) mis à jour avec les requêtes gagnantes + note horodatée.
- Destop 950 ml (EAN 3665468000312) validé après ajout de l’asset Monoprix (`pipeline/assets/3665468000312.jpg`) et extension des stopwords (`multi`, `usages`, `flacon`). Run : `maxicourses_test/results/run-3665468000312-20251101-113240.json`.
- Rappel : toute fiche Monoprix impose désormais un visuel référent dans `pipeline/assets/<EAN>.jpg`; sans cela le matching image bloque la collecte.

### Points ouverts
- Éventuellement réduire `MONOPRIX_MAX_TERMS` (actuel 12) si la nouvelle shortlist suffit partout ; pour l’instant laisser par défaut.
- Les variantes sucrées (cookie, mangue…) restent couvertes par la liste négative (`negatives.monoprix`) mais la revue complète des seeds textuels est encore à faire.

## 2025-10-31 – GPT (Codex CLI)

### Faits marquants
- Monoprix : le fetcher s’appuie désormais d’abord sur les requêtes « marque + variant » issues des seeds (`fetch_monoprix_price.py`). La validation impose le quadruple verrou (variant, catégorie, taille, image). Les runs `maxicourses_test/results/run-5411188118961-20251031-150919.json` et `...-170412.json` confirment que l’amande est bien reconnue via tokens + matching visuel.
- Monoprix : les descripteurs ont été enrichis (`manual_descriptors.json`) avec les clichés locaux (`maxicourses_test/pipeline/assets/*`) pour les EAN Alpro/Hipro. Les requêtes Monoprix restent encore verbeuses et bloquent sur `3033491485756` (fraise/framboise).
- Leclerc Drive : `manual_leclerc_cdp.py` n’utilise plus le cache PDP et embarque un mode rapide (`FAST_MODE`) qui divise tous les délais par 10 pour éviter les attentes de plusieurs minutes.
- Front comparateur : nouveaux logos spécifiques City/Market/Super (`maxicourses_test/assets/logos/`) et badge “Super” dans `pipeline/index2.html`.
- Carrefour Super : l’état JSON a été rafraîchi (`maxicourses_test/state/carrefour_super.json`) mais doit encore être rejoué proprement via Chrome 9222 (sélection « Lormont, Gironde, France »).

### Résultats & captures
- `5411188118961` → `status=OK`, prix 2,45 € chez Monoprix (`maxicourses_test/results/latest.json`).
- `5411188103387` → toujours `NO_RESULTS` avec la génération automatique actuelle (`maxicourses_test/results/run-5411188103387-20251031-153833.json`).
- `3033491485756` → `NO_RESULTS` malgré quatre requêtes dérivées, voir `maxicourses_test/results/run-3033491485756-20251031-165005.json`.
- Assets images ajoutés : `maxicourses_test/pipeline/assets/5411188118961.jpg`, `...8103387.jpg`, `...48756.jpg`.

### ToDo immédiat
1. Finaliser `build_query_terms()` (Monoprix) pour privilégier 2–3 requêtes « marque + saveur » (ex. `hipro fraise`, `hipro framboise`). Journaliser les termes testés pour le debug.
2. Retester `3033491485756` et `5411188103387` une fois le générateur raffiné ; archiver la requête gagnante dans `manual_descriptors.json`.
3. Reprendre la capture humaine Carrefour Super Lormont (Chrome 9222) pour stabiliser `state/carrefour_super.json` et confirmer la collecte multi-Carrefour.
4. Mettre à jour `docs/PRICE_COMPARATOR_PLAN.md` et `docs/monoprix_hotfix_brief.md` après validation du point 1.
5. Prévoir une passe sur les logos Carrefour (Super) côté `pipeline/index2.html` lorsque la collecte sera validée pour éviter l’affichage « Market » par défaut.

## 2025-10-17 – GPT (Codex CLI)

### Faits marquants
- Profil Chrome remote Course U remis à zéro (`maxicourses_test/.chrome-debug` renommé) puis session reconstruite : challenge Cloudflare validé, cookies/overlay fermés, `state/courseu.json` régénéré.
- `fetch_courseu_price.py` enrichi : suppression systématique de la `div.mask` + mémorisation automatique des PDP Course U (`courseu_url`/`courseu_slug` dans `manual_descriptors.json`) afin de rejouer directement les fiches et limiter Cloudflare.
- Documentation mise à jour (`ONBOARDING`, `PROMPT_BOOTSTRAP`, `PRICE_COLLECTION_GUIDE`, `README`) avec la méthode PDP et la procédure de reset Chrome.

### Collectes Course U validées
- Destop 950 ml – JSON : `maxicourses_test/results/test-3665468000312/courseu-20251017-105656.json` (prix 3,76 € / 3,96 €/L, `matched_ean` OK).
- Savora 385 g – JSON : `maxicourses_test/results/test-8712100731822/courseu-20251017-105952.json` (prix 2,32 € / 6,03 €/kg).
- Orangina 1,5 L – JSON : `maxicourses_test/results/test-3124480200433/courseu-20251017-110142.json` (prix 2,15 € / 1,43 €/L).

### Points de vigilance
- Cloudflare bloque à nouveau après plusieurs hits rapprochés (ex. `maxicourses_test/results/test-3665468000312/run-courseu-20251017-131212.json`). Avant tout nouveau run massif, patienter quelques minutes ou relancer Chrome 9222 avec profil vierge puis resauvegarder la state.
- Vérifier régulièrement que les URLs PDP stockées dans `manual_descriptors.json` restent valides et les mettre à jour si Course U change les slugs produits.

### Suites suggérées
1. Relancer `python3 pipeline/run_pipeline.py --ean <EAN>` pour remettre `results/summary.json` à jour avec les prix Course U validés.
2. Ajouter captures si besoin (non prises aujourd’hui) pour compléter le dossier de preuves.
