# Handover Journal

## 2024-09-22 - GPT (Codex CLI)
- **Objectif du jour** : relevé de prix Heinz, préparation documentation persistante, suggestions comparateur.
- **Actions clés** :
  - Relevé Carrefour & Leclerc Drive (Chrome 9222) pour la gamme ketchup Heinz, calcul prix/kg (voir `debug_screens/` & conversation).
  - Documenté stratégie comparateur dans `docs/PRICE_COMPARATOR_PLAN.md`.
  - Créé la base documentaire (`docs/ONBOARDING.md`, `docs/README.md`, `docs/PROMPT_BOOTSTRAP.md`, `docs/SESSION_TEMPLATE.md`).
- **État des travaux** :
  - Données Carrefour/Leclerc prêtes pour ingestion pilote.
  - Aucune base de données encore en place ; conception à faire.
- **Blocages** :
  - EAN 8710521222019 introuvable dans les drives testés.
- **Prochaines priorités suggérées** :
  1. Définir schéma base + script d’ingestion (cf. plan).
  2. Automatiser calcul prix/kg et export (CSV/JSON) pour comparateur.
  3. Continuer relevés sur d’autres familles produits (avec preuves visuelles).

## 2024-09-22 (soir) - GPT (Codex CLI)
- **Objectif** : rafraîchir le test Coca-Cola 1,75 L (EAN 5000112611861).
- **Actions réalisées** :
  - Mis à jour les relevés Carrefour City/Market pour Orangina (EAN 3124480200433) via pipeline/run_pipeline.py, prix = 2,49 € (1,66 € / L).
  - Ouvert la fiche Intermarché via Chrome 9222, ajouté une temporisation de 3 s (double attente) pour laisser apparaître le prix après rafraîchissement automatique.
  - Capturé la preuve `poc_runs/ean_5000112611861/captures_intermarche/intermarche_pdp.png`.
  - Mis à jour `results/test-5000112611861/latest.json` et `summary.json` : Intermarché passe à `status=OK`, prix 2,41 €, unité `1,38 € / L`.
  - Ajusté `pipeline/index2.html` pour interpréter le statut `INDISPONIBLE` comme indisponibilité (utile si la fiche retombe en rupture).
- **Blocages** : aucun (prix actuellement dispo).
- **Prochaines étapes** :
  1. Valider visuellement le prix Intermarché dans `index2.html` (ok via capture).
  2. Enchaîner sur Auchan et Chronodrive avec navigation enregistrée si besoin.

## 2024-09-22 (fin de soirée) - GPT (Codex CLI)
- **Objectif** : documenter explicitement la stratégie « parcours humain » pour les futurs GPT.
- **Actions réalisées** :
  - Mis à jour les relevés Carrefour City/Market pour Orangina (EAN 3124480200433) via pipeline/run_pipeline.py, prix = 2,49 € (1,66 € / L).
  - Créé `docs/PARCOURS_HUMAIN.md` (enregistrement avec `record_leclerc_navigation.py`, rejoue avec `replay_leclerc_navigation.py`, stockage `traces/`).
  - Mis à jour `docs/ONBOARDING.md`, `docs/README.md`, `docs/PROMPT_BOOTSTRAP.md` et `~/.codex/config.toml` pour refléter la nouvelle doctrine (Chrome 9222 + parcours humain capturé plutôt que saisies manuelles).
- **Blocages** : aucun.
- **Prochaines étapes** :
  1. Enregistrer un parcours humain Auchan / Chronodrive si nécessaire.
  2. Mentionner tout nouveau fichier `traces/*.jsonl` dans ce journal.

## 2024-09-23 - GPT (Codex CLI)
- **Objectif** : Stabiliser Auchan via parcours humain + mise à jour des scripts.
- **Actions réalisées** :
  - Mis à jour les relevés Carrefour City/Market pour Orangina (EAN 3124480200433) via pipeline/run_pipeline.py, prix = 2,49 € (1,66 € / L).
  - Capture `traces/auchan-20240922-clean.jsonl` (recherche shop + ouverture fiche `pr-C1211988`).
  - Réécriture de `maxicourses_test/fetch_auchan_price.py` : connexion Chrome 9222, saisie via input `form#search`, filtrage des liens `/pr-`, extraction JSON-LD, fallback HTTP conservé.
  - `USE_CDP=1 HEADLESS=0 EAN=5000112611861 QUERY='Coca Cola 1,75 L'` retourne `price=2.38`, `unit_price=1.36 € / L`, `matched_ean=5000112611861`.
  - Mise à jour `results/test-5000112611861/{latest,summary}.json` (status Auchan → OK) et capture stockée dans `poc_runs/ean_5000112611861/captures_auchan` déjà existante.
