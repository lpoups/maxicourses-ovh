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
- Les requêtes gagnantes sont désormais consignées directement dans `seed_catalog.py` (le fichier `manual_descriptors.json` ne sert plus qu'aux hints Course U).
- Destop 950 ml (EAN 3665468000312) validé après ajout de l’asset Monoprix (`pipeline/assets/3665468000312.jpg`) et extension des stopwords (`multi`, `usages`, `flacon`). Run : `maxicourses_test/results/run-3665468000312-20251101-113240.json`.
- Rappel : toute fiche Monoprix impose désormais un visuel référent dans `pipeline/assets/<EAN>.jpg`; sans cela le matching image bloque la collecte.

### Points ouverts
- Éventuellement réduire `MONOPRIX_MAX_TERMS` (actuel 12) si la nouvelle shortlist suffit partout ; pour l’instant laisser par défaut.
- Les variantes sucrées (cookie, mangue…) restent couvertes par la liste négative (`negatives.monoprix`) mais la revue complète des seeds textuels est encore à faire.

## 2025-10-31 – GPT (Codex CLI)

### Faits marquants
- Monoprix : le fetcher s’appuie désormais d’abord sur les requêtes « marque + variant » issues des seeds (`fetch_monoprix_price.py`). La validation impose le quadruple verrou (variant, catégorie, taille, image). Les runs `maxicourses_test/results/run-5411188118961-20251031-150919.json` et `...-170412.json` confirment que l’amande est bien reconnue via tokens + matching visuel.
- Monoprix : les visuels référents ont été ajoutés dans `maxicourses_test/pipeline/assets/*` pour les EAN Alpro/Hipro (plus aucun mot-clé n'est conservé dans `manual_descriptors.json`). Les requêtes Monoprix restent encore verbeuses et bloquent sur `3033491485756` (fraise/framboise).
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
2. Retester `3033491485756` et `5411188103387` une fois le générateur raffiné ; archiver la requête gagnante dans `seed_catalog.py` (Finder only).
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

## 2025-11-14T10:10 (Europe/Paris) – GPT (Codex CLI)

### Faits marquants
- `fetch_intermarche_price.py` coupe désormais la recherche après 8 mismatches EAN et marque explicitement le produit comme absent (`_meta.abort_search` avec raison horodatée).
- `run_pipeline.py` réagit à ce signal pour passer immédiatement à l’enseigne suivante, ce qui évite les boucles infinies et enregistre une note « produit absent ».
- Ajout du dataset fraise `5411188114536` dans `pipeline/index2.html` + rafraîchissement des JSON `results/test-5411188114536/{latest,summary}.json` pour alimenter la vitrine.

### Suivi / prochaines étapes
- Confirmer que l’entrée Intermarché « produit absent » reste visible côté front (`pipeline/index2.html`) et qu’aucun autre run n’a supprimé les dumps debug attendus.
- Si d’autres EAN non trouvés reproduisent le pattern, ajuster le seuil `INTERMARCHE_EAN_MISMATCH_ABORT` et enrichir `docs/ONBOARDING.md` avec la procédure.

## 2025-11-14T11:30 (Europe/Paris) – GPT (Codex CLI)

### Faits marquants
- Auchan Talence Gallieni : slug forcé (`auchan-drive-supermarche-talence-gallieni`) + clic automatique sur « Choisir ce drive/Afficher le prix » + attente explicite du widget prix → le fetcher retourne à nouveau des JSON `status="OK"` (test sur 5411188118961).
- Comparateur `pipeline/index2.html` : `resolveDescriptor()` fusionne désormais correctement les méta-données issues des runs (images locales, Nutri/Eco-score, source) sans que le cache seed « unknown » les écrase ; fallback possible via `manual_descriptors.json`.

### Suites suggérées
- Relancer `run_pipeline.py --ean 5411188119098 --use_finder` pour actualiser `results/summary.json` et valider visuellement que les badges restent corrects dans `index2.html`.
- Étendre le mécanisme `manual_override` si d’autres fiches doivent forcer un branding ou une image spécifique.

## 2025-11-18 – GPT (Codex CLI)

### Faits marquants
- Auchan Talence : ajout de `choose_drive()` dans `fetch_auchan_price.py` (clic automatique sur « Choisir ce drive » + attente 4 s avant recherche). Test validé avec `USE_CDP=1 HEADLESS=0 EAN=8712100731822 QUERY="8712100731822" python3 fetch_auchan_price.py` → prix 2,65 € chez Auchan Talence.
- Comparateur `pipeline/index2.html` : `RESULTS_BASE_CANDIDATES` privilégie désormais `../results` avant `./data/results`, ce qui supprime l’ancien cache statique qui bloquait les montées de version (plus besoin de redémarrer `python3 -m http.server` après chaque collecte).
- Documentation mise à jour (`docs/ONBOARDING.md`, `docs/PRICE_COLLECTION_GUIDE.md`) pour rappeler la procédure Auchan + la nouvelle priorité des JSON côté front.

### Suivi / prochaines étapes
- Si Auchan retombe en `NO_PRICE`, vérifier que le bouton « Choisir ce drive » n’a pas changé (adapter le sélecteur dans `choose_drive()` si besoin) et rejouer la trace `traces/auchan-20251104-talence-orangina.jsonl` avant collecte.
- Pour éviter de retomber sur le snapshot statique, laisser `pipeline/data/results` dormir et ne s’en servir qu’en build offline ; la référence reste `maxicourses_test/results/summary.json`.

## 2025-11-18T19:45 – GPT (Codex CLI)

### Faits marquants
- Leclerc Drive : `manual_leclerc_cdp.py` accepte désormais les substituts lorsque l’EAN est introuvable. Un candidat validé via les tokens seed est marqué `equivalent=true` avec `difference_note` (« EAN introuvable… »), ce qui évite le statut `NO_MATCH` et déclenche le badge « Produit différent » dans `index2.html`.
- Front comparateur : `finalizeRow()` détecte les payloads `equivalent`/`difference_note`, applique automatiquement `row.isMismatch` et affiche la note sous le nom du produit. Les badges « Produit différent » se déclenchent donc même si l’EAN n’a pas été remonté par Leclerc.
- Collecte cible : `USE_CDP=1 HEADLESS=0 python3 pipeline/run_pipeline.py --ean 3092718637033 --headed --adapters leclerc` aboutit à `status="NO_PRICE"` mais `equivalent=true` + `difference_note`. Les fichiers `results/test-3092718637033/{latest,summary}.json` ainsi que `results/summary.json` ont été rafraîchis (badge visible côté front).

### Suivi / prochaines étapes
- Investiguer la non-remontée du prix sur la fiche « Boisson concentrée Teisseire Menthe verte » (nouveau markup prix ?). En attendant, la collecte passe en `NO_PRICE` mais ne bloque plus le pipeline.
- Étendre la même logique d’équivalence aux autres fetchers humains si des EAN continuent de disparaître des PDP.

## 2025-11-19 – GPT (Codex CLI)

### Faits marquants
- Leclerc Drive : `manual_leclerc_cdp.py` pondère désormais les cartes selon les tokens (marque + fonction + parfum) et rejette automatiquement les variantes « sans sucre » si le seed ne les cite pas. Quand aucun EAN n’est disponible, le script prend la fiche au meilleur `token_hits`, extrait prix/quantité et ajoute `equivalent=true` + `difference_note`. Résultat validé sur 3092718637033 : collecte complète `USE_CDP=1 HEADLESS=0 python3 pipeline/run_pipeline.py --ean 3092718637033 --headed`.
- Monoprix : `fetch_monoprix_price.py` démarre toujours la recherche avec deux mots (`<marque> <fonction>`) puis ajoute un troisième mot si nécessaire avant de tester la quantité. Test `USE_CDP=1 HEADLESS=0 EAN=3092718637033 python3 fetch_monoprix_price.py` → fiche « Teisseire Menthe verte 60cl » capturée (prix 3,29 €, image match OK).
- Les fichiers `docs/ONBOARDING.md` et `docs/PRICE_COLLECTION_GUIDE.md` documentent ces procédures afin que les prochains GPT rejouent les mêmes paramètres sans bricoler produit par produit.

### Suivi / prochaines étapes
- Si Leclerc réintroduit la version standard avec EAN visible, vérifier que `manual_leclerc_cdp.py` remonte automatiquement `matched_ean` (aucune action manuelle à faire). En cas de nouvelles variantes sans sucre légitimes, ajouter le flag dans `seed_catalog.py` pour lever le veto.
- Pour Monoprix, consigner dans `seed_catalog.py` toute requête supplémentaire nécessaire (ex. parfum spécifique). Relancer périodiquement `run_pipeline.py --ean <EAN>` pour garder `results/summary.json` et `pipeline/index2.html` alignés.
