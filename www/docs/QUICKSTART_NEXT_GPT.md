# QUICKSTART – PROCHAINE SESSION GPT

Merci de lire attentivement ce mémo avant toute action. Chaque assistant doit compléter ou corriger ce document lorsque la situation évolue ; ajouter une section « Mise à jour <date> » en fin de fichier pour noter les changements.

## Message à copier-coller au prochain GPT

```
Avant toute action :
1. Lis les fichiers suivants dans cet ordre strict :
   - docs/PROMPT_BOOTSTRAP.md
   - docs/ONBOARDING.md
   - docs/GIT_SAUVEGARDE.md
   - docs/PARCOURS_HUMAIN.md
   - dernière entrée de docs/HANDOVER_DAILY.md
   - docs/PRICE_COLLECTION_GUIDE.md
   - docs/LECLERC_HUMAN_METHOD.md
   - docs/PRICE_COMPARATOR_PLAN.md
   - docs/README.md
   - docs/SESSION_TEMPLATE.md
   - docs/PROMPT_LOG.md
   - docs/REFONTE_FRONT_V2.md
2. Confirme que tu as lu/accepté toutes les consignes impératives définies dans docs/QUICKSTART_NEXT_GPT.md (sections « Consignes impératives » et « Points techniques actuels ») et cite les points clés (Chrome 9222 + USE_CDP, seed Carrefour City→Market→Auchan→Chronodrive, pas de requête "produit <EAN>", JSON complets, image locale, MAJ handover, scripts stables intouchables, fermeture des onglets Carrefour avant relance).
3. Mets à jour docs/QUICKSTART_NEXT_GPT.md en ajoutant une section « Mise à jour <date> » décrivant tes changements (ou « RAS »).
4. Utilise docs/SESSION_TEMPLATE.md pour rédiger ton entrée dans docs/HANDOVER_DAILY.md en fin de session.
```

## Lecture obligatoire (ordre strict)
- docs/PROMPT_BOOTSTRAP.md
- docs/ONBOARDING.md
- docs/PARCOURS_HUMAIN.md
- docs/HANDOVER_DAILY.md (dernière entrée)
- docs/PRICE_COLLECTION_GUIDE.md
- docs/LECLERC_HUMAN_METHOD.md
- docs/PRICE_COMPARATOR_PLAN.md
- docs/README.md
- docs/SESSION_TEMPLATE.md
- docs/PROMPT_LOG.md
- docs/REFONTE_FRONT_V2.md

## Consignes impératives
- Avant toute action, vérifier la configuration GitHub (cf. docs/GIT_SAUVEGARDE.md) : status propre, remote `origin`, `git pull --ff-only`.
- Horodater toutes les sauvegardes, journaux et entrées de handover en heure de Paris (Europe/Paris).
- Après chaque échange utilisateur/assistant, consigner le dialogue horodaté dans `docs/PROMPT_LOG.md`.
- Pour enrichir descriptif/Nutri-score/Eco-score, exploiter fr.openfoodfacts.org (version FR) sans remplacer les visuels issus des enseignes.
- Transparence obligatoire : signaler immédiatement toute difficulté ou retard à Laurent.
- Démarrer Chrome via `./start_chrome_debug.sh`, travailler avec `USE_CDP=1`; basculer `HEADLESS=0` uniquement pour les vérifications humaines.
- Recherche seed : Carrefour City → Carrefour Market → Auchan → Chronodrive. Arrêter si aucune enseigne seed ne retourne le produit.
- Collecte déclenchable par EAN ou descriptif (front index2.html + serveur) : toujours vérifier que le descriptif résout vers le bon EAN avant d’enchaîner.
- Enseignes sans recherche EAN (Leclerc, Intermarché, etc.) : utiliser le descriptif seed généré, jamais « produit <EAN> ».
- Aucune saisie manuelle : scripts seulement. Chaque résultat JSON doit inclure prix TTC, prix unitaire (€/kg ou €/L), quantité, magasin, note horodatée (Europe/Paris), URL, matched_ean.
- Image locale obligatoire dans `maxicourses_test/pipeline/assets/`, référencée dans `manual_descriptors.json`, afin que « Voir image » fonctionne dans `pipeline/index2.html`.
- Documenter chaque session dans `docs/HANDOVER_DAILY.md` avec preuves (captures, commandes). Utiliser `docs/SESSION_TEMPLATE.md`.
- Ne pas toucher aux scripts stables (Leclerc, Intermarché, Carrefour, Chronodrive) sans nouvelle trace validée par Laurent.
- Avant de relancer la pipeline ou l’API, fermer les onglets Carrefour encore ouverts ou redémarrer Chrome 9222.
- Pour chaque run, générer et archiver les traces (captures, stdout/stderr) puis consigner les actions dans docs/HANDOVER_DAILY.md en suivant le plan de refonte V2.