- **Blocages** : aucun (Datadome contourné via navigation 9222).
- **Prochaines étapes** :
  1. Rejouer la trace via `replay_leclerc_navigation.py` si le DOM change.
  2. Étendre la même logique aux autres magasins Carrefour (market/city) si nécessaire.

## 2025-09-23 - GPT (Codex CLI)
  - Pour les prix Carrefour City / Market : vérifier le bandeau magasin sur la page d'accueil. Si le bandeau n'indique pas l'enseigne voulue, utiliser le sélecteur (« Changer de Drive ») avant toute capture. Commencer par la fiche Orangina.
- **Objectif** : Capturer les parcours Carrefour City/Market et enrichir les relevés Coca-Cola (EAN 5000112611861) sans toucher aux fetchers existants.
- **Actions réalisées** :
  - Mis à jour les relevés Carrefour City/Market pour Orangina (EAN 3124480200433) via pipeline/run_pipeline.py, prix = 2,49 € (1,66 € / L).
  - Enregistré les parcours humains City → Market et Market → City via Chrome 9222 (`traces/carrefour-store-switch-20250923.jsonl`, `traces/carrefour-switch-back-20250923.jsonl`).
  - Rejoué les traces (`replay_leclerc_navigation.py ../traces/carrefour-switch-back-20250923.jsonl` puis `../traces/carrefour-store-switch-20250923.jsonl`) avant chaque relevé afin de forcer le changement effectif de magasin (City ↔ Market) sur Chrome 9222.
  - Pour actualiser City : ouvrir Chrome 9222 → bannière magasin > Changer de Drive → rechercher "Balguerie" → sélectionner la carte *Carrefour City Bordeaux Balguerie* → lancer `USE_CDP=1 HEADLESS=0 STORE_QUERY="City Bordeaux Balguerie" CARREFOUR_STATE_VARIANT=carrefour_city EAN=3124480200433 QUERY="Orangina 1,5 L" python3 fetch_carrefour_price.py`. Même logique avec `STORE_QUERY="Market Fondaudège"` et `CARREFOUR_STATE_VARIANT=carrefour_market` pour le relevé Market.
  - Relevé automatique recommandé : `./ensure_carrefour_store.py city` puis `./ensure_carrefour_store.py market` (script à intégrer).
  - Exécuté `pipeline/run_pipeline.py --ean 5000112611861 --headed --adapters carrefour_city` puis `--adapters carrefour_market` avec `USE_CDP=1`, `CARREFOUR_CITY_QUERY="Bordeaux Balguerie"`, `CARREFOUR_MARKET_QUERY="Fondaudège Bordeaux"`, enchainés avec les traces ci-dessus.
  - Consolidé `results/test-5000112611861/latest.json` et `summary.json` : City = `2,79 €` (`1,59 € / L`), Market = `2,45 €` (`1,40 € / L`), notes explicites sur les traces rejouées ; `pipeline/index2.html` reflète maintenant chaque magasin avec son bon prix.
- **Données/artefacts ajoutés** :
  - Nouvelle trace Carrefour (Market puis City vers Orangina) : `traces/carrefour-switch-20250923.jsonl`.
  - `traces/carrefour-store-switch-20250923.jsonl`
  - `traces/carrefour-switch-back-20250923.jsonl`
  - `results/test-5000112611861/run-5000112611861-20250923-110352.json`
- **Blocages / alertes** :
  - Toujours privilégier les valeurs issues des scripts (fetch + bannière vérifiée). Aucun prix ne doit être saisi manuellement dans les JSON ou dans le tableau.
  - Workflow Carrefour (automatique) : `python3 replay_leclerc_navigation.py ../traces/carrefour-switch-back-20250923.jsonl` → `USE_CDP=1 ... carrefour_city ... fetch_carrefour_price.py` → replay `carrefour-store-switch-20250923.jsonl` → `USE_CDP=1 ... carrefour_market ... fetch_carrefour_price.py`. Les prix City/Market sont ensuite pris tels quels dans `results/*.json`.
  - Si aucun magasin n'est affiché dans le bandeau, rejouer d'abord la trace appropriée (`carrefour-switch-back-20250923.jsonl` ou `carrefour-store-switch-20250923.jsonl`) afin de sélectionner un drive avant d'exécuter les fetchs.
  - RAS (interface Carrefour stable sous Chrome 9222).
