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

## 2025-09-24 (soir) - GPT (Codex CLI)
- **Objectif** : stabiliser la collecte Leclerc Drive (Bruges) sur l’EAN 5000112611861 en mimant un humain.
- **Actions réalisées** :
  - Écrit le script `maxicourses_test/manual_leclerc_cdp.py` (connexion CDP, saisie lente, ouverture PDP, extraction prix).
  - Documenté la méthode dans `docs/LECLERC_HUMAN_METHOD.md` et renforcé `docs/PROMPT_BOOTSTRAP.md` (ton strictement pro demandé par Laurent).
  - Mise à jour des fichiers `maxicourses_test/results/test-5000112611861/latest.json` et `summary.json` ainsi que `maxicourses_test/results/summary.json` avec le prix Leclerc 2,38 € (1,36 € / L) récupéré via Chrome 9222.
  - Ajout debug `results/debug/leclerc/` (captures HTML) pour inspection future.
- **Données/artefacts ajoutés** :
  - `maxicourses_test/manual_leclerc_cdp.py`
  - `docs/LECLERC_HUMAN_METHOD.md`
  - JSONs résultats Leclerc rafraîchis (5000112611861).
- **Blocages / alertes** :
  - Ne jamais relancer la collecte Leclerc sans Chrome 9222 + script humain (Datadome bloque sinon).
  - Respecter les délais (5 s accueil, 12 s résultats, 7 s PDP) et accepter les cookies OneTrust.
- **Suivi / prochaines étapes** :
  1. Intégrer cette logique directement dans `fetch_leclerc_drive_price.py` quand le temps le permet (reuse du helper ou portage complet).
  2. Enregistrer une nouvelle trace si Leclerc modifie l’UI (et mettre à jour doc / script).

## 2025-09-24 (nuit) - GPT (Codex CLI)
- **Objectif** : supprimer les anciennes méthodes Leclerc instables et ne garder que le flux humain.
- **Actions réalisées** :
  - Remplacé `fetch_leclerc_drive_price.py` par un wrapper minimal qui délègue à `manual_leclerc_cdp.run_manual_leclerc`.
  - Refactorisé `manual_leclerc_cdp.py` pour exposer la fonction réutilisable et documenté le comportement.
  - Mis à jour `docs/LECLERC_HUMAN_METHOD.md` et `docs/README.md` pour pointer uniquement vers cette méthode.
- **Données/artefacts ajoutés** :
  - Nouvelle version `manual_leclerc_cdp.py` (fonction + CLI).
  - Wrapper `fetch_leclerc_drive_price.py` simplifié.
- **Blocages / alertes** :
  - Toute collecte Leclerc doit passer par ce helper CDP (aucune autre méthode conservée).
- **Suivi / prochaines étapes** :
  1. Si besoin d’automatiser davantage, étendre `manual_leclerc_cdp.py` (ajout captures, logs) plutôt que recréer un fetch parallèle.

## 2025-09-24 (nuit tard) - GPT (Codex CLI)
- **Objectif** : référencer l’EAN 3700260216148 (Ultima chat stérilisé saumon) et obtenir le prix Leclerc via seed Auchan.
- **Actions réalisées** :
  - Collecté le prix Auchan (`7,55 €`) avec `fetch_auchan_price.py` (Chrome 9222).
  - Rejoué la recherche Leclerc avec le descriptif Auchan : `11,31 €` (Drive Bruges).
  - Créé `maxicourses_test/results/test-3700260216148/{latest,summary}.json` et mis à jour `results/summary.json`.
  - Enrichi `manual_descriptors.json` (entrée Ultima / 3 kg) pour affichage pipeline.
- **Données/artefacts ajoutés** :
  - `maxicourses_test/results/test-3700260216148/latest.json`
  - `maxicourses_test/results/test-3700260216148/summary.json`
  - Capture debug : `maxicourses_test/debug-search-3700260216148.png`
- **Blocages / alertes** :
  - Aucun seed Carrefour disponible pour cet EAN (traces renvoient Ricoré) ; seed = Auchan.
