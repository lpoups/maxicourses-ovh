# Plan comparateur de prix intelligent

## Objectif
Créer un moteur capable d’agréger automatiquement les prix multi-enseignes (Carrefour, Leclerc Drive, etc.), de normaliser les produits et de restituer les meilleures offres (ex. prix/kg minimal) avec preuve visuelle.

## État actuel
- Scripts Playwright fonctionnels pour Carrefour, Leclerc Drive, Auchan, Intermarché, Chronodrive et Course U (Super U Eysines).
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
   - [ ] Finaliser l’enseigne Carrefour Super : rejouer un parcours humain (Chrome 9222) pour capturer `facilityServiceId` / `FRONTAL_STORE` propres à Lormont (sélection « Lormont, Gironde, France »), mettre à jour `state/carrefour_super.json` et vérifier l’affichage « Super » côté UI (`pipeline/index2.html`).
   - [x] Monoprix : validation renforcée sur couverture ≥ 70 % des tokens seed + hash image multi-sources (voir `seed_catalog.py` → `canonical.images`). Option `allow_monoprix_squeeze` débloque les conditionnements légitimes ; run de contrôle `3088545004001` validé (fiche « Lune de Miel Squeeze 500g »).

## Rôles du prochain assistant
- Poursuivre la conception de la base et du script d’ingestion.
- Renforcer la documentation si un nouvel opérateur est ajouté.
- Documenter chaque run bloquant dans `HANDOVER_DAILY.md`.

## Ressources utiles
- `maxicourses_test/fetch_*_price.py` : logique actuelle pour chaque enseigne.
- `maxicourses_test/state/` : états Playwright, à réutiliser plutôt que relancer des connexions.
- `docs/PROMPT_BOOTSTRAP.md` : rappel à intégrer dans les prompts initial.

## ToDo évolution Maxicourses
- Mettre en place une base de connaissances (LLM interne) consignant erreurs à éviter et bonnes pratiques de collecte pour guider les prochaines itérations.
- Construire un moteur de recommandations produits équivalents : comparer qualité, valeur nutritive et prix pour proposer des alternatives moins chères à partir des données multi-enseignes.
- Intégrer la prise en compte des promotions/cartes de fidélité : calculer automatiquement le prix réel selon les remises actives.
- Automatiser la collecte des catalogues promo (PDF) de chaque enseigne, ingestion sur le serveur OVH et indexation dans la base.
- Développer un assistant courses personnalisé (objectifs minceur, prise de masse, vegan, etc.) tenant compte du nombre de personnes, de la durée et des habitudes sport/nutrition.