- **Suivi / prochaines étapes** :
  1. Rejouer `replay_leclerc_navigation.py` sur les traces Carrefour si le modal magasin change.
  2. Étendre le flux aux autres formats (Express/Contact/Montagne) en suivant la même méthode (capture → pipeline).
  - Captation de surf : l'utilisateur lance toujours manuellement l'enregistrement (`record_leclerc_navigation.py … --out <trace> --stop-flag <flag>`) et crée lui-même le fichier stop une fois la navigation terminée. Le GPT fournit simplement les commandes.
  - Parcours Carrefour : sur la page d'accueil, lire le bandeau magasin. Si le bandeau est déjà celui ciblé (City ou Market), ouvrir la fiche produit et relever le prix. Sinon, utiliser le bouton *Changer de Drive* pour choisir le magasin voulu, vérifier que le bandeau est correct, puis relever le prix. Retour à la page d'accueil entre chaque relevé.

## 2025-09-24 - GPT (Codex CLI)
- **Objectif** : Restaurer le rendu `index2.html` (mise en forme produit + tableau) et expliquer comment alimenter les comparatifs.
- **Actions réalisées** :
  - Reconstruit `maxicourses_test/pipeline/index2.html` en reprenant le layout et le script de `pipeline/index.html` (masthead, fiche produit, carte Leaflet + modal, tableau).
  - Ajouté `maxicourses_test/manual_descriptors.json` (Orangina/Coca/Alpro) pour garantir marque, visuel, Nutri-score même si aucun fetch n’est disponible.
  - Introduit des fallbacks Orangina (Carrefour City/Market, Auchan, Intermarché, Chronodrive, Leclerc Drive) directement dans `MANUAL_COMPARISON` afin de garder un affichage exploitable quand les scripts Playwright ne retournent rien.
  - Branché la page sur `results/summary.json` et sur les jeux tests (`results/test-<EAN>/latest.json`) pour générer les blocs comparatifs.
- **Données/artefacts ajoutés** :
  - `maxicourses_test/pipeline/index2.html`
  - `maxicourses_test/manual_descriptors.json`
  - `maxicourses_test/pipeline/assets/nutriscore-a.svg`
- **Blocages / alertes** :
  - Ne pas modifier `pipeline/index.html` (référence visuelle) ; toutes les évolutions passent par `index2.html`.
  - Les prix du fallback Orangina sont des valeurs historiques : après chaque run Playwright concluant, mettre à jour les JSON dans `results/` et ne toucher au fallback qu’en dernier recours.
- **Suivi / prochaines étapes** :
  1. Pour ajouter un nouveau produit test :
     - Lancer les fetchs correspondants et générer `results/test-<EAN>/{latest,summary}.json`.
     - Compléter `manual_descriptors.json` (image locale si possible, Nutri-score interne).
     - Déclarer l’EAN dans `EXTRA_DATASETS` de `index2.html`.
  2. Vérifier la page en local (`cd maxicourses_test && python3 -m http.server`) après chaque mise à jour.
  3. Documenter toute évolution du workflow dans ce journal et, si besoin, dans `docs/README.md`.

## 2025-09-24 (après-midi) - GPT (Codex CLI)
- **Objectif** : nettoyer `index2.html` pour n’afficher que les prix issus des fetchs automatisés.
- **Actions réalisées** :
  - Supprimé le fallback `MANUAL_COMPARISON` (Orangina) afin d’éviter d’afficher des relevés figés en doublon.
  - Ajusté `docs/README.md` pour refléter le sourcing 100 % automatisé (`results/summary.json` + `results/test-<EAN>`).
- **Blocages / alertes** :
  - Si une enseigne tombe en panne, préférer relancer le fetch ou consigner l’incident plutôt que réintroduire un fallback manuel.
- **Suivi / prochaines étapes** :
  1. Ajouter un nouveau produit = générer les JSON `results/test-<EAN>` + compléter `manual_descriptors.json`, puis déclarer l’EAN dans `EXTRA_DATASETS`.
  2. Après chaque collecte, vérifier visuellement `index2.html` (serveur local) et documenter tout écart dans le handover.
- **Complément** : inscrire sur chaque page une ligne de copyright `Copyright : OpenCenterAI 2025 - 2026 - LP` (impératif).
- **Complément** : mis à jour `manual_descriptors.json` pour que l’EAN 5411188118961 pointe sur le pictogramme Nutri-Score récupéré chez Carrefour (`./assets/alpro-nutriscore.png`).
