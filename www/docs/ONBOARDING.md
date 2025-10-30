# Maxicourses Assistant Onboarding

## Mission Snapshot
- Maintenir et enrichir les scripts de relevé de prix (Carrefour, Leclerc Drive, etc.)
- Assurer une traçabilité claire des relevés (Chrome remote, captures si besoin) pour préparer le comparateur de prix intelligent.
- Capitaliser l'historique (décisions, obstacles, artefacts) afin que tout nouvel assistant reprenne le travail sans perte d'information.

## Dernière itération (2025-10-30)
- **Fait** : Leclerc Drive sélectionne désormais la bouteille unitaire Orangina 1,5 L. Correctifs appliqués : normalisation du descripteur (`brand`/queries ↦ « Orangina 1.5L »), filtrage des tokens quantité dans `run_pipeline.py`, et pénalités anti-pack côté `manual_leclerc_cdp.py`. Run de validation : `results/run-3124480200433-20251030-115344.json` (`matched_ean=3124480200433`).
- **À faire** : implémenter le verrou variante/negatives pour Monoprix (cf. `docs/monoprix_hotfix_brief.md`). Les requêtes générées sont correctes (`Orangina 1.5L`), mais l’adaptateur retourne encore `NO_RESULTS`.
- **À faire** : après stabilisation Monoprix, relancer `run_pipeline.py --ean 3124480200433 --headed` puis rafraîchir `results/test-3124480200433/latest.json` + page comparateur.

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
