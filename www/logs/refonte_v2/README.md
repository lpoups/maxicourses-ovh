# Logs refonte front V2

Chaque test (collecte, UI) doit créer un sous-dossier dans `runs/` :

- `YYYYMMDD-HHMMSS-<slug>/commands.log` : commandes exécutées + retour.
- `captures/` : captures d'écran PNG ou extraits HTML.
- `stdout.log` / `stderr.log` : sorties brutes des scripts.
- `notes.md` : résumé (objectif, résultat, anomalies) horodaté Europe/Paris.

N'oublie pas de référencer le sous-dossier correspondant dans `docs/HANDOVER_DAILY.md`.