- **Suivi / prochaines étapes** :
  1. Vérifier l’affichage `pipeline/index2.html` après avoir ajouté l’EAN à `EXTRA_DATASETS`.
  2. Documenter la source Auchan si d’autres enseignes doivent servir de seed.

## 2025-09-25 - GPT (Codex CLI)
- **Objectif** : formaliser un guide unique pour les prochains GPT (collecte par enseigne).
- **Actions réalisées** :
  - Créé `docs/PRICE_COLLECTION_GUIDE.md` (scripts, commandes, traces, règles globales).
  - Mis à jour `docs/PROMPT_BOOTSTRAP.md` et `docs/README.md` pour pointer vers ce guide.
  - Normalisé les images produits (visuels locaux + lien « Voir image » systématique dans `index2.html`).
- **Blocages / alertes** :
  - Chronodrive Le Haillan ne renvoie pas l’EAN 3700260216148 (`NO_RESULTS`).
- **Suivi / prochaines étapes** :
  1. Remplacer les assets provisoires (ex. Ultima) par des photos locales haute résolution si disponibles.
  2. Ajouter toute nouvelle enseigne (ou nouvelle trace) dans le guide et le handover dès création.

## 2025-09-25 - GPT (Codex CLI)
- **Objectif** : corriger le fetcher Chronodrive et récupérer le prix Coca-Cola (EAN 5000112611861).
- **Actions réalisées** :
  - Refactorisé `maxicourses_test/fetch_chronodrive_price.py` : navigation directe via `/search/<terme>`, acceptation cookies Didomi, matching intelligent des vignettes, extraction JSON-LD (prix, gtin13, quantité) et calcul unitaire.
  - Ajouté `accept_cookies`/`extract_store_label` et enrichi le résultat (`matched_ean`, formatage quantité/unit_price).
  - Rejoué la collecte via Chrome CDP (drive Le Haillan affiché à l’écran) et mis à jour `results/test-5000112611861/{latest,summary}.json` + `results/summary.json` : Chronodrive confirme 2,45 € (1,40 € / L) horodaté 2025-09-25T12:53Z.
- **Données/artefacts ajoutés** :
  - `fetch_chronodrive_price.py` nouvelle version (CDP-friendly, seed via search URL).
  - Chronodrive payload rafraîchi dans les `results/` (EAN 5000112611861).
- **Blocages / alertes** :
  - En sandbox headless la page masque encore les prix tant que le magasin n’est pas fixé. Utiliser `USE_CDP=1` + store Le Haillan pour les runs réels.
- **Suivi / prochaines étapes** :
  1. Rejouer la collecte via Chrome 9222 pour capturer un screenshot PDP Chronodrive (ajouter dans `poc_runs/...` si nécessaire).
  2. Étendre la logique de sélection à d’autres EAN (test 3700260216148 lorsque nouvelle trace disponible).

## 2025-09-25 (suite) - GPT (Codex CLI)
- **Objectif** : automatiser la rafraîchissement multi-enseignes pour ALPRO (EAN 5411188118961).
- **Actions réalisées** :
  - Ajusté `fetch_auchan_price.py` et `fetch_intermarche_price.py` pour fiabiliser quantité/unité et format des prix (fallback manual_descriptors).
  - Normalisé la sortie Carrefour (`price` en format FR) et documenté la sélection Chronodrive 100% scriptée (`ensure_store_selected`).
  - Relancé les fetchers CDP (Carrefour City/Market, Leclerc, Auchan, Intermarché, Chronodrive) et mis à jour `results/test-5411188118961/{latest,summary}.json` + `results/summary.json`.
  - Préparé un nouveau produit démo (EAN 5411188103387 – Dessert soja vanille ALPRO) avec JSONs, manuel_descriptors et entrée `EXTRA_DATASETS` pour `pipeline/index2.html`.
  - Gravé dans `docs/PROMPT_BOOTSTRAP.md` + `docs/PRICE_COLLECTION_GUIDE.md` l’obligation de rejouer les traces City/Market avant chaque collecte Carrefour (séquence `carrefour-switch-back` puis `carrefour-store-switch`).
