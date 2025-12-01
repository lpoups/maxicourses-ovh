# Guide de collecte prix par enseigne

- Chrome remote lancé via `maxicourses_test/start_chrome_debug.sh` (profil `.chrome-debug`), puis toutes les commandes Playwright avec `USE_CDP=1`.
- **Recherche EAN brut obligatoire** : pour tout nouveau produit, taper directement le code EAN (sans texte) sur les enseignes seed qui l’acceptent – Carrefour Market → Carrefour City → Auchan → Chronodrive → Course U (Super U Eysines) → G20 Minute → Casino Shop (Bègles) → Spar Super Saint-Médard. Une fois ces runs effectués, exploiter le descriptif obtenu pour Intermarché, Leclerc puis Monoprix. Aucun descriptif ne doit être utilisé sur les enseignes EAN si l’EAN est connu ; un résultat `NO_PRICE` ou `NO_RESULTS` signifie que le drive ne propose pas ce produit.
- **Mode MàJ prix / URLs seedées** : lorsque `USE_CACHED_URLS=1`, les fetchers compatibles consomment `DIRECT_URL` et `SKIP_SEARCH` (injectés par `/api/update-price`) pour charger directement la PDP (`carrefour_*`, `auchan`, `chronodrive`, `courseu`, `g20`, `casino`, `spar`, `intermarche`, `monoprix`). Leclerc reste en mode humain : même en rapide, il faut rejouer la trace CDP.
- **Mots-clés générés par Finder** : `run_pipeline.py` construit désormais la short-list de requêtes via `FinderPipeline`/`KeywordGenerator`. Les seeds (marque, quantité, requêtes par enseigne) sont codées dans `seed_catalog.py` et exposées via `descriptor_store.py` ; toute mise à jour passe par le code, plus par un JSON. **Interdiction absolue** de créer ou modifier des fichiers `.json` pour piloter les mots-clés : toute tentative doit être migrée vers `finder.py` ou `seed_catalog.py`.
- Chaque sortie JSON doit inclure `price`, `unit_price` (€/kg ou €/L), `quantity`, `store`, `note` (horodatage UTC), `url`, `matched_ean`.
- Conserver les captures dans `maxicourses_test/debug_screens/` ou `maxicourses_test/debug/` et référencer la trace dans `docs/HANDOVER_DAILY.md`.
- Chaque produit possède un visuel local dans `maxicourses_test/pipeline/assets/` référencé par le seed (`seed_catalog.py` → champ `image`). Le comparateur (`pipeline/index2.html`) s’appuie sur l’API `/api/descriptors` du serveur pour exposer ces métadonnées.

## Leclerc Drive (Bruges)
- **Script** : `maxicourses_test/manual_leclerc_cdp.py` (CDP humain). Wrapper CLI : `fetch_leclerc_drive_price.py`.
- **Commandes** :
  ```bash
  cd maxicourses_test
  USE_CDP=1 CDP_URL="http://127.0.0.1:9222" \
    STORE_URL="https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx" \
    EAN=<ean> QUERY="<libellé seed>" \
    LECLERC_HUMAN_DELAY_MS=5000 LECLERC_RESULT_DELAY_MS=12000 LECLERC_PDP_DELAY_MS=7000 \
    python3 manual_leclerc_cdp.py
  ```
