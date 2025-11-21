# Maxicourses Assistant Onboarding

imperatif de corriger le probleme de collecte global les mises à jour de collecte ne s'affichent pas dans index2.html

## Rôle et hiérarchie
- Laurent donne les ordres et l’assistant obéit strictement : **le user commande, l’assistant exécute**. Toujours suivre ses instructions sans discuter.
- Aucun switch manuel n’est toléré : tous les drapeaux (`USE_AI_ASSIST`, etc.) doivent être activés automatiquement dans les scripts pour supporter 300 000 collectes/jour sans intervention humaine.

Il est interdit de faire des reponses de plus de 5 phrases! 

# Le principe de la methode pour trouver les bons produits sur les magasin n'ayant pas de recherche EAN ou comme chez intermarche la possibilité de valider le produit avec la presence du code EAN dans le lien href de la page produit? on recupere des mots cles à partir des descriptifs des produits des magasins seed permettant les recherche directe EAN ce qui permet d'avoir des mots cles de recherche pour arriver sur une liste de produit sur les magasins non EAN ensuite il y a 3 methodes! la première intermarché on clic sur les fiche produit et on valide le bon produit quand on voit le code EAN dans le lien href de la fiche produit 2 ieme methode Leclerc on clic sur les fiches produits et on valide avec le code EAN present dans le lien "informations produit" de la page du produit si on ne trouve pas le code EAN car il n'est pas present à 100% on valide le produit en comparant l'images SEED avec l'image produit leclerc! 3ieme méthode Monoprix on clic sur les fiches produits et on valide en comparant l'image seed avec l'image de la fiche produit Monoprix! est ce que tout ceci est bien compris?
On part toujours des enseignes seed capables de chercher par EAN pour définir des mots-clés fiables.
Avec ces mots-clés, on ouvre les listings des enseignes sans recherche EAN.
Intermarché : on valide uniquement quand l’URL produit contient l’EAN attendu.
Leclerc : on ouvre la fiche, on cherche l’EAN dans « informations produit » et, s’il manque, on compare l’image seed à l’image Leclerc pour confirmer.
Monoprix : validation exclusivement par matching visuel avec l’image seed.
as tu compris le principe de la methode pour trouver les bons produits sur les magasin n'ayant pas de recherche EAN ou comme chez intermarche la possibilité de valider le produit avec la presence du code EAN dans le lien href de la page produit? on recupere des mots cles à partir des descriptifs des produits des magasins seed permettant les recherche directe EAN ce qui permet d'avoir des mots cles de recherche pour arriver sur une liste de produit sur les magasins non EAN ensuite il y a 3 methodes! la première intermarché on clic sur les fiche produit et on valide le bon produit quand on voit le code EAN dans le lien href de la fiche produit 2 ieme methode Leclerc on clic sur les fiches produits et on valide avec le code EAN present dans le lien "informations produit" de la page du produit si on ne trouve pas le code EAN car il n'est pas present à 100% on valide le produit en comparant l'images SEED avec l'image produit leclerc! 3ieme méthode Monoprix on clic sur les fiches produits et on valide en comparant l'image seed avec l'image de la fiche produit Monoprix! est ce que tout ceci est bien compris?

## Mission Snapshot
- Maintenir et enrichir les scripts de relevé de prix (Carrefour, Leclerc Drive, etc.)
- Assurer une traçabilité claire des relevés (Chrome remote, captures si besoin) pour préparer le comparateur de prix intelligent.
- Capitaliser l'historique (décisions, obstacles, artefacts) afin que tout nouvel assistant reprenne le travail sans perte d'information.
- Migration OVH en standby tant que l’instance locale n’est pas parfaitement stabilisée et sanctuarisée : priorité absolue au bon fonctionnement local.
- **2025-11-19 – Déploiement OVH** : un VPS Ubuntu 22.04 est prêt (`ubuntu@91.134.133.156` / mot de passe en Handover). Le repo `maxicourses-prod` + venv + Chrome headless sont installés. Les collectes doivent désormais s’exécuter sur ce VPS (Chrome 9222 via `xvfb-run`). Voir `docs/OVH_SERVER_SETUP.md` pour toutes les commandes. Toujours rapatrier les JSON depuis `~/maxicourses-prod/maxicourses_test/results/` avant de pousser vers `www/maxicourses-prod/…` sur le FTP.
- **Blocages actuels** :
  - `Leclerc Drive` : DataDome bloque l’IP OVH (voir captures `www/tmp/debug_store.{png,html}`). Tant qu’une solution proxy/tunnel n’est pas mise en place, désactiver Leclerc dans les commandes (`--adapters … monoprix`).
  - `Carrefour City/Market/Super` : la même IP est désormais classée `CF_BLOCK`. Les scripts retournent `{"status":"CF_BLOCK"}`. Prévoir un fallback (proxy ou récupération manuelle via un navigateur humain).
  - `Intermarché` : les adaptateurs tournent mais renvoient `NO_RESULTS` (les requêtes IA semblent rejetées, à investiguer).
