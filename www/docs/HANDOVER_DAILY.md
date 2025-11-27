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

## 2025-11-21 – GPT (Codex CLI)

### Faits marquants
- Les collectes déclenchées via `index2.html` étaient stoppées à 480 s par le watchdog de `server.py`, ce qui effaçait `results/test-<EAN>/` avant d’avoir un nouveau JSON. Ajout d’un paramètre `PIPELINE_TIMEOUT_SECONDS` (par défaut 900 s) pour laisser `run_pipeline.py` terminer l’enchaînement des 12 adaptateurs.
- Pour éviter toute page blanche en cas d’échec, `api/collect` ne purge plus le dossier `results/test-<EAN>` ni l’entrée `summary.json` tant que le run n’est pas annoncé `OK`. Les anciennes données restent donc visibles dans `index2.html` jusqu’à ce qu’une collecte réussisse.
- Validation : `curl -sS -X POST http://127.0.0.1:5001/api/collect -H 'Content-Type: application/json' -d '{"ean":"3665468000312"}'` → run complet en ~8 min 33 s, fichiers mis à jour : `results/test-3665468000312/run-3665468000312-20251121-184030.json`, `latest.json`, `summary.json` + entrée globale `results/summary.json` (Casino/Spar OK).
- Après toute modification de `server.py`, redémarrer immédiatement : `pkill -f "maxicourses_test/server.py"` puis `USE_CDP=1 python3 maxicourses_test/server.py >/tmp/maxi_server.log 2>&1 &` et noter ce reboot dans le handover.

### Points ouverts
- Surveiller la durée réelle des adaptateurs Intermarché/Leclerc : si l’un dépasse plusieurs minutes, préparer une stratégie de parallélisation ou relever `PIPELINE_TIMEOUT_SECONDS`.
- Rejouer `curl /api/collect` pour les EAN critiques (Orangina, Coca, Savora, Destop…) après toute modification fetcher afin de garantir que `results/summary.json` reste cohérent avec l’UI.

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

## 2025-11-20 – GPT (Codex CLI)

### Correctifs
- `pipeline/index2.html` détecte désormais automatiquement si l’API locale (`server.py`) n’est pas lancée. Un bandeau d’alerte s’affiche dès le chargement quand l’`OPTIONS` sur `/api/collect` échoue, avec l’instruction explicite : `cd maxicourses_test && USE_CDP=1 python3 server.py`.
- Mise à jour du CORS (`GET` autorisé) afin de permettre ce ping automatique et toute future consultation.
- L’alerte est masquée dès que le serveur répond : relancez simplement `server.py` puis rafraîchissez la page.

### Suivi
- Garder cette vérification lors des prochains refactors front (V2) afin d’éviter toute nouvelle séance de debug « page vide » lorsque l’API locale est arrêtée.

## 2025-11-21 – GPT (Codex CLI)

### Problèmes résolus
- **Bannière « serveur injoignable »** : le front cache désormais le bandeau par défaut, ne l’affiche qu’en cas d’erreur réseau réelle et, côté Safari, un `hidden` force `display:none`. La redirection automatique HTTPS → HTTP n’est appliquée qu’en local (`localhost`/`127.0.0.1`), ce qui évite les rafraîchissements infinis sur l’instance OVH encore en HTTPS.
- **Auchan Talence** : `fetch_auchan_price.py` clic désormais sur toutes les variantes de boutons (« Choisir ce drive », « Choisir ce magasin », « Afficher le prix ») et resynchronise le contexte magasin après chaque clic. Test concluants (`EAN=5000112611861`) → prix 2,38 € Talence récupéré systématiquement.
- **Leclerc keywords** : `run_pipeline.py` construit les requêtes strictement à partir du seed (marque + variante + quantité + EAN). Les requêtes IA ne peuvent plus générer de termes génériques, ce qui évite les « Jean’s Cola » et force l’adaptateur Leclerc à coller au produit seed. Collecte complète confirmée sur `5000112611861`.

### À surveiller / restant à faire
- **Instance OVH** : `server.py` n’est pas encore lancé côté VPS, donc l’UI prod reste en lecture seule. Dès que le backend sera actif, vérifier que l’alerte reste silencieuse et qu’aucune redirection ne se déclenche.
- **Nouvelle enseigne Casino Bègles** : préciser la méthode de collecte pour `https://www.mescoursesdeproximite.com/` (magasin CASINO SHOPPING · Allée des Pruniers, Bègles). Le logo `maxicourses_test/assets/logos/casino.png` est prêt ; reste à script-er le fetcher + l’intégration pipeline/index2.html.
- **Priorité carburants** : lancer une passe sur la récupération automatique des prix carburants pour toutes les enseignes qui distribuent du fuel (ou pour les stations proches des magasins déjà suivis) afin d’enrichir le comparateur.
  - API publique : `https://donnees.roulez-eco.fr/opendata/instantane` (ZIP → XML complet, rafraîchi toutes les ~10 min).
  - Formats alternatifs (portail Opendatasoft/data.gouv.fr) : JSON, CSV, GeoJSON.
  - Carburants couverts : Gazole (B7), SP95 (E5), SP98 (E5), SP95-E10 (E10), GPLc, E85.