## Points techniques actuels
- Normalisation des requêtes/descripteurs centralisée dans `maxicourses_test/pipeline/run_pipeline.py` (`sanitize_query`, `sanitize_descriptor_entry`) et `maxicourses_test/server.py`.
- Si Carrefour City ne trouve pas immédiatement l’EAN, basculer sans boucle vers Market, puis Auchan, puis Chronodrive.
- Ajouter l’EAN dans `EXTRA_DATASETS` si la nouvelle fiche doit apparaître dans `pipeline/index2.html`.
- Vérifier que `manual_descriptors.json` contient une entrée propre avant de lancer Leclerc/Intermarché ; l’API crée un stub assaini si besoin.
- La refonte front se déroule dans `maxicourses_front_v2/` (aperçu local : `http://localhost:8000/maxicourses_front_v2/index.html`).
- Les campagnes de tests doivent archiver leurs traces dans `logs/refonte_v2/` (structure détaillée dans `logs/refonte_v2/README.md`).

## À faire par chaque nouveau GPT
- Confirmer que ce document reste à jour ; ajouter en fin de fichier une section « Mise à jour <date> » décrivant vos modifications, ou indiquer « RAS » si rien n’a changé.
- Signaler dans `docs/HANDOVER_DAILY.md` toute décision importante (scripts modifiés, nouvelles traces, erreurs rencontrées).

## Mise à jour 2025-09-27
- Création initiale du mémo.

## Mise à jour 2025-09-28
- Relecture complète des consignes impératives et confirmation qu'elles couvrent Chrome 9222 + USE_CDP, ordre seed Carrefour City→Market→Auchan→Chronodrive, absence de requêtes « produit <EAN> », sorties JSON complètes avec images locales et mise à jour du handover.

## Mise à jour 2025-09-28 (Codex CLI)
- RAS sur le contenu : relecture des consignes impératives (Chrome 9222 + USE_CDP, seed Carrefour City→Market→Auchan→Chronodrive, interdiction requête "produit <EAN>", JSON complets + image locale, MAJ handover).
- Handover du jour mis à jour dans `docs/HANDOVER_DAILY.md` via `docs/SESSION_TEMPLATE.md`.

## Mise à jour 2025-09-28 (Refonte V2)
- Création de `docs/REFONTE_FRONT_V2.md` pour documenter la nouvelle interface et le protocole de tests/logs. Toute modification doit être tracée au fil de l'eau.

## Mise à jour 2025-09-28 (Sauvegarde GitHub)
- Ajout de `docs/GIT_SAUVEGARDE.md` et rappel de valider la configuration Git avant toute nouvelle tâche.

## Mise à jour 2025-09-28 (Journal des prompts)
- Création de `docs/PROMPT_LOG.md` et obligation de tracer chaque échange avec horodatage Europe/Paris.

## Mise à jour 2025-09-29 (Horodatage Europe/Paris)
- Ajout de la consigne d’horodater toutes les sauvegardes et journaux en heure de Paris (Europe/Paris).

## Mise à jour 2025-09-29 (Open Food Facts)
- Autorisation explicite d’utiliser fr.openfoodfacts.org pour enrichir les fiches (descriptif, Nutri-score, Green-score), tout en conservant les visuels des enseignes.

## Mise à jour 2025-09-29 (Transparence)
- Rappel explicite : signaler à Laurent tout blocage ou retard sans délai.

## Mise à jour 2025-09-29T21:39+02:00 (Refonte V2)
- Création de `maxicourses_front_v2/` (copie de l’UI actuelle) et mise en place de `logs/refonte_v2/` avec gabarit de rapport.

## Mise à jour 2025-09-29T19:49+02:00 (Codex CLI)
- Lecture complète des documents obligatoires ; consignes confirmées, pas d'autre modification de fond.