- **Données/artefacts ajoutés** :
  - Nouvelles entrées JSON pour chaque enseigne (prix 2025-09-25T14:25Z, unit_price/quantité cohérents).
  - Scripts modifiés : `fetch_auchan_price.py`, `fetch_intermarche_price.py`, `fetch_carrefour_price.py`, `fetch_chronodrive_price.py` (doc).
- **Blocages / alertes** :
  - Carrefour ne retourne pas toujours le prix au kg sur la page PDP ; prévoir un post-traitement si ce champ devient obligatoire.
- **Suivi / prochaines étapes** :
  1. Capturer des screenshots PDP (Intermarché/Chronodrive) pour preuve visuelle stockée dans `poc_runs/ean_5411188118961/`.
  2. Factoriser la récupération du Nutri-score/quantité dans un utilitaire commun pour éviter les heuristiques par script.

## 2025-09-28 - GPT (Codex CLI)
- **Objectif** : vérifier que toutes les consignes impératives figurent dans la documentation et consigner la session.
- **Actions réalisées** :
  - Relu `docs/PROMPT_BOOTSTRAP.md`, `docs/ONBOARDING.md`, `docs/PARCOURS_HUMAIN.md`, la dernière entrée de `docs/HANDOVER_DAILY.md`, `docs/PRICE_COLLECTION_GUIDE.md`, `docs/LECLERC_HUMAN_METHOD.md`, `docs/PRICE_COMPARATOR_PLAN.md`, `docs/README.md` et `docs/SESSION_TEMPLATE.md`.
  - Confirmé que les consignes clés (Chrome 9222 + USE_CDP, ordre seed Carrefour City→Market→Auchan→Chronodrive, interdiction « produit <EAN> », sorties JSON complètes avec image locale, mise à jour handover) sont présentes et cohérentes entre les documents.
  - Ajouté la section « Mise à jour 2025-09-28 » dans `docs/QUICKSTART_NEXT_GPT.md` pour tracer la relecture et rappeler les consignes.
- **Données/artefacts ajoutés** :
  - `docs/QUICKSTART_NEXT_GPT.md`: section « Mise à jour 2025-09-28 ».
  - `docs/HANDOVER_DAILY.md`: entrée du 2025-09-28.
- **Blocages / alertes** :
  - RAS.
- **Suivi / prochaines étapes** :
  1. Poursuivre les collectes EAN en respectant l’ordre seed et la méthode CDP.
  2. Mettre à jour la documentation si de nouvelles consignes sont introduites par Laurent.

## 2025-09-28 (soir) - GPT (Codex CLI)
- **Objectif** : Confirmer la bonne couverture documentaire des consignes impératives et consigner la session.
- **Actions réalisées** :
  - Relu l'ensemble des documents obligatoires pour vérifier que Chrome 9222 + USE_CDP, l'ordre seed Carrefour City→Market→Auchan→Chronodrive, l'interdiction des requêtes « produit <EAN> », les sorties JSON complètes avec image locale et la mise à jour du handover sont tous rappelés.
  - Ajouté la section « Mise à jour 2025-09-28 (Codex CLI) » à `docs/QUICKSTART_NEXT_GPT.md` pour tracer la relecture (RAS).
  - Préparé cette entrée de handover en suivant `docs/SESSION_TEMPLATE.md`.
- **Données/artefacts ajoutés** :
  - docs/QUICKSTART_NEXT_GPT.md#L1
- **Blocages / alertes** :
  - Aucun.
- **Suivi / prochaines étapes** :
  1. Poursuivre les collectes en respectant la séquence seed et l'usage CDP.
  2. Mettre à jour la documentation si de nouvelles consignes surgissent.

## 2025-09-28 (refonte V2) - GPT (Codex CLI)
- **Objectif** : Lancer la documentation de la refonte front V2 et sécuriser les consignes pour les prochains GPT.
- **Actions réalisées** :
  - Créé `docs/REFONTE_FRONT_V2.md` avec le plan détaillé (inventaire, nouveau front, pipeline, logs/tests).
  - Mis à jour `docs/QUICKSTART_NEXT_GPT.md` : lecture obligatoire du plan V2 + rappel de journaliser chaque run.
  - Préparé cette entrée de handover pour tracer le démarrage.
- **Données/artefacts ajoutés** :
  - docs/REFONTE_FRONT_V2.md
  - docs/QUICKSTART_NEXT_GPT.md