## 2025-11-21T14:25 – GPT (Codex CLI)

### Faits marquants
- Nouvelle collecte **Casino Shop Bègles** : ajout du fetcher HTTP `maxicourses_test/fetch_casino_price.py`. Le script interroge la page `/recherche/TZ193?produit_recherche=<query>`, parcourt les cartes et valide uniquement les PDP dont le JSON-LD (`gtin13`) correspond à l’EAN. Prix TTC et €/L/€/kg sont repris du listing ; le magasin est figé sur « Casino Shop · Bègles Pruniers ».
- Intégration pipeline/UI : `run_pipeline.py` connaît l’adaptateur `casino` (ordre par défaut après `g20`), `index2.html` expose le logo `assets/logos/casino.png`, une entrée `DISPLAY_NAMES` dédiée et le point GPS (lat 44.814814, lon -0.550976) pour la carte. Les docs `ENSEIGNES`, `PRICE_COLLECTION_GUIDE`, `ONBOARDING`, `PRICE_COMPARATOR_PLAN` et `HANDOVER` décrivent la procédure.
- Test rapide : `cd maxicourses_test && python3 pipeline/run_pipeline.py --ean 5449000131836 --adapters casino` — renvoie `NO_RESULTS` sur la requête EAN brute (normal), les requêtes Finder courtes (`coca cola sans sucre 50cl`, etc.) retournent bien `status="OK"` avec `matched_ean=5449000131836`.

### Suites / TODO
1. Alimenter `finder.py` / `seed_catalog.py` avec des requêtes ciblées pour Casino et Spar dès qu’un nouveau produit est ajouté (marque + parfum + format) afin que le pipeline ne retombe plus sur le fallback EAN vide.
2. Étendre la surveillance `_meta` (`supports_keywords=true`) pour suivre les requêtes testées et documenter toute anomalie dans ce journal.
3. Ajouter de vraies collectes Casino/Spar dans `results/test-<EAN>/` puis rafraîchir `results/summary.json` pour valider le rendu `index2.html` (logos/cartes).

## 2025-11-21T16:00 – GPT (Codex CLI)

### Faits marquants
- Intégration **Spar Super Saint-Médard-en-Jalles** (mescoursesdeproximite.com) : nouvel adaptateur `spar` dans `run_pipeline.py` réutilisant `fetch_casino_price.py` mais avec le store code `TL832`. `index2.html` embarque le logo `assets/logos/spar.png`, un label dédié et la géolocalisation (lat 44.894404, lon -0.715413).
- `seed_catalog.py` fournit désormais les requêtes Finder `casino` + `spar` pour tous les EAN pilotes (Coca 1,75 L, Destop, Hipro, Lune de Miel, Alpro, Orangina, Savora), ce qui évite les recherches EAN qui renvoient 0 résultat sur mescoursesdeproximite.com.
- Documentation mise à jour (`ONBOARDING`, `PRICE_COLLECTION_GUIDE`, `PRICE_COMPARATOR_PLAN`, `pipeline/ENSEIGNES.md`) pour préciser la procédure Spar et rappeler que les deux enseignes partagent le même fetcher HTTP.

### Suivi
- Lors des prochaines collectes globales, vérifier que `run_pipeline.py` enchaîne bien `... g20 -> casino -> spar ...` et que `results/summary.json` remonte les deux magasins. Si Spar tombe en `NO_RESULTS`, ajuster les requêtes `queries['spar']` dans `seed_catalog.py`.

## 2025-11-26 – GPT (Codex CLI)

### Faits marquants
- Commit global `chore: snapshot py html json` (561 fichiers) incluant tous les `.py/.html/.json` modifiés, résultat/runs et captures debug. `ai_helpers.toml` non touché.
- Leclerc : `manual_leclerc_cdp.py` en matching strict EAN (plus de token_equivalent), timeouts navigation réduits, `LECLERC_MAX_PDP` porté à 12. Collecte validée sur `5411188118961` → fiche amande avec EAN exact.
- Intermarché : pauses réduites (timeouts 1200 ms au lieu de 5000) et run ok sur `5411188118961` (prix 1,95 €, EAN exact).

### Points d’attention
- Le commit inclut de très nombreux JSON/logs/caches Chrome (profil carrefour_city). Prévoir un nettoyage `.gitignore` ciblé si besoin de réduire le dépôt.
- Finder/post-traitement : warning récurrent (`FinderPipeline` sans `decide`) toujours présent dans les logs Leclerc. A traiter pour stabiliser l’éval post-collecte.