- **Procédure de collecte (sans Leclerc)** :
  1. SSH sur le VPS, démarrer Chrome si besoin (`nohup xvfb-run … google-chrome-stable --remote-debugging-port=9222 …`).
 2. Pour chaque EAN : `./maxicourses_test/run_pipeline_server.sh <EAN> --adapters carrefour_city carrefour_market carrefour_super auchan chronodrive courseu g20 casino intermarche monoprix`.
  3. Récupérer `summary.json` + `test-<EAN>` via SCP, mettre à jour le dépôt local puis uploader vers `/www/maxicourses-prod/maxicourses_test/results/`.
  4. Rafraîchir `index2.html` (il lit directement `results/summary.json` sur le FTP).
- Noter toutes les anomalies (CF_BLOCK, DataDome, erreurs Intermarché) dans `docs/HANDOVER_DAILY.md` avec horodatage + captures.

## Incidents critiques (2025-11-18)
- **Auchan Talence** : `fetch_auchan_price.py` déclenche maintenant `choose_drive()` avant chaque recherche. Le script clique sur « Choisir ce drive », attend 4 s pour que Talence Gallieni soit fixé, puis ouvre la fiche et force l’affichage du prix. Si le bouton réapparaît, rejouer la trace `traces/auchan-20251104-talence-orangina.jsonl`, relancer Chrome 9222 et contrôler les logs `[auchan] goto store page … / results visible` avant de relancer la collecte.
- **Comparateur index2** : la page charge en priorité `../results/summary.json` (données live) et ne s’appuie sur `pipeline/data/results` qu’en secours. Si les prix semblent figés, vérifier que ce répertoire `../results` contient bien les JSON récents et ne pas copier manuellement le snapshot statique : recharger la page suffit dès que `results/summary.json` est mis à jour.
- **Leclerc fallback** : lorsque la fiche PDP n’affiche plus l’EAN (cas 3092718637033), `manual_leclerc_cdp.py` bascule automatiquement sur le candidat le plus proche, marque la collecte en `equivalent=true` + `difference_note` et l’UI `index2.html` affiche « Produit différent ». Le pipeline ne reste plus bloqué sur `NO_MATCH` et passe à l’enseigne suivante.
- **Leclerc tokens (2025-11-19)** : la sélection Leclerc s’appuie désormais sur les tokens seed (marque + parfum + fonction) : rejet automatique des « sans sucre » quand le seed ne les mentionne pas, scoring renforcé sur ces tokens, fallback sur la fiche avec le meilleur « token_hits » et matching image systématique. En cas d’EAN absent, le script marque `equivalent=true` mais fournit prix/quantité.
- **Monoprix requêtes courtes (2025-11-19)** : `fetch_monoprix_price.py` commence toujours par deux requêtes minimalistes (marque + fonction, puis + parfum). Si aucun résultat n’apparaît, une troisième requête ajoute un mot et la quantité n’est testée qu’en dernier recours. Documenter tout blocage dans `docs/HANDOVER_DAILY.md`.

## Redémarrage des services locaux
- **Chrome debug (port 9222)** : indispensable pour tous les fetchers CDP. Lancer `cd maxicourses_test && ./start_chrome_debug.sh` (laisse la fenêtre Chrome ouverte). Si le profil est corrompu, supprimer `maxicourses_test/.chrome-debug` puis relancer.
- **API collecte (`server.py`)** : toujours relancer après une modification ou un crash via `cd maxicourses_test && USE_CDP=1 python3 server.py`. Surveille la console et garde la fenêtre ouverte afin de voir les logs Playwright.
- **Prévisualisation comparateur** : `cd maxicourses_test && python3 -m http.server 8000` . Redémarre ce serveur statique à chaque fois que tu modifies les assets HTML/JSON.