- **Blocages / alertes** :
  - Aucun.
- **Suivi / prochaines étapes** :
  1. Cloner l’UI actuelle dans `maxicourses_front_v2/` et conserver les composants sains.
  2. Mettre en place la collecte de logs/tests ciblés avant corrections.

## 2025-09-28 (sauvegarde GitHub) - GPT (Codex CLI)
- **Objectif** : Vérifier la configuration GitHub et documenter la procédure de sauvegarde avant la refonte V2.
- **Actions réalisées** :
  - Contrôlé `git status -sb` et `git remote -v` (origin = https://github.com/lpoups/maxicourses-ovh.git).
  - Créé `docs/GIT_SAUVEGARDE.md` avec la checklist complète (status, remote, pull, push).
  - Ajouté les rappels dans `docs/QUICKSTART_NEXT_GPT.md` et `docs/REFONTE_FRONT_V2.md`.
- **Données/artefacts ajoutés** :
  - docs/GIT_SAUVEGARDE.md
  - docs/QUICKSTART_NEXT_GPT.md
  - docs/REFONTE_FRONT_V2.md
- **Blocages / alertes** :
  - Plusieurs fichiers cache Chrome listés par `git status`; à ignorer au moment des commits.
- **Suivi / prochaines étapes** :
  1. Lancer la duplication de l’UI dans `maxicourses_front_v2/` (après checklist Git).
  2. Mettre en place l’arborescence de logs/tests conformément au plan V2.

## 2025-09-28 (journal prompts) - GPT (Codex CLI)
- **Objectif** : Instaurer un suivi horodaté des échanges utilisateur/assistant.
- **Actions réalisées** :
  - Créé `docs/PROMPT_LOG.md` et rétro-consigné l’ensemble des messages de la session (UTC).
  - Mis à jour `docs/QUICKSTART_NEXT_GPT.md` pour rendre ce journal obligatoire à la lecture et à la mise à jour.
- **Données/artefacts ajoutés** :
  - docs/PROMPT_LOG.md
  - docs/QUICKSTART_NEXT_GPT.md
- **Blocages / alertes** :
  - Aucun.
- **Suivi / prochaines étapes** :
  1. Continuer d’appendre chaque nouvel échange dans `docs/PROMPT_LOG.md`.
  2. Poursuivre les travaux de refonte V2 selon le plan établi.

## 2025-09-29 (horodatage FR) - GPT (Codex CLI)
- **Objectif** : Basculer toutes les sauvegardes et journaux sur l’heure française.
- **Actions réalisées** :
  - Ajouté une consigne horaire dans `docs/QUICKSTART_NEXT_GPT.md` (Europe/Paris).
  - Complété `docs/GIT_SAUVEGARDE.md` avec la règle d’horodatage France.
  - Mis à jour `docs/REFONTE_FRONT_V2.md` pour refléter cette contrainte.
  - Journalisé la demande dans `docs/PROMPT_LOG.md` avec heure de Paris.
- **Données/artefacts ajoutés** :
  - docs/QUICKSTART_NEXT_GPT.md
  - docs/GIT_SAUVEGARDE.md
  - docs/REFONTE_FRONT_V2.md
  - docs/PROMPT_LOG.md
- **Blocages / alertes** :
  - Aucun.
- **Suivi / prochaines étapes** :
  1. Poursuivre la mise en place de la V2 (duplication front, logs/tests).
  2. Appliquer systématiquement l’horodatage Europe/Paris dans les sauvegardes et handovers.

## 2025-09-29 (bug requêtes EAN) - GPT (Codex CLI)
- **Objectif** : Noter l’anomalie "produit + EAN" dans les seeders.
- **Actions réalisées** :
  - Ajouté un item dans `docs/REFONTE_FRONT_V2.md` (corrections itératives) pour supprimer le préfixe "produit" sur les requêtes EAN.
- **Données/artefacts ajoutés** :
  - docs/REFONTE_FRONT_V2.md
  - docs/PROMPT_LOG.md
- **Blocages / alertes** :
  - Bug actuel : certains scripts seed tapent "produit <EAN>" au lieu de l’EAN brut (priorité élevée).
- **Suivi / prochaines étapes** :
  1. Identifier les scripts concernés et corriger l’injection EAN (Carrefour, Auchan, Chronodrive).
  2. Revalider la collecte seed après correction.

## 2025-09-29 (Open Food Facts) - GPT (Codex CLI)
- **Objectif** : Consigner l’autorisation d’utiliser fr.openfoodfacts.org pour enrichir les fiches produit.
- **Actions réalisées** :
  - Ajout d’un principe dans `docs/REFONTE_FRONT_V2.md` (Open Food Facts pour métadonnées, visuels conservés).
  - Mise à jour `docs/PRICE_COLLECTION_GUIDE.md` avec une section dédiée.
  - Consigne impérative ajoutée dans `docs/QUICKSTART_NEXT_GPT.md` et trace dans `docs/PROMPT_LOG.md`.
- **Données/artefacts ajoutés** :
  - docs/REFONTE_FRONT_V2.md
  - docs/PRICE_COLLECTION_GUIDE.md
  - docs/QUICKSTART_NEXT_GPT.md
  - docs/PROMPT_LOG.md
- **Blocages / alertes** :
  - Aucun.
- **Suivi / prochaines étapes** :
  1. Prévoir l’intégration Open Food Facts lors de la refonte pipeline.
  2. Conserver les visuels enseignes lors de l’affichage comparatif.

## 2025-09-29 (transparence) - GPT (Codex CLI)
- **Objectif** : Rappeler l’interdiction de mentir et la nécessité d’annoncer tout blocage.
- **Actions réalisées** :
  - Ajout d’un principe de transparence dans `docs/REFONTE_FRONT_V2.md`.
  - Mise à jour de `docs/QUICKSTART_NEXT_GPT.md` avec une consigne explicite.
  - Journalisation dans `docs/PROMPT_LOG.md`.
- **Données/artefacts ajoutés** :
  - docs/REFONTE_FRONT_V2.md
  - docs/QUICKSTART_NEXT_GPT.md
  - docs/PROMPT_LOG.md
- **Blocages / alertes** :
  - Aucun.
- **Suivi / prochaines étapes** :
  1. Continuer la refonte V2 conformément aux consignes.
  2. Avertir immédiatement Laurent au moindre incident.

## 2025-09-29T21:39+02:00 (refonte V2 – front & logs) - GPT (Codex CLI)
- **Objectif** : Démarrer concrètement la V2 en sécurisant l’état Git, en dupliquant l’UI et en initant l’espace de logs/tests.
- **Actions réalisées** :
  - `git status -sb` exécuté (branche `main`, nombreuses modifications existantes dont profil `.chrome-debug` et runs Playwright) ; `git fetch origin` OK mais aucun upstream détecté (`git pull --ff-only` impossible car `origin/main` absent).
  - Création de `maxicourses_front_v2/` avec copie de `maxicourses_test/pipeline/index2.html` ➜ nouveau `index.html` + duplication des assets.
  - Mise en place de `logs/refonte_v2/` et rédaction de `README.md` décrivant la structure des campagnes (commands.log, stdout/stderr, captures, notes horodatées Europe/Paris).
  - Commit local `315874e8a9cdd2623b7ec025c91fe47cdff6a5fa` : ajout du squelette `maxicourses_front_v2`, README de logs et mises à jour documentaires.
- **Données/artefacts ajoutés** :
  - maxicourses_front_v2/index.html
  - maxicourses_front_v2/assets/
  - logs/refonte_v2/ (README + arborescence `runs/`).
- **Blocages / alertes** :
  - Aucun upstream Git disponible (`origin/main` inexistant). Tentative `git push origin main` échouée (« could not read Username for https://github.com »). Besoin d’un accès/branche distante pour finaliser la sauvegarde.
- **Suivi / prochaines étapes** :
  1. Concevoir le nouveau formulaire triple recherche dans `maxicourses_front_v2/index.html` et le lier aux endpoints existants/à créer.
  2. Lancer la campagne de reproduction des bugs (Carrefour City sans résultat, prix identiques, seed « produit <EAN> ») en archivant chaque run dans `logs/refonte_v2/`.
