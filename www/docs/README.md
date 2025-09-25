# Dossier `docs/`

Ce répertoire regroupe les fichiers persistants à relire par chaque nouvel assistant GPT.

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
- `maxicourses_test/manual_descriptors.json` : attributs produit statiques utilisés pour alimenter l’en-tête (titre, Nutri-score, image locale).
- `maxicourses_test/fetch_leclerc_drive_price.py` : simple wrapper qui appelle `manual_leclerc_cdp.py` (méthode humaine unique supportée).

## Bonnes pratiques
- **Versionner** chaque évolution documentaire (pas d’édition locale hors Git).
- **Datation** : toute entrée `HANDOVER_DAILY` doit commencer par `## YYYY-MM-DD - Auteur`.
- **Liens** : préférer les chemins relatifs ou URL complètes publiques des enseignes.

## Processus Conseillé à Chaque Relève
- `pipeline/index2.html` : la fiche principale charge l’EAN 3124480200433 (Orangina) via `results/summary.json`. Les comparatifs additionnels sont décrits dans `EXTRA_DATASETS`. Ajouter un produit = générer `results/test-<EAN>/{latest,summary}.json`, compléter `manual_descriptors.json`, puis ajouter l’entrée dans `EXTRA_DATASETS`.
1. Lire le dernier bloc dans `HANDOVER_DAILY.md`.
2. Mettre à jour la section "Tâches en cours" ou créer une nouvelle entrée si les priorités changent.
3. Compléter `PROMPT_BOOTSTRAP.md` si de nouvelles consignes doivent être rappelées systématiquement.

### Rafraîchir la page `index2.html`
1. Lancer les fetchs Playwright (Carrefour, Leclerc, etc.) avec `USE_CDP=1 HEADLESS=0` pour mettre à jour `results/latest.json` et `results/test-<EAN>/`.
2. Ajuster `manual_descriptors.json` uniquement si le descriptif produit change (visuel local dans `maxicourses_test/pipeline/assets/` recommandé).
3. Tester localement : `cd maxicourses_test && python3 -m http.server`, puis ouvrir `http://localhost:8000/pipeline/index2.html`.
4. Capturer les éventuels nouveaux parcours humains dans `traces/` et consigner le tout dans `docs/HANDOVER_DAILY.md`.

Ce dossier remplace la mémoire persistante : à maintenir avec rigueur.