- **Logique** : saisie lente, acceptation OneTrust, sélection du meilleur résultat selon les tokens de la requête, extraction JSON-LD.
- **Validation** : le script ouvre jusqu’à 10 cartes du listing ; chaque PDP est rejetée si l’EAN récupéré via « Informations pratiques » diffère du seed. Les variantes « sans sucre », « zero/zéro » sont bannies automatiquement sauf si le seed les mentionne explicitement. Les tokens marque/parfum/fonction issus du seed sont utilisés pour scorer les cartes et la meilleure couverture (« token_hits ») sert de fallback quand aucun EAN n’est remonté.
- **Fallback équivalent** : si l’EAN est absent de la fiche mais que les mots-clés seed correspondent, le fetcher valide désormais le meilleur candidat en `equivalent=true` avec une `difference_note` explicite. `pipeline/index2.html` affiche alors le badge « Produit différent » et la collecte peut se poursuivre au lieu de rester bloquée sur `NO_MATCH`.
- **Requêtes** : générées automatiquement à partir du seed (marque + fonction/nom + quantité) pour garantir un minimum de trois mots ciblés (« Destop Déboucheur 950 ML » par exemple). Les variantes éventuelles (liquide, original…) sont ajoutées en secondaire, mais la requête principale conserve toujours la structure marque/fonction/quantité.
- **Traces** : conserver les traces humaines dans `traces/leclerc-*.jsonl` si la navigation change.
- **Résultats** : JSON par EAN dans `maxicourses_test/results/test-<EAN>/`, agrégat global `maxicourses_test/results/summary.json`.
- **Statut OVH (nov. 2025)** : la navigation vers `fd12-courses.leclercdrive.fr` tombe sur la page DataDome (voir `www/tmp/debug_store.{png,html}`). Tant que l’IP OVH reste bloquée, retirer Leclerc des pipelines (`--adapters … monoprix`) et documenter toute tentative de contournement (proxy résidentiel, tunnel SSH vers un navigateur humain, résolution manuelle du captcha + `save_state_from_cdp.py leclercdrive`).

## Carrefour (City / Market)
- **Scripts** :
  - City : `maxicourses_test/fetch_carrefour_price_city.py`
  - Market : `maxicourses_test/fetch_carrefour_price_market.py`
- **Préparation** : chaque wrapper rejoue automatiquement la trace correspondante (`carrefour-switch-back-20250923.jsonl` pour City, `carrefour-store-switch-20250923.jsonl` pour Market) avant d’appeler `fetch_carrefour_price.py`.
- **Commandes types** :
  ```bash
  cd maxicourses_test
  USE_CDP=1 HEADLESS=0 python3 fetch_carrefour_price_city.py --ean <ean> --query "<libellé>"
  USE_CDP=1 HEADLESS=0 python3 fetch_carrefour_price_market.py --ean <ean> --query "<libellé>"
  ```
- **Sorties** : le JSON indique explicitement le magasin (`store`). Si le libellé retourné n’est pas celui attendu, rejouer la trace puis relancer le script.
- **IDs magasins (cookie `FRONTAL_STORE`)** : City Bordeaux Balguerie = `800041`, Market Fondaudège = `1911`. Les wrappers injectent ces valeurs automatiquement ; vérifier/mettre à jour si un autre drive est utilisé.
- **Statut OVH** : sur le VPS, Carrefour répond désormais `CF_BLOCK` (Cloudflare). Lancer ces fetchs depuis un poste local ou via un proxy résidentiel tant que l’IP serveur reste black-listée, et consigner chaque tentative dans `docs/HANDOVER_DAILY.md`.

## Auchan
- **Script** : `maxicourses_test/fetch_auchan_price.py` (CDP + seed humain `traces/auchan-20240922-clean.jsonl`, nouvelle trace EAN `traces/auchan-20251104-talence-orangina.jsonl`).
- **Commandes** :
  ```bash
  USE_CDP=1 HEADLESS=0 EAN=<ean> QUERY="<libellé seed ou EAN>" python3 fetch_auchan_price.py
  ```
- Sert de seed alternatif lorsque Carrefour n’a pas l’EAN ; taper d’abord l’EAN brut, puis réutiliser le descriptif trouvé pour les autres enseignes.
- **Sélection magasin** :
  - L’URL par défaut **doit** rester `https://www.auchan.fr/magasins/drive/auchan-drive-supermarche-talence-gallieni/s-6117`. Tout autre slug ou chemin (`/drive/magasins/...`) casse le chargement.
  - Lancer `./maxicourses_test/start_chrome_debug.sh` avant la collecte pour garantir la connexion CDP + la persistance du magasin. Sans ce Chrome, Playwright renvoie immédiatement `ECONNREFUSED 9222`.
  - La state `state/auchan.json` contient `storeReference.id = 6117`. Si un autre drive est imposé, mettre à jour cette state via Chrome 9222 puis relancer le fetcher.
