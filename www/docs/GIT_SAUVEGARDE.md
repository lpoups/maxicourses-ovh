# Checklist sauvegarde Git (Europe/Paris)

## Préparation avant toute intervention
1. Noter l’heure de contrôle (Europe/Paris) dans vos notes internes.
2. Exécuter `git status -sb` et vérifier qu’aucun fichier inattendu n’est modifié.
3. Vérifier les remotes avec `git remote -v` : `origin` doit pointer vers le dépôt GitHub officiel.
4. Si nécessaire, synchroniser : `git pull --ff-only origin main`.
5. Confirmer que vous travaillez bien sur la branche attendue (par défaut `main`).

## Pendant les modifications
1. Éviter de toucher aux fichiers marqués sensibles par Laurent (scripts fetch stables, captures historiques) sans accord.
2. Documenter localement les commandes et horodatages (Europe/Paris) pour intégration dans `logs/refonte_v2/` si des tests sont lancés.
3. Garder un œil sur `git status` afin d’identifier immédiatement tout fichier généré par erreur (cache, profil Chrome, etc.).

## Avant toute sauvegarde / remise
1. Relire `git status -sb` : seuls les fichiers concernés par la tâche doivent apparaître.
2. Mettre à jour `docs/HANDOVER_DAILY.md` et `docs/PROMPT_LOG.md` avec l’heure Europe/Paris.
3. Lister les commandes clés et résultats dans les notes de session (ou `logs/refonte_v2/runs/<horodatage>`).
4. Ne PAS lancer `git add`/`git commit`/`git push` sans validation explicite de Laurent.
5. Si une sauvegarde Git est autorisée, respecter l’ordre :
   - `git add <fichiers>`
   - `git status -sb` (contrôle final)
   - `git commit -m "..."` (message concis)
   - `git push origin <branche>`
   - Noter l’horaire du push (Europe/Paris) dans le handover.

## Nettoyage recommandé après validation
1. Supprimer les artefacts temporaires (profils Chrome, caches Playwright, dossiers `runs/` inutiles) uniquement si Laurent l’a confirmé.
2. Repasser un `git status -sb` pour garantir un arbre propre avant la prochaine session.
3. Fermer la session en consignant les décisions ou anomalies dans `docs/HANDOVER_DAILY.md`.
