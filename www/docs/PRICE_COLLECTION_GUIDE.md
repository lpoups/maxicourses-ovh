# Guide de collecte prix par enseigne

- Chrome remote lancé via `maxicourses_test/start_chrome_debug.sh` (profil `.chrome-debug`), puis toutes les commandes Playwright avec `USE_CDP=1`.
- **Recherche EAN brut obligatoire** : pour tout nouveau produit, taper directement le code EAN (sans texte) sur les enseignes seed qui l’acceptent – Carrefour City/Market → Auchan → Chronodrive. Dès qu’un descriptif fiable est obtenu, l’enregistrer dans `manual_descriptors.json` et l’utiliser pour les enseignes ne supportant pas la recherche EAN (Leclerc, Intermarché, etc.).
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

## Auchan
- **Script** : `maxicourses_test/fetch_auchan_price.py` (CDP + seed humain `traces/auchan-20240922-clean.jsonl`).
- **Commandes** :
  ```bash
  USE_CDP=1 HEADLESS=0 EAN=<ean> QUERY="<libellé seed ou EAN>" python3 fetch_auchan_price.py
  ```
- Sert de seed alternatif lorsque Carrefour n’a pas l’EAN ; taper d’abord l’EAN brut, puis réutiliser le descriptif trouvé pour les autres enseignes.

## Intermarché
- **Script** : `maxicourses_test/fetch_intermarche_price.py` (CDP, accepter cookies via script).
- **Commandes** :
  ```bash
  USE_CDP=1 HEADLESS=0 EAN=<ean> QUERY="<libellé adopté>" python3 fetch_intermarche_price.py
  ```
- **Notes** : attendre que le prix apparaisse (commutateur rafraîchissement automatique). Sauvegarder `store` (ex. « Intermarché · Bordeaux Talence (drive) »).

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
- `traces/carrefour-switch-back-20250923.jsonl` puis `traces/carrefour-store-switch-20250923.jsonl` – séquence obligatoire avant toute collecte Carrefour (City puis Market).
- Captures debug dans `maxicourses_test/debug/` (HTML) et `maxicourses_test/debug_screens/` (PNG).

## Rappels finaux
- Toujours consigner un résumé de session dans `docs/HANDOVER_DAILY.md` (format `## YYYY-MM-DD - GPT`).
- Attacher les preuves (commandes, captures, JSON) aux entrées correspondantes.
- Aucun prix ne doit être saisi manuellement : tout provient des scripts Playwright/CDP.
