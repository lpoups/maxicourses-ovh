# Dossier `docs/`

Ce répertoire regroupe les fichiers persistants à relire par chaque nouvel assistant GPT.

## Vision MaxiCourses
- Comparateur de prix multi-enseignes (Carrefour City/Market, Leclerc Drive, Auchan, Chronodrive, Intermarché) avec preuves (captures, JSON).
- Triple mode de recherche : \* EAN brut (seed depuis fr.openfoodfacts.org), \* descriptif libre (marque + type/goût + contenance), \* upload photo (décodage code-barres → EAN).
- Les visuels de produits restent ceux des enseignes ; OpenFoodFacts sert uniquement au descriptif, Nutri-score, Green/Eco-score et méta-données.
- Les informations produits (titre, quantity, image locale, scores) sont figées après une seed réussie et ne changent qu’à la prochaine collecte volontaire.
- Objectif court terme : pipeline de collecte stable pour les démos investisseurs, puis refonte front V2 offrant les trois parcours.

## Fichiers à connaître
- `ONBOARDING.md` : vision globale, règles d’or, scripts critiques.
- `PRICE_COMPARATOR_PLAN.md` : roadmap technique pour construire le comparateur intelligent.
- `PRICE_COLLECTION_GUIDE.md` : mode opératoire par enseigne (scripts, traces, règles).
- `HANDOVER_DAILY.md` : journal de relève (ajouter une section par session de travail).
- `SESSION_TEMPLATE.md` : gabarit pour prise de notes (à copier-coller dans `HANDOVER_DAILY.md`).
- `PROMPT_BOOTSTRAP.md` : éléments à injecter dans le prompt initial du prochain GPT.
- `PARCOURS_HUMAIN.md` : procédure détaillée pour enregistrer/rejouer un parcours humain anti-bot.
- `LECLERC_HUMAN_METHOD.md` : workflow spécifique pour Leclerc Drive (Bruges) en mode CDP humain.
- `maxicourses_test/pipeline/index2.html` : page de démonstration (copie du layout historique) branchée sur les résultats JSON.
- `maxicourses_test/seed_catalog.py` : catalogue seed codé en dur (titre, quantité, visuel local, requêtes par enseigne) consommé via `descriptor_store.py`.
- `maxicourses_test/fetch_leclerc_drive_price.py` : simple wrapper qui appelle `manual_leclerc_cdp.py` (méthode humaine unique supportée).
- `maxicourses_test/fetch_monoprix_price.py` : collecte Monoprix via recherche textuelle (pas de support EAN).
- `maxicourses_test/fetch_courseu_price.py` : collecte Course U (Super U Eysines) par recherche EAN directe (session Chrome 9222 validée, overlay promo fermé, state sauvegardée). Le script mémorise l’URL PDP `courseu_url` dans `seed_catalog.py` pour limiter les reblocs Cloudflare lors des runs suivants.
- `maxicourses_test/ai_helpers.py` + `run_ai_pipeline.py` : génèrent via OpenAI les requêtes ≤30 caractères pour Leclerc/Monoprix/Intermarché à partir des seeds EAN.

## Bonnes pratiques
- **Versionner** chaque évolution documentaire (pas d’édition locale hors Git).
- **Datation** : toute entrée `HANDOVER_DAILY` doit commencer par `## YYYY-MM-DD - Auteur`.
- **Liens** : préférer les chemins relatifs ou URL complètes publiques des enseignes.

## Processus Conseillé à Chaque Relève
- `pipeline/index2.html` : la fiche principale charge l’EAN 3124480200433 (Orangina) via `results/summary.json`. Les comparatifs additionnels sont décrits dans `EXTRA_DATASETS`. Ajouter un produit = générer `results/test-<EAN>/{latest,summary}.json`, compléter `seed_catalog.py`, puis ajouter l’entrée dans `EXTRA_DATASETS`.
1. Lire le dernier bloc dans `HANDOVER_DAILY.md`.
2. Mettre à jour la section "Tâches en cours" ou créer une nouvelle entrée si les priorités changent.
3. Compléter `PROMPT_BOOTSTRAP.md` si de nouvelles consignes doivent être rappelées systématiquement.

### Rafraîchir la page `index2.html`
1. Lancer les fetchs Playwright (Carrefour, Leclerc, etc.) avec `USE_CDP=1 HEADLESS=0` pour mettre à jour `results/latest.json` et `results/test-<EAN>/`.
2. Ajuster `seed_catalog.py` uniquement si le descriptif produit change (visuel local dans `maxicourses_test/pipeline/assets/` recommandé).
3. Tester localement : `cd maxicourses_test && python3 -m http.server`, puis ouvrir `http://localhost:8000/pipeline/index2.html`.
4. Capturer les éventuels nouveaux parcours humains dans `traces/` et consigner le tout dans `docs/HANDOVER_DAILY.md`.

Ce dossier remplace la mémoire persistante : à maintenir avec rigueur.
