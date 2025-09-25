# Guide de collecte prix par enseigne

## Règles globales (impératifs)
- Chrome remote lancé via `maxicourses_test/start_chrome_debug.sh` (profil `.chrome-debug`), puis toutes les commandes Playwright avec `USE_CDP=1`.
- Toujours obtenir un **descriptif seed** avant Leclerc : Carrefour en priorité ; si l’EAN est absent, basculer sur Auchan.
- Chaque sortie JSON doit inclure `price`, `unit_price` (€/kg ou €/L), `quantity`, `store`, `note` (horodatage UTC), `url`, `matched_ean`.
- Conserver les captures dans `maxicourses_test/debug_screens/` ou `maxicourses_test/debug/` et référencer la trace dans `docs/HANDOVER_DAILY.md`.
- Chaque produit possède un visuel local dans `maxicourses_test/pipeline/assets/` déclaré via `manual_descriptors.json` ; le comparateur (`pipeline/index2.html`) affiche ensuite un lien « Voir image ».

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
- **Traces** : conserver les traces humaines dans `traces/leclerc-*.jsonl` si la navigation change.
- **Résultats** : JSON par EAN dans `maxicourses_test/results/test-<EAN>/`, agrégat global `maxicourses_test/results/summary.json`.

## Carrefour (City / Market)
- **Script** : `maxicourses_test/fetch_carrefour_price.py` (Playwright CDP).
- **Magasins** :
  - Rejouer les traces `traces/carrefour-switch-back-20250923.jsonl` (City) & `traces/carrefour-store-switch-20250923.jsonl` (Market) via `python3 replay_leclerc_navigation.py`.
  - Variables : `STORE_QUERY`, `CARREFOUR_STATE_VARIANT` (`carrefour_city` ou `carrefour_market`).
- **Commandes types** :
  ```bash
  USE_CDP=1 HEADLESS=0 QUERY="<libellé>" STORE_QUERY="Bordeaux Balguerie" \
    CARREFOUR_STATE_VARIANT=carrefour_city python3 fetch_carrefour_price.py
  ```
- **Sorties** : `price`, `unit_price`, `store`, et capture visuelle si nécessaire.

## Auchan
- **Script** : `maxicourses_test/fetch_auchan_price.py` (CDP + seed humain `traces/auchan-20240922-clean.jsonl`).
- **Commandes** :
  ```bash
  USE_CDP=1 HEADLESS=0 EAN=<ean> QUERY="<libellé>" python3 fetch_auchan_price.py
  ```
- Sert de seed alternatif lorsque Carrefour n’a pas l’EAN.

## Intermarché
- **Script** : `maxicourses_test/fetch_intermarche_price.py` (CDP, accepter cookies via script).
- **Commandes** :
  ```bash
  USE_CDP=1 HEADLESS=0 EAN=<ean> QUERY="<libellé adopté>" python3 fetch_intermarche_price.py
  ```
- **Notes** : attendre que le prix apparaisse (commutateur rafraîchissement automatique). Sauvegarder `store` (ex. « Intermarché · Bordeaux Talence (drive) »).

## Chronodrive
- **Script** : `maxicourses_test/fetch_chronodrive_price.py` (CDP).
- **Magasin** : `STORE_URL="https://www.chronodrive.com/magasin/le-haillan-422"`.
- **Commandes** :
  ```bash
  USE_CDP=1 HEADLESS=0 STORE_URL=... QUERY="<libellé>" EAN=<ean> python3 fetch_chronodrive_price.py
  ```
- Si aucun produit ne correspond, enregistrer `NO_RESULTS` avec magasin et requête utilisée.

## Gestion des résultats & comparateur
- Chaque EAN dispose de `results/test-<EAN>/latest.json` et `summary.json`. L’agrégat global `results/summary.json` alimente `pipeline/index2.html`.
- Ajouter un produit dans le comparateur :
  1. Générer ou mettre à jour les JSON `results/test-<EAN>/`.
  2. Compléter `manual_descriptors.json` (titre, quantité, image locale, Nutri-score si dispo).
  3. Ajouter l’EAN dans `EXTRA_DATASETS` de `pipeline/index2.html`.
  4. Vérifier la page via `cd maxicourses_test && python3 -m http.server`.

## Documentation à lire impérativement
1. `docs/PROMPT_BOOTSTRAP.md` – check-list initiale et ton attendu.
2. `docs/ONBOARDING.md` – règles générales et scripts critiques.
3. `docs/LECLERC_HUMAN_METHOD.md` – workflow détaillé pour Leclerc Drive.
4. `docs/PARCOURS_HUMAIN.md` – enregistrement/rejeu des traces anti-bot.
5. `docs/HANDOVER_DAILY.md` – état des travaux (dernière entrée).
6. Ce guide (`docs/PRICE_COLLECTION_GUIDE.md`) pour connaître la méthode par enseigne.

## Traces & captures utiles
- `traces/auchan-20240922-clean.jsonl` – navigation Auchan seed.
- `traces/leclerc-20250924-*.jsonl` – sélection drive Bruges.
- `traces/carrefour-switch-*.jsonl` – bascule City ↔ Market.
- Captures debug dans `maxicourses_test/debug/` (HTML) et `maxicourses_test/debug_screens/` (PNG).

## Rappels finaux
- Toujours consigner un résumé de session dans `docs/HANDOVER_DAILY.md` (format `## YYYY-MM-DD - GPT`).
- Attacher les preuves (commandes, captures, JSON) aux entrées correspondantes.
- Aucun prix ne doit être saisi manuellement : tout provient des scripts Playwright/CDP.
