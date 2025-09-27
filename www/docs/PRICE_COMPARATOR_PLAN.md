# Plan comparateur de prix intelligent

## Objectif
Créer un moteur capable d’agréger automatiquement les prix multi-enseignes (Carrefour, Leclerc Drive, etc.), de normaliser les produits et de restituer les meilleures offres (ex. prix/kg minimal) avec preuve visuelle.

## État actuel
- Scripts Playwright fonctionnels pour Carrefour, Leclerc Drive, Auchan, Intermarché, Chronodrive.
- Contraintes strictes Leclerc Drive documentées dans `fetch_leclerc_drive_price.py` et `~/.codex/config.toml` (Chrome 9222 obligatoire, validation visuelle).
- Collected dataset d’exemple sur le ketchup Heinz (Carrefour + Leclerc) avec calculs prix/kg (voir `docs/HANDOVER_DAILY.md` et captures dans `maxicourses_test/debug_screens/`).

## Prochaines étapes (priorisées)
1. **Stockage structuré**
   - [ ] Concevoir schéma PostgreSQL (tables `products`, `observations`, `sources`, `assets`).
   - [ ] Écrire script d’ingestion (Python) qui prend la sortie JSON des fetchers et alimente la base.
2. **Normalisation produit**
   - [ ] Définir pipeline de matching : EAN > titre nettoyé > fallback heuristique (poids, marque).
   - [ ] Ajouter un module d’enrichissement poids/volume + calcul auto du prix unitaire.
3. **API/CLI**
   - [ ] Prototyper un CLI `compare_prices.py` retournant les offres triées par prix/kg.
   - [ ] Spécifier endpoints REST/GraphQL à exposer ensuite.
4. **Surveillance & preuves**
   - [ ] Formaliser stockage des captures (chemin + hash) et lien dans la base.
   - [ ] Mettre en place alerte lorsque le statut `CF_BLOCK`/`NO_RESULTS` persiste.

## Rôles du prochain assistant
- Poursuivre la conception de la base et du script d’ingestion.
- Renforcer la documentation si un nouvel opérateur est ajouté.
- Documenter chaque run bloquant dans `HANDOVER_DAILY.md`.

## Ressources utiles
- `maxicourses_test/fetch_*_price.py` : logique actuelle pour chaque enseigne.
- `maxicourses_test/state/` : états Playwright, à réutiliser plutôt que relancer des connexions.
- `docs/PROMPT_BOOTSTRAP.md` : rappel à intégrer dans les prompts initial.
