# Maxicourses Assistant Onboarding

## Mission Snapshot
- Maintenir et enrichir les scripts de relevé de prix (Carrefour, Leclerc Drive, etc.)
- Assurer une traçabilité claire des relevés (Chrome remote, captures si besoin) pour préparer le comparateur de prix intelligent.
- Capitaliser l'historique (décisions, obstacles, artefacts) afin que tout nouvel assistant reprenne le travail sans perte d'information.

## Garde-fous immédiats
- **Gel fetchers existants** : ne toucher sous aucun prétexte aux scripts `fetch_carrefour_price_market.py`, `fetch_carrefour_price_city.py`, `fetch_auchan_price.py`, `fetch_chronodrive_price.py`, `fetch_courseu_price.py`, `fetch_intermarche_price.py`, `fetch_leclerc_drive_price.py`, `fetch_monoprix_price.py` (ni à leurs helpers) tant que Laurent n’a pas validé une modification. Les travaux en cours ne concernent que `fetch_carrefour_price_super.py` et sa configuration.
- Les requêtes humaines doivent conserver des espaces (`"coca cola 1,75 l"`) ; bannir les `+` quels que soient les magasins.

## Dernière itération (2025-10-30)
- **Fait** : Leclerc Drive sélectionne désormais la bouteille unitaire Orangina 1,5 L. Correctifs appliqués : normalisation du descripteur (brand/queries → « Orangina 1.5L »), filtrage des tokens quantité dans `run_pipeline.py`, et pénalités anti-pack dans `manual_leclerc_cdp.py`. Run de validation : `results/run-3124480200433-20251030-115344.json` (`matched_ean=3124480200433`).
- **Fait** : Monoprix verrouillé via variant lock + négatifs dynamiques. Implémentation : `fetch_monoprix_price.py` évalue désormais la variante détectée, la famille d’unité et la taille (tolérance ±25 %), et rejette les cartes contenant des variantes négatives. Les requêtes Monoprix sortent en « marque + variant/volume » via `query_builder.py`. Run de validation : `results/run-3124480200433-20251030-122923.json` (`status=OK`, prix 2,45 €).
- **Mise à jour 2025-10-31** : Abandon du mode « PDP cache » pour Leclerc Drive. Chaque collecte rejoue la recherche complète, `manual_leclerc_cdp.py` n’écrit plus de `leclerc_url` dans `manual_descriptors.json`, et le flag `LECLERC_FAST_MODE=1` divise tous les délais par 10 pour éliminer l’attente de 20 min observée en mode standard.
- **Problème chronodrive/auchan/courseu (30/10)** : enchaînement « goto recherche » → redirection → fermeture de l’onglet (erreur `TargetClosedError`). Les moteurs n’aiment pas les requêtes URL encodées (`coca+cola+1,75l`). Solution à déployer : rejouer la saisie comme un humain (focus champ de recherche, frappe caractère par caractère), laisser les espaces, et stocker les PDP dès qu’elles sont trouvées (équivalent Leclerc). EAN de test : `5000112611861` (Coca-Cola 1,75 L).
- **Problème Chronodrive confirmé (2025-10-31)** : la saisie « humaine » actuelle (`fetch_chronodrive_price.py`) retombe encore sur l’accueil (`https://www.chronodrive.com/magasin/le-haillan-422`). Les indices côté logs montrent que l’overlay recherche se referme avant la soumission et qu’aucun appel XHR n’est déclenché. Hypothèse : mouvement anti-bot (délai trop court + `press` sur l’input). À corriger : ouvrir explicitement l’overlay via le bouton loupe, typer avec `page.keyboard`, attendre le rendu du champ suggestion, puis cliquer sur l’icône loupe (pas de `Enter`). Vérifier que le délai total n’excède pas 2 s entre la frappe et le clic. Conserver ce comportement même quand on injecte directement l’URL PDP (`manual_descriptors.json` → `chronodrive_url`).
- **Problème Chronodrive (règle « pas de + »)** : rappeler que toutes les chaînes passées aux scripts doivent remplacer `+` par un espace simple avant frappe. Le pipeline actuel envoie encore des requêtes `coca+cola+1,75l` quand le descripteur provient d’une source legacy. Le nettoyage doit être doublé : côté `query_builder` (génération IA) et côté fetchers (`_normalize_term_for_typing` / `normalize_search_term`).
- **Auchan / CourseU (2025-10-31)** : même contexte anti-bot, la page résultats ne se charge pas quand on détecte un `TargetClosedError`. À investiguer après Chronodrive : vérifier qu’on clique bien sur la suggestion #1 avant d’ouvrir la PDP, sinon forcer la requête API catalogue comme sur Leclerc. Garder l’EAN `5000112611861` comme smoke test.
- **Correctif Chronodrive déployé (2025-10-30 soir)** : `fetch_chronodrive_price.py` contourne désormais l’overlay capricieux en interrogeant l’API suggestions (`/v1/search-suggestions`) puis l’API produit (`/v1/products/{id}`) avec les en-têtes `x-chronodrive-site-id=1006`. On sélectionne le meilleur candidat via l’EAN + tokens, on résout la `canonicalUrl` et on ouvre la PDP Playwright (<2 s). Les anciens fallback UI restent présents mais ne devraient plus se déclencher.
- **Nouveau scope Carrefour Super Lormont (2025-10-31)** : le wrapper `fetch_carrefour_price_super.py` reproduit la stratégie City/Market avec `STORE_QUERY="Super Lormont"`. Le pipeline connaît désormais l’adaptateur `carrefour_super` (logo Carrefour + label « Super ») et le point GPS (lat 44.867007, lon -0.516348). Seed en EAN brut obligatoire, aucune régression tolérée sur City/Market.
- **À faire Carrefour Super** : l’état CDP actuel (`state/carrefour_super.json`) contient encore `FRONTAL_STORE=116` (Market Fondaudège). Il faut **rejouer un parcours humain** (ouvrir Chrome 9222, clic « Drive » → « Changer de drive » → rechercher « Lormont ») et sélectionner la fiche **« Lormont, Gironde, France »** (le site n’affiche pas « Lormont Super »). Enregistrer la trace/ID comme pour City/Market et relever `displayableUrlId`, `facilityServiceId`, `FRONTAL_STORE` avant de relancer des collectes.
- **À faire** : propager ces règles à d’autres seeds (vérifier desserts végétaux), archiver les captures Monoprix/Leclerc dans `results/debug/` et mettre à jour la page comparateur (rafraîchir `results/test-3124480200433/latest.json` déjà régénéré, contrôler le rendu web).
- **Mise à jour Monoprix (2025-11-02)** :
  - `_descriptor_validation_tokens` inclut le profil canonique pour imposer ≥ 70 % de couverture des tokens (marque, forme, quantité) ; les tokens purement numériques sont neutralisés.
  - `_descriptor_remote_images` remonte les visuels `canonical.images` / `reference_image(s)` ; l’asset seed `3088545004001` est désormais la bouteille « squeeze » (Carrefour).
  - `_collect_monoprix_negatives` respecte le flag `allow_monoprix_squeeze` dans `manual_descriptors.json` pour éviter les faux veto.
  - Tests `tests/test_monoprix_validation.py` vérifient la couverture et l’agrégation d’images. Run de contrôle : `USE_CDP=1 HEADLESS=0 EAN=3088545004001` → fiche « Lune de Miel Squeeze Miel de Fleur 500g » validée.