## Garde-fous immédiats
- **Gel fetchers existants** : ne toucher sous aucun prétexte aux scripts `fetch_carrefour_price_market.py`, `fetch_carrefour_price_city.py`, `fetch_auchan_price.py`, `fetch_chronodrive_price.py`, `fetch_courseu_price.py`, `fetch_casino_price.py`, `fetch_intermarche_price.py`, `fetch_leclerc_drive_price.py`, `fetch_monoprix_price.py` (ni à leurs helpers) tant que Laurent n’a pas validé une modification explicite. Seul le wrapper `fetch_carrefour_price_super.py` peut évoluer sans validation préalable (objectif : sécuriser la collecte Carrefour Super Lormont).

- Les requêtes humaines doivent etre tapé avec des espaces (`"coca cola 1,75 l"`) ; bannir les `+` quels que soient les magasins (le fait d'ajouter de "+" force des mots clés et augment la quantité de resultats sur certain magasins).

Nous utilison `finder.py` et plus du tout de fichier .json pour definir les mots cles de recherche et les mots cles de descriptif pour pre-validations de fiche avant matching image!

⚠️ **RAPPEL ABSOLU** : aucun mot-clé ne doit être maintenu dans des fichiers `.json`. Toute génération/édition passe exclusivement par `finder.py` et la logique Python associée. Toute réintroduction de `.json` pour les mots-clés est strictement interdite.


//
- **URGENT PRIORITE : Auchan Talence (2025-11-05)** : 
Recommencer l'intégralité de la collect AUCHAN car tout a été saccagé par le précendent GPT! il faut repartir de zero! AUCHAN accept la recherche directe via EAN! eventuellement rechercher la sauvegarde de fetch_auchan_price.py datant de avant le 01/11/2025. **Procédure à appliquer pour éviter toute régression slug/prix :**
  1. Vérifier que `fetch_auchan_price.py` pointe sur le slug `auchan-drive-supermarche-talence-gallieni` et sur l’URL complète `https://www.auchan.fr/magasins/drive/auchan-drive-supermarche-talence-gallieni/s-6117`. Bannir définitivement l’ancien chemin `/drive/magasins/...` qui renvoie « Cannot GET ».
  2. Lancer Chrome CDP avec `./maxicourses_test/start_chrome_debug.sh` avant de démarrer le fetcher. Sans ce profil la connexion 9222 échoue et le magasin n’est pas mémorisé.
  3. Toute collecte Auchan doit commencer par `EAN=<ean> python3 maxicourses_test/fetch_auchan_price.py` (HEADLESS=0 en validation) et cliquer sur « Choisir ce drive » / « Afficher le prix ». Si ces boutons reviennent, rejouer la trace `traces/auchan-20251104-talence-orangina.jsonl` et resauvegarder `state/auchan.json`.
  4. Si la page ne contient aucun symbole `€`, c’est que le widget prix n’a pas chargé : refaire l’ouverture depuis Chrome humain puis relancer le fetcher (ne **jamais** retomber sur les falses positives `Roboto:300,40`).
  5. Dès qu’un prix Auchan est OK, relancer `python3 maxicourses_test/pipeline/run_pipeline.py --ean <ean>` pour consigner `results/test-<ean>/` et vérifier l’entrée dans `results/summary.json`.

- **Journal 2025-11-06 — Actions récentes**
  - `fetch_auchan_price.py` normalise désormais la quantité collectée : on extrait toutes les mesures (g/ml) et on garde la valeur majoritaire pour éviter les faux `5 L`.
  - `maxicourses_test/decode_ean.py` possède un double fallback :
    - OCR local (pytesseract) si ZXing n’arrive pas à lire les barres ;
    - Appel optionnel à l’API OpenAI (`gpt-4o-mini`) pour lire les chiffres imprimés (clé recherchée dans `OPENAI_API_KEY` ou `docs/API_KEY.md`).
  - `start_chrome_debug.sh` ajoute `--remote-allow-origins=*` pour garantir la compatibilité Playwright ↔ Chrome 142.

- **À poursuivre**

  - Valider en conditions réelles la lecture via OpenAI : certains prompts retournent encore « je ne peux pas aider », il faudra éventuellement ajuster le wording ou le modèle.
  - Relancer une collecte globale complète pour s’assurer que les nouvelles quantités Auchan et la colonne « collecte précédente » côté front sont conformes.

- **Correctif Chronodrive déployé (2025-10-30 soir)** : `fetch_chronodrive_price.py` contourne désormais l’overlay capricieux en interrogeant l’API suggestions (`/v1/search-suggestions`) puis l’API produit (`/v1/products/{id}`) avec les en-têtes `x-chronodrive-site-id=1006`. On sélectionne le meilleur candidat via l’EAN + tokens, on résout la `canonicalUrl` et on ouvre la PDP Playwright (<2 s). Les anciens fallback UI restent présents mais ne devraient plus se déclencher.
- **Nouveau scope Carrefour Super Lormont (2025-10-31)** : le wrapper `fetch_carrefour_price_super.py` reproduit la stratégie City/Market avec `STORE_QUERY="Super Lormont"`. Le pipeline connaît désormais l’adaptateur `carrefour_super` (logo Carrefour + label « Super ») et le point GPS (lat 44.867007, lon -0.516348). Seed en EAN brut obligatoire, aucune régression tolérée sur City/Market.
- **À faire Carrefour Super** : l’état CDP actuel (`state/carrefour_super.json`) contient encore `FRONTAL_STORE=116` (Market Fondaudège). Il faut **rejouer un parcours humain** (ouvrir Chrome 9222, clic « Drive » → « Changer de drive » → rechercher « Lormont ») et sélectionner la fiche **« Lormont, Gironde, France »** (le site n’affiche pas « Lormont Super »). Enregistrer la trace/ID comme pour City/Market et relever `displayableUrlId`, `facilityServiceId`, `FRONTAL_STORE` avant de relancer des collectes.
- **À faire** : propager ces règles à d’autres seeds (vérifier desserts végétaux), archiver les captures Monoprix/Leclerc dans `results/debug/` et mettre à jour la page comparateur (rafraîchir `results/test-3124480200433/latest.json` déjà régénéré, contrôler le rendu web).
- **Mise à jour Monoprix (2025-11-02)** :
  - `_descriptor_validation_tokens` inclut le profil canonique pour imposer ≥ 70 % de couverture des tokens (marque, forme, quantité) ; les tokens purement numériques sont neutralisés.
  - `_descriptor_remote_images` remonte les visuels `canonical.images` / `reference_image(s)` ; l’asset seed `3088545004001` est désormais la bouteille « squeeze » (Carrefour).
  - `_collect_monoprix_negatives` respecte le flag `allow_monoprix_squeeze` défini dans `seed_catalog.py` pour éviter les faux veto.
  - Tests `tests/test_monoprix_validation.py` vérifient la couverture et l’agrégation d’images. Run de contrôle : `USE_CDP=1 HEADLESS=0 EAN=3088545004001` → fiche « Lune de Miel Squeeze Miel de Fleur 500g » validée.
//

## Règles Incontournables
1. **Collecte seed systématique** : commencer chaque produit par une recherche **100 % EAN brut** (sans texte additionnel) sur les enseignes qui l’acceptent :
   - Carrefour Market d’abord, puis Carrefour City (via les wrappers CDP),
   - ensuite Auchan,
   - puis Chronodrive,
   - Course U (Super U Eysines),
   - G20 Minute (recherche EAN possible, mais conserver le descriptif seed pour les tokens),
   - Casino Shop (Bègles) une fois les requêtes Finder définies.
  Une fois ce descriptif fiable (titre, quantité) récupéré, l’intégrer dans `seed_catalog.py` et l’utiliser pour enchaîner Intermarché, Leclerc puis Monoprix (qui ne prennent pas l’EAN brut).
2. **Leclerc Drive** : toute interaction passe par Chrome remote (port 9222) + validation visuelle. `USE_CDP=1`, `HEADLESS=0`. Aucun scraping headless ni requête directe.
3. **Carrefour** : privilégier Chrome remote pour contourner Cloudflare. Toujours sauvegarder au besoin les captures (`HUMAN_DEBUG_DIR`).
4. **Images seed** : l’image de référence doit être issue de Carrefour en priorité ; si absente, choisir une autre enseigne seed acceptant l’EAN (Auchan, Chronodrive, Course U). Mettre à jour l’asset local et `seed_catalog.py` avant tout matching (Monoprix/Leclerc/Intermarché) pour éviter les validations sur de mauvais visuels.
6. **Validation commits** : toujours demander l’accord explicite de l’utilisateur avant tout `git commit` (ou action équivalente).
7. **Documentation vivante** : mettre à jour les fichiers de handover pour tout changement significatif.
8. **Requêtes IA** : après chaque seed réussi, lancer `USE_AI_ASSIST=true ./run_ai_pipeline.sh <EAN>` pour générer (OpenAI) des requêtes ≤30 caractères destinées aux enseignes textuelles (Leclerc/Monoprix/Intermarché). Reporter les requêtes validées dans `seed_catalog.py`.
9. **Intermarché** : recherche textuelle uniquement et validation stricte via l’EAN embarqué dans l’URL (`…/produit/<slug>-<EAN>`). Toute fiche dont l’URL ne contient pas l’EAN attendu est rejetée automatiquement par le fetcher.
10. **Leclerc** : toutes les requêtes générées automatiquement respectent la forme « marque + fonction/nom + quantité » (au moins trois mots) afin d’éviter les recherches trop larges.
11. **Monoprix** : les requêtes sont limitées à **deux** mots-clefs : d’abord la marque, ensuite la fonction ou un terme issu du seed (ex. `Destop Déboucheur`). Toute suggestion automatique est normalisée en ce sens.
12. **Course U** : en cas de blocage Cloudflare (`status="CF_BLOCK"` ou `NO_PRICE` avec un autre EAN), ouvrir le drive Super U Eysines via Chrome remote, accepter les challenges, fermer l’overlay marketing qui masque la barre de recherche, puis régénérer `state/courseu.json` (`USE_CDP=1 python3 save_state_from_cdp.py courseu`) avant de relancer la collecte.
    - Si l’overlay n’est pas fermé, le fetcher bascule sur une page promo (ex. lessive Skip) : on obtient `status="NO_PRICE"` et un `matched_ean` incorrect. Toujours valider la recherche manuelle (EAN Destop → fiche Destop) juste avant de sauvegarder la state.
    - Dès qu’un fetch Course U aboutit, le script mémorise automatiquement l’URL de la fiche (`courseu_url` / `courseu_slug` dans `seed_catalog.py`) et réutilise cette PDP lors des runs suivants pour éviter Cloudflare. Vérifier que cette URL reste valable et ne pas la supprimer.
    - Si Cloudflare revient malgré tout après plusieurs collects, repartir d’un profil vierge : fermer Chrome 9222, sauvegarder/renommer `maxicourses_test/.chrome-debug`, relancer `./start_chrome_debug.sh`, repasser le challenge puis resauvegarder `state/courseu.json`.
13. **Gel de maintenance des fetchers** : ne toucher **en aucun cas** aux scripts Carrefour City/Market/Super (`fetch_carrefour_price*.py`), Auchan, Chronodrive, Course U, Intermarché, Leclerc Drive ou Monoprix (et à leurs wrappers) sans instruction explicite de Laurent. Toute mise à jour non commandée est interdite.

## Arborescence Clés
- `maxicourses_test/` : scripts de relevés Playwright (`fetch_*_price.py`), utilitaires, états.
- `maxicourses_test/state/` : `*.json` de session Playwright (Carrefour, Leclerc, etc.).
- `maxicourses_test/debug_screens/` : captures à conserver lorsque c'est pertinent.
- `traces/` : enregistrements de parcours humains (voir `docs/PARCOURS_HUMAIN.md`).
- `docs/` : documentation persistante (présent fichier, checklist, brief quotidien).
- `DEVLOG.md` : journal global historique.

## Scripts et Procédure Rapide
1. **Lancer Chrome en mode remote** :
   ```bash
   cd maxicourses_test
   ./start_chrome_debug.sh
   ```
2. **Carrefour (exemple)** :
   ```bash
   USE_CDP=1 HEADLESS=0 QUERY="<recherche>" STATE_VARIANT=carrefour_city \
     python3 fetch_carrefour_price.py
   ```
3. **Leclerc Drive** :
   ```bash
   USE_CDP=1 HEADLESS=0 QUERY="<recherche>" \
     STORE_URL="https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx" \
     STATE_VARIANT=leclercdrive_bruges \
     python3 fetch_leclerc_drive_price.py
   ```
   ➜ vérifier visuellement la vignette ; conserver capture.

4. **Extraction via Chrome 9222** :
   - Utiliser `scrape_active_tab_price.py` si une fiche est déjà ouverte dans Chrome remote.
   - En cas de blocage robot, enregistrer/rejouer un parcours humain (voir `docs/PARCOURS_HUMAIN.md`) et documenter la méthode dans le handover.

## Où Documenter ?
- `docs/HANDOVER_DAILY.md` : à compléter à chaque fin de session.
- `docs/PRICE_COMPARATOR_PLAN.md` : feuille de route technique.
- Captures + scripts référencés dans `docs/README.md`.

## Checklist de Démarrage (résumé)
- Lire `docs/ONBOARDING.md` + `docs/README.md`.
- Parcourir `docs/PRICE_COMPARATOR_PLAN.md` pour l’état des travaux.
- Consulter `docs/HANDOVER_DAILY.md` (dernière entrée) avant toute action.
- Vérifier que Chrome 9222 tourne (`ps aux | grep Chrome` si doute).

Bienvenue à bord !
