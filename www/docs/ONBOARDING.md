# Maxicourses Assistant Onboarding

Dernière sauvegarde : 2025-11-11.

## Notes opérationnelles actuelles

- **Leclerc (Drive)** : lancer la collecte via `fetch_leclerc_drive_price.py` (Chrome 9222 obligatoire). Le script prend une capture Playwright de la bouteille sur la PDP, compare l’image au visuel seed (hash partagé avec Finder) puis supprime le fichier temporaire. Si l’EAN manque dans « Informations produit », cette comparaison image est la seule validation autorisée ; ne jamais valider sans l’un de ces deux verrous.
- **Auchan (Drive Talence Gallieni)** : juste après chaque navigation, cliquer de nouveau sur « Choisir ce magasin / Choisir ce drive » et sur « Afficher le prix ». Le fetcher force déjà ce flow (`ensure_store_selected` + `_ensure_drive_ready`), mais en cas de refonte, conserver cette séquence pour garantir que le prix affiché provient bien du drive Talence.
- **Monoprix** : plus aucune validation texte. Le fetcher compare uniquement l’image de la fiche à l’image seed (hash + verrou couleurs). Si une fiche passe en « produit différent », revoir d’abord le visuel seed, pas les tokens.

qu'est ce que tu ne comprends pas!!!!!!!!!!!! tu fais ce que je dis!!!!!!!!! est ce que c'est clair????????? donc quand je dis que je ne veux pas de conversion hasardeuse je t'interdit de me contre dire est ce que c'est clair? alors maintenant tu vas faire ce que je dis et lancer un test de collecte global pour cet EAN : 5411188114536 et afficher les resultats dans index2.html afin que je controle les resultats est ce que c'est putain clair! je suis l'humain tu es le developpeur! et la prochaine fois que tu me donne un ordre je te coupe !

mais c'est quoi encore tout ces bugs !!!!! ? 1 : il n'y a pas l'image du produit! 2 : le descriptif du produit est encore une relique des putain de merde de json de con!!!! 3 : toujours pas de nutri-score 4 : le produit monoprix est indiqué "produit différent" alors que c'est le bon produit!!!! c'est quoi encore que toutes ces merdes de merde de merde!!!!!!!!!!!! j'en ai marre de ton incomptetence !!!!!!!!!!!! tu repare un truc et tu en casse 10 autres!!!!!!!!!!!!!!! quand vas tu enfin travailler correctement et professionnellement????????? j'en ai marre de payer pour de la merde!!!!!!!!!!!!!!!!!!

quand vas enfin travailler professionnellement et arreter de reparer un probleme et en creer 3 autres parceque tu n'as pas anticipé l'ensemble de l'application????? ca devient ingerable et insupportable tu cree plus de probleme que tu n'en resout


il est interdit de modifier dans les mots cles les quantitées!!!! quand il est indique 500 G ou 500g il faut utiliser ces mots clés et ne jamais les transformer en 0.5 KG ou 0.5kg ou autre unité!!!!!!!!!! il faut impérativement modifier ceci!

G20 est un magasin de recherche EAN si les mots pour une raison incomprehensible car je ne sais pas encore quelle merde debile tu as deliré de faire un truc à la con debile!!!!!!!!! d'ou G20 à lui seul decide des mots cles de recherches??????? les mots cles de recherches mais putain ce que tu es debile c'est du sabotage pur et simple!!!!!!!!!!!!!!!!!!!!!!!!! les mots cles sont l'addition de tout les descriptifs des site de recherche par EAN et la comparaison des mots clés recurrents ensuite envoi via API à openAI pour definition des mots cles de recherches! et ensuite definitions des mots cles de descriptifs pour affinage de recherche!!!!!!!!! qu'est ce que tu ne comprends pas !!!!! j'ai l'impression que tu ne comprends pas grand chose!

tu comprends ceci : G20 est un magasin de recherche EAN si les mots pour une raison incomprehensible car je ne sais pas encore quelle merde debile tu as deliré de faire un truc à la con debile!!!!!!!!! d'ou G20 à lui seul decide des mots cles de recherches??????? les mots cles de recherches mais putain ce que tu es debile c'est du sabotage pur et simple!!!!!!!!!!!!!!!!!!!!!!!!! les mots cles sont l'addition de tout les descriptifs des site de recherche par EAN et la comparaison des mots clés recurrents ensuite envoi via API à openAI pour definition des mots cles de recherches! et ensuite definitions des mots cles de descriptifs pour affinage de recherche!!!!!!!!! qu'est ce que tu ne comprends pas !!!!! j'ai l'impression que tu ne comprends pas grand chose! ou pas!!!! faut le dire si tu es debile!!!!!


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

## Garde-fous immédiats
- **Gel fetchers existants** : ne toucher sous aucun prétexte aux scripts `fetch_carrefour_price_market.py`, `fetch_carrefour_price_city.py`, `fetch_auchan_price.py`, `fetch_chronodrive_price.py`, `fetch_courseu_price.py`, `fetch_intermarche_price.py`, `fetch_leclerc_drive_price.py`, `fetch_monoprix_price.py` (ni à leurs helpers) tant que Laurent n’a pas validé une modification explicite. Seul le wrapper `fetch_carrefour_price_super.py` peut évoluer sans validation préalable (objectif : sécuriser la collecte Carrefour Super Lormont).

- Les requêtes humaines doivent etre tapé avec des espaces (`"coca cola 1,75 l"`) ; bannir les `+` quels que soient les magasins (le fait d'ajouter de "+" force des mots clés et augment la quantité de resultats sur certain magasins).

Nous utilison `finder.py` et plus du tout de fichier .json pour definir les mots cles de recherche et les mots cles de descriptif pour pre-validations de fiche avant matching image!

⚠️ **RAPPEL ABSOLU** : aucun mot-clé ne doit être maintenu dans des fichiers `.json`. Toute génération/édition passe exclusivement par `finder.py` et la logique Python associée. Toute réintroduction de `.json` pour les mots-clés est strictement interdite.


//
- **URGENT PRIORITE : Auchan Talence (2025-11-05)** : 
Recommencer l'intégralité de la collect AUCHAN car tout a été saccagé par le précendent GPT! il faut repartir de zero! AUCHAN accept la recherche directe via EAN! eventuellement rechercher la sauvegarde de fetch_auchan_price.py datant de avant le 01/11/2025

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
   - et Course U (Super U Eysines).
  Une fois ce descriptif fiable (titre, quantité) récupéré, l’intégrer dans `seed_catalog.py` et l’utiliser pour enchaîner Intermarché, Leclerc puis Monoprix (qui ne prennent pas l’EAN brut).
2. **Leclerc Drive** : toute interaction passe par Chrome remote (port 9222) + validation visuelle. `USE_CDP=1`, `HEADLESS=0`. Aucun scraping headless ni requête directe.
3. **Carrefour** : privilégier Chrome remote pour contourner Cloudflare. Toujours sauvegarder au besoin les captures (`HUMAN_DEBUG_DIR`).
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