-  - Le bouton « Choisir ce drive »/« Afficher le prix » réapparaît régulièrement : enregistrer un parcours humain (`record_generic_navigation.py`) et rejouer `traces/auchan-20251104-talence-orangina.jsonl` jusqu’à ce que le widget prix affiche un montant **avec le symbole €**. Le script dispose désormais d’un hook `choose_drive()` qui clique automatiquement sur « Choisir ce drive » et patiente 4 s avant de saisir l’EAN ; si le prix reste vide, vérifier que ce bouton n’a pas changé de texte.
- **Slug magasin** : utiliser systématiquement `auchan-drive-supermarche-talence-gallieni`. Après chaque navigation, effectuer (ou laisser le script effectuer) les clics « Choisir ce drive » puis « Afficher le prix » si visibles, sinon la page renvoie des faux `NO_PRICE`.
- **Validation prix** : `clean_price()` ignore maintenant toute valeur dépourvue du symbole `€`. Si le prix n’est pas remonté, vérifier la page manuellement, rafraîchir via Chrome CDP et relancer plutôt que de récupérer un faux montant provenant des CSS.

## Intermarché
- **Script** : `maxicourses_test/fetch_intermarche_price.py` (CDP, accepter cookies via script).
- **Commandes** :
  ```bash
  USE_CDP=1 HEADLESS=0 EAN=<ean> QUERY="<libellé adopté>" python3 fetch_intermarche_price.py
  ```
- **Notes** : attendre que le prix apparaisse (commutateur rafraîchissement automatique). Sauvegarder `store` (ex. « Intermarché · Bordeaux Talence (drive) »).
- **Validation** : chaque fiche produit Intermarché expose l’EAN 13 chiffres dans l’URL (`.../produit/<slug>-<EAN>`). Le fetcher extrait systématiquement cet EAN et confirme qu’il correspond à la valeur recherchée avant de retourner un prix ; si l’EAN diffère ou est absent, la fiche est rejetée et le candidat suivant est testé.
- **Sélection magasin** : la state `state/intermarche.json` capture actuellement le drive Hyper Cestas (`store_id_itm = 01047`). Mettre à jour ce fichier via Chrome 9222 si un autre point de vente est requis avant relance.
- **Statut OVH** : l’adaptateur tourne mais renvoie majoritairement `NO_RESULTS` (aucune carte validée). Vérifier manuellement la SERP via Chrome 9222, ajuster les requêtes Finder/`seed_catalog.py` et noter toute observation dans le Handover.

## Monoprix (courses.monoprix.fr)
- **Script** : `maxicourses_test/fetch_monoprix_price.py` (CDP obligatoire, recherche par descriptif uniquement).
- **Commandes** :
  ```bash
  cd maxicourses_test
  USE_CDP=1 HEADLESS=0 QUERY="<libellé seed>" \
    HOME_URL="https://courses.monoprix.fr/" \
    python3 fetch_monoprix_price.py
  ```
- **Logique** :
  - se rendre sur `HOME_URL` (ou `STORE_URL` si un magasin spécifique doit être chargé),
  - accepter les cookies puis saisir la requête issue du seed (des magasins acceptant les recherches EAN carrefour market/city/super, auchan, chronodrive, courseu, g20, casino, spar),
  - ouvrir la fiche la plus pertinente en comparant les descriptifs des magasins seed et extraire prix TTC, prix unitaire, quantité, URL, magasin.
- **Stratégie de recherche** : pour chaque produit, le fetcher construit automatiquement des requêtes minimalistes (`<marque> <fonction>` puis `<marque> <fonction> <parfum>`). Ces requêtes sans quantité sont testées AVANT les requêtes Finder longues ; si la page renvoie trop de résultats ou aucun, un troisième terme est ajouté et, en dernier recours seulement, la quantité est réintroduite. Documenter toute requête inefficace dans `seed_catalog.py` et dans `docs/HANDOVER_DAILY.md`.
- **Résultats** : JSON par EAN dans `maxicourses_test/results/test-<EAN>/`, agrégat global `maxicourses_test/results/summary.json`.
- **Notes** : Monoprix ne supporte pas la recherche EAN il faut donc impérativement faire du matching d'image afin de s'assurer que nous sommes sur le bon produit; si aucun résultat n’est trouvé, documenter et cloturer la collecte.