## Règles Incontournables
1. **Collecte seed systématique** : commencer chaque produit par une recherche **100 % EAN brut** (sans texte additionnel) sur les enseignes qui l’acceptent :
   - Carrefour Market d’abord, puis Carrefour City (via les wrappers CDP),
   - ensuite Auchan,
   - puis Chronodrive,
   - et Course U (Super U Eysines).
  Une fois ce descriptif fiable (titre, quantité) récupéré, l’enregistrer dans `manual_descriptors.json` et l’utiliser pour enchaîner Intermarché, Leclerc puis Monoprix (qui ne prennent pas l’EAN brut).
2. **Leclerc Drive** : toute interaction passe par Chrome remote (port 9222) + validation visuelle. `USE_CDP=1`, `HEADLESS=0`. Aucun scraping headless ni requête directe.
3. **Carrefour** : privilégier Chrome remote pour contourner Cloudflare. Toujours sauvegarder au besoin les captures (`HUMAN_DEBUG_DIR`).
4. **Preuve humaine** : conserver les captures dans `maxicourses_test/debug_screens/` ou via les scripts existants. Nommer les fichiers explicitement (`leclerc_ketchup_search_only.png`, etc.).
5. **Ne jamais écraser** les modifications utilisateur existantes. Toute évolution passe par de nouveaux fichiers ou des ajouts contrôlés.
6. **Validation commits** : toujours demander l’accord explicite de l’utilisateur avant tout `git commit` (ou action équivalente).
7. **Documentation vivante** : mettre à jour les fichiers de handover pour tout changement significatif.
8. **Requêtes IA** : après chaque seed réussi, lancer `USE_AI_ASSIST=true ./run_ai_pipeline.sh <EAN>` pour générer (OpenAI) des requêtes ≤30 caractères destinées aux enseignes textuelles (Leclerc/Monoprix/Intermarché). Les résultats sont stockés dans `manual_descriptors.json`.
9. **Intermarché** : recherche textuelle uniquement et validation stricte via l’EAN embarqué dans l’URL (`…/produit/<slug>-<EAN>`). Toute fiche dont l’URL ne contient pas l’EAN attendu est rejetée automatiquement par le fetcher.
10. **Leclerc** : toutes les requêtes générées automatiquement respectent la forme « marque + fonction/nom + quantité » (au moins trois mots) afin d’éviter les recherches trop larges.
11. **Monoprix** : les requêtes sont limitées à **deux** mots-clefs : d’abord la marque, ensuite la fonction ou un terme issu du seed (ex. `Destop Déboucheur`). Toute suggestion automatique est normalisée en ce sens.
12. **Course U** : en cas de blocage Cloudflare (`status="CF_BLOCK"` ou `NO_PRICE` avec un autre EAN), ouvrir le drive Super U Eysines via Chrome remote, accepter les challenges, fermer l’overlay marketing qui masque la barre de recherche, puis régénérer `state/courseu.json` (`USE_CDP=1 python3 save_state_from_cdp.py courseu`) avant de relancer la collecte.
    - Si l’overlay n’est pas fermé, le fetcher bascule sur une page promo (ex. lessive Skip) : on obtient `status="NO_PRICE"` et un `matched_ean` incorrect. Toujours valider la recherche manuelle (EAN Destop → fiche Destop) juste avant de sauvegarder la state.
    - Dès qu’un fetch Course U aboutit, le script mémorise automatiquement l’URL de la fiche (`courseu_url` / `courseu_slug` dans `manual_descriptors.json`) et réutilise cette PDP lors des runs suivants pour éviter Cloudflare. Vérifier que cette URL reste valable et ne pas la supprimer.
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
