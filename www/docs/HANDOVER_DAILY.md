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