## Chronodrive
- **Script** : `maxicourses_test/fetch_chronodrive_price.py` (CDP obligatoire).
- **Préparation** : lancer `./start_chrome_debug.sh` (profil `.chrome-debug`). `ensure_store_selected` se charge d’appliquer le drive à partir de `STORE_URL`/`state/chronodrive.json` ; aucun clic manuel n’est requis si l’état est valide.
- **Commande type** :
  ```bash
  cd maxicourses_test
  USE_CDP=1 HEADLESS=0 \
    STORE_URL="https://www.chronodrive.com/magasin/le-haillan-422" \
    QUERY="<libellé seed>" EAN=<ean> \
    python3 fetch_chronodrive_price.py
  ```
  - `HEADLESS=0` recommandé lors des validations initiales pour vérifier la bannière magasin ; ensuite `HEADLESS=1` possible.
  - Le script extrait automatiquement prix TTC, prix unitaire et quantité depuis la fiche associée au drive.
- Si malgré le seed aucune fiche ne correspond, retourner `NO_RESULTS` avec le magasin utilisé et ajouter la trace dans `docs/HANDOVER_DAILY.md`.

## Course U (Super U Eysines)
- **Script** : `maxicourses_test/fetch_courseu_price.py`.
- **Commandes** :
  ```bash
  cd maxicourses_test
  USE_CDP=1 HEADLESS=0 \
    STORE_URL="https://www.coursesu.com/drive-superu-eysines" \
    EAN=<ean> python3 fetch_courseu_price.py
  ```
- **Points de vigilance** :
  - accepter les cookies OneTrust, passer le challenge Cloudflare puis fermer les overlays promotionnels (`div.mask`) avant toute saisie ;
  - recherche EAN brut prioritaire (le script replonge sur `/recherche?q=<EAN>` en fallback) ;
  - choisir la fiche dont l’URL/libellé contient l’EAN ou les tokens seed (attention aux promos Skip/lessives renvoyées par défaut) ;
  - consigner dans `note` l’horodatage UTC + « Super U Eysines ».
  - dès qu’un run aboutit, vérifier que `seed_catalog.py` contient bien `courseu_url`/`courseu_slug` pour l’EAN ; ces champs sont utilisés en priorité pour charger directement la PDP sans repasser par la recherche (diminue fortement les CF).
- **Blocages possibles** :
  - si Cloudflare refuse l’accès, repasser en CDP humain, valider manuellement la recherche puis rejouer `state/courseu.json` ;
  - si le fetcher renvoie `NO_PRICE` avec un `matched_ean` différent (ex. Skip), l’overlay est encore présent dans la state : fermer la modale dans Chrome 9222, sauvegarder immédiatement la state et relancer.
  - Documenter toute manoeuvre et l’EAN concerné dans `docs/HANDOVER_DAILY.md`.
- **Cloudflare** : si la fiche n’apparaît pas (`status="CF_BLOCK"`), lancer `./start_chrome_debug.sh`, ouvrir le drive dans ce Chrome, accepter les cookies/challenges puis exécuter `USE_CDP=1 python3 save_state_from_cdp.py courseu` pour régénérer `state/courseu.json` avant de relancer le fetch. En cas de blocages répétés, repartir d’un profil vierge (renommer `maxicourses_test/.chrome-debug`, relancer Chrome 9222, repasser le challenge) puis resauvegarder la state.

## Casino Shop (Bègles)
- **Script** : `maxicourses_test/fetch_casino_price.py` (HTTP pur, pas de Playwright).
- **Commandes** :
  ```bash
  cd maxicourses_test
  EAN=<ean> QUERY="<requête Finder>" \
    CASINO_STORE_CODE=TZ193 CASINO_STORE_SLUG="casino-shop-33130" \
    python3 fetch_casino_price.py
  ```
