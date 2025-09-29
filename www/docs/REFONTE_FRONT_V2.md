
# Plan de refonte front MaxiCourses V2

## Objectif général
Construire une interface propre (V2) permettant trois modes de recherche (EAN saisi, photo du code-barres, descriptif libre), tout en conservant l’affichage actuel validé pour les démos et en améliorant la fiabilité de la collecte.

## Principes immuables
- Transparence garantie : tout obstacle ou retard est immédiatement signalé à Laurent.
- Les données descriptives (Nutri-score, Green-score, labels) peuvent être enrichies via fr.openfoodfacts.org ; les visuels restent issus des enseignes comparées.
- Tous les scripts de collecte restent obligatoirement en mode Chrome 9222 (`USE_CDP=1`).
- Le descriptif "canonique" (titre, quantité, Nutri-score, image locale) est figé après une collecte seed réussie et n’est mis à jour qu’à la prochaine collecte seed.
- Chaque run (succès ou échec) doit produire des traces (captures, stdout/stderr, horodatage) et être consigné dans `docs/HANDOVER_DAILY.md`.
- Aucune modification de styles ou layout existants tant que le nouveau front V2 n’est pas prêt à remplacer la page actuelle.
- Avant toute refonte ou test, exécuter la checklist GitHub (docs/GIT_SAUVEGARDE.md) pour garantir la possibilité de rollback.
- Tous les horodatages (logs, handover, captures) sont renseignés en heure de Paris (Europe/Paris).

## Pistes de travail
1. **Inventaire**
   - [ ] Dresser la liste des composants UI à conserver (cartes produits, section comparateur) et des scripts stables.
   - [ ] Cataloguer les comportements défaillants (recherche Carrefour City sans résultat, prix identiques City/Leclerc, etc.).
2. **Nouvelle base front**
   - [x] Créer `maxicourses_front_v2/` et y copier les éléments sains (`index2.html` layout, CSS, actifs). ➜ dossier initial créé (copie de `pipeline/index2.html` + assets) le 2025-09-29T21:39+02:00.
   - [ ] Conception d’un formulaire unique regroupant : saisie EAN, upload photo, champ descriptif.
   - [ ] Brancher le formulaire sur les endpoints backend (`/api/collect` + service de décodage image à créer).
3. **Pipeline & scripts**
   - [ ] Supprimer les valeurs EAN par défaut dans les fetchers ; refuser une collecte sans EAN réel.
   - [ ] Permettre la collecte seed à partir d’un descriptif et sécuriser l’enchaînement City → Market → Auchan → Chronodrive.
   - [ ] Télécharger l’image produit dès la première seed validée et la sauvegarder localement.
   - [ ] Intégrer la récupération optionnelle des métadonnées (Nutri-score, Green-score, labels) via fr.openfoodfacts.org lors de la phase seed, sans remplacer les visuels locaux.
4. **Infrastructure de test**
   - [x] Mettre en place un dossier `logs/refonte_v2/` pour stocker : 
       - commandes exécutées,
       - captures (PNG/HTML),
       - sorties `stdout`/`stderr`,
       - résumé horodaté de chaque tentative.
   - [x] Écrire un gabarit de rapport pour chaque campagne de test. ➜ `logs/refonte_v2/README.md` décrit la structure (commands.log, stdout/stderr, captures, notes horodatées Europe/Paris).
5. **Corrections itératives**
   - [ ] Planifier des scénarios de test (ex. "Carrefour City sans résultat", "Leclerc indisponible", "Chronodrive timeout").
  - [ ] Corriger les seeders qui envoient "produit <EAN>" : sur les enseignes compatibles EAN (Carrefour, Auchan, Chronodrive) la requête doit être l’EAN brut.
   - [ ] Pour chaque bug : reproduire → corriger → relancer → documenter.
6. **Documentation**
   - [ ] Mettre à jour `docs/QUICKSTART_NEXT_GPT.md` pour pointer vers ce plan.
   - [ ] Ajouter un chapitre dans `docs/PRICE_COLLECTION_GUIDE.md` une fois les nouveaux flux validés.
   - [ ] Documenter la procédure de décodage d’image (photo → EAN) dès qu’elle est opérationnelle.

## Statut initial (2025-09-28)
- Nouveau document créé pour tracer la refonte V2.
- Étapes suivantes :
  1. Cloner l’UI dans `maxicourses_front_v2/`.
  2. Démarrer la collecte de logs/tests ciblés.
  3. Mettre à jour QUICKSTART + HANDOVER à chaque jalon.
