# Maxicourses Assistant Onboarding

## Mission Snapshot
- Maintenir et enrichir les scripts de relevé de prix (Carrefour, Leclerc Drive, etc.)
- Assurer une traçabilité claire des relevés (Chrome remote, captures si besoin) pour préparer le comparateur de prix intelligent.
- Capitaliser l'historique (décisions, obstacles, artefacts) afin que tout nouvel assistant reprenne le travail sans perte d'information.

## Garde-fous immédiats
- **Gel fetchers existants** : ne toucher sous aucun prétexte aux scripts `fetch_carrefour_price_market.py`, `fetch_carrefour_price_city.py`, `fetch_chronodrive_price.py`, `fetch_courseu_price.py`, `fetch_intermarche_price.py`, `fetch_leclerc_drive_price.py`, `fetch_monoprix_price.py`, `fetch_carrefour_price_super.py` (ni à leurs helpers) tant que Laurent n’a pas validé une modification. Les travaux en cours ne concernent que,  `fetch_auchan_price.py` ainsi que verifier que la collect globale à partir de index2.html ne s'arrete pas à intermarche ! 

- Les requêtes humaines doivent etre tapé avec des espaces (`"coca cola 1,75 l"`) ; bannir les `+` quels que soient les magasins (le fait d'ajouter de "+" force des mots clés et augment la quantité de resultats sur certain magasins).

Nous utilison `finder.py` et plus du tout de fichier .json pour definir les mots cles de recherche et les mots cles de descriptif pour pre-validations de fiche avant matching image! 

Il est strictement interdit de toucher aux fetcher autre que auchan!

//
- **URGENT PRIORITE : Auchan Talence (2025-11-05)** : 
Recommencer l'intégralité de la collect AUCHAN car tout a été saccagé par le précendent GPT! il faut repartir de zero! AUCHAN accept la recherche directe via EAN! eventuellement rechercher la sauvegarde de fetch_auchan_price.py datant de avant le 01/11/2025

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