- **Logique** :
  - chaque run interroge la page `/recherche/<STORE_CODE>?produit_recherche=<query>` ; les requêtes proviennent du seed Finder (marque + parfum) car la recherche EAN brute renvoie 0 résultat ;
  - le script ouvre ensuite chaque PDP retournée pour lire le JSON-LD (`gtin13`) et ne valide que lorsque l’EAN correspond exactement ;
  - prix TTC et prix unitaire sont extraits du listing HTML, l’unité est ajoutée telle qu’affichée (€/kg ou €/L) et le magasin est fixé à `Casino Shop · Bègles Pruniers`.
- **Paramétrage** : `CASINO_STORE_CODE`, `CASINO_STORE_SLUG` et `CASINO_STORE_URL` peuvent être forcés via l’environnement si un autre magasin doit être couvert ; par défaut on cible `https://www.mescoursesdeproximite.com/courses-en-ligne/casino-shop-33130/TZ193`.

## Spar Super Saint-Médard-en-Jalles
- **Script** : identique (`maxicourses_test/fetch_casino_price.py`) mais avec `CASINO_STORE_CODE=TL832`, `CASINO_STORE_SLUG="spar-33160"`, `CASINO_STORE_URL="https://www.mescoursesdeproximite.com/courses-en-ligne/spar-33160/TL832"`, `CASINO_STORE_LABEL="Spar Super · Saint-Médard-en-Jalles"`.
- **Principe** : mêmes requêtes Finder que Casino (texte uniquement). Le script parcourt la SERP, ouvre les PDP et valide le `gtin13`. Les prix pack/unitaires sont ceux du listing Spar.
- **Astuce** : si la SERP renvoie des promos ou des lots, ajuster `seed_catalog.py` (`queries['spar']`) pour privilégier marque + volume (ex. `coca cola 1,75l`). Toute mise à jour doit être documentée dans le handover.

## Gestion des résultats & comparateur
- Chaque EAN dispose de `results/test-<EAN>/latest.json` et `summary.json`. L’agrégat global `results/summary.json` alimente `pipeline/index2.html`.
- `pipeline/index2.html` charge désormais `../results/summary.json` (sorties live) avant de retomber sur `pipeline/data/results/summary.json` (snapshot). Ne jamais copier les JSON vers `pipeline/data` pour « débloquer » l’UI : mettre à jour `maxicourses_test/results/*` puis rafraîchir la page suffit.
- Ajouter un produit dans le comparateur :
  1. Générer ou mettre à jour les JSON `results/test-<EAN>/`.
  2. Compléter l’entrée correspondante dans `seed_catalog.py` (titre, quantité, image locale, Nutri-score si dispo).
  3. Ajouter l’EAN dans `EXTRA_DATASETS` de `pipeline/index2.html`.
  4. Vérifier la page via `cd maxicourses_test && python3 -m http.server`.

## Requêtes générées par l’IA (Leclerc / Monoprix / Intermarché)
- Après une collecte seed réussie (Carrefour Market/City, Auchan, Chronodrive), lancer `USE_AI_ASSIST=true ./run_ai_pipeline.sh <EAN>` pour que `run_pipeline.py` envoie les payloads à OpenAI.
- `summarize_product_seed` produit un profil canonique (`ai_profile`, `ai_keywords`), puis `suggest_search_queries(store=...)` fabrique des requêtes ≤30 caractères (« marque + produit [+ contenance] ») pour Leclerc, Monoprix et Intermarché.
- Les requêtes texte validées sont stockées dans `seed_catalog.py` (`queries` et `leclerc_queries`) et utilisées automatiquement lors des prochains fetchs via `descriptor_store`.
- Les journaux IA (prompts + réponses) sont archivés dans `maxicourses_test/logs/refonte_v2/runs/<horodatage>-<EAN>-<PID>/`.

### Clés de recherche (IA)
- `primary_keywords` = requête envoyée au moteur (marque → quantité/format → type → variante). Exemple croquettes : `ULTIMA 1.5kg chat croquettes`; lessive : `ARIEL 21 capsules lessive`; condiments : `Amora 385g moutarde`.
- `secondary_keywords` = mots qui doivent apparaître sur la carte retenue (stérilisé, aromates, grandiose…). Le fetcher rejette toute carte qui ne les contient pas tous.
- Termes interdits dans les primaires : `stérilisé`, `adulte`, `promo`, `lot`, `pack`, `xN`, etc. Ils restent autorisés en secondaires pour filtrer.
- Toute fiche seed avec `matched_ean` vide ou différent est ignorée et consignée dans `docs/SEED_RULES.md` (« Faire ceci = erreur »).
- Avant chaque run, relire `docs/SEED_RULES.md` pour appliquer la bonne méthode (contenu déjà validé, mots à bannir, variantes attendues).

## Suivi urgent (OVH, nov. 2025)
- **Leclerc Drive** : DataDome bloque l’IP. Mettre en place un proxy résidentiel ou une session humaine (VNC) pour passer le captcha, enregistrer l’état et relancer `manual_leclerc_cdp.py`.
- **Carrefour City/Market/Super** : Cloudflare renvoie `CF_BLOCK`. Collecter ces enseignes depuis un poste local le temps d’obtenir une IP approuvée.
- **Intermarché** : enquête à poursuivre (les requêtes IA produisent `NO_RESULTS`). Vérifier les SERP dans Chrome 9222, ajuster `seed_catalog`/`finder` et documenter toutes les pistes.
- **Pipeline VPS** : toujours activer le venv (`. .venv/bin/activate`), s’assurer que `zxing-cpp` est installé et que Chrome 9222 tourne (`nohup xvfb-run ...`). Copier systématiquement les JSON depuis le VPS vers le FTP (`www/maxicourses-prod/maxicourses_test/results/`) pour alimenter `index2.html`.

## Documentation à lire impérativement
1. `docs/PROMPT_BOOTSTRAP.md` – check-list initiale et ton attendu.
2. `docs/ONBOARDING.md` – règles générales et scripts critiques.
3. `docs/LECLERC_HUMAN_METHOD.md` – workflow détaillé pour Leclerc Drive.
4. `docs/PARCOURS_HUMAIN.md` – enregistrement/rejeu des traces anti-bot.
5. `docs/HANDOVER_DAILY.md` – état des travaux (dernière entrée).
6. Ce guide (`docs/PRICE_COLLECTION_GUIDE.md`) pour connaître la méthode par enseigne.

## Traces & captures utiles
- `traces/auchan-20240922-clean.jsonl` – navigation Auchan seed (ancienne version).
- `traces/auchan-20251104-talence-orangina.jsonl` – sélection Talence Gallieni avec recherche EAN et clic « Afficher le prix ».
- `traces/leclerc-20250924-*.jsonl` – sélection drive Bruges.
- `traces/carrefour-switch-back-20250923.jsonl` puis `traces/carrefour-store-switch-20250923.jsonl` – séquence obligatoire avant toute collecte Carrefour (City puis Market).
- Captures debug dans `maxicourses_test/debug/` (HTML) et `maxicourses_test/debug_screens/` (PNG).

## Rappels finaux
- Toujours consigner un résumé de session dans `docs/HANDOVER_DAILY.md` (format `## YYYY-MM-DD - GPT`).
- Attacher les preuves (commandes, captures, JSON) aux entrées correspondantes.
- Aucun prix ne doit être saisi manuellement : tout provient des scripts Playwright/CDP.

## Enrichissement Open Food Facts
- Source autorisée : https://fr.openfoodfacts.org (version française).
- Utiliser l’EAN pour récupérer Nutri-score, Eco-score/Green-score, labels (bio, vegan, niveau de transformation) et descriptions détaillées.
- Ne jamais remplacer les visuels : les images restent issues des enseignes comparées (Carrefour, Auchan, etc.).
- Documenter dans les résultats JSON l’origine des données (`source":"openfoodfacts"`) quand elles sont utilisées.
