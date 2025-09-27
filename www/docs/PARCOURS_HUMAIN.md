# Parcours Humain (Anti-bot)

## Objectif
Certaines enseignes (Leclerc, Intermarché, Auchan…) déclenchent rapidement des protections anti-bot. Pour contourner ces blocages, on capture un **parcours entièrement humain** depuis Chrome 9222, puis on le rejoue / on s’en inspire pour les scripts Playwright. Le but est de ne pas refaire manuellement chaque relevé mais de rejouer fidèlement les actions validées par un humain.

## Pré-requis
- Chrome lancé via `maxicourses_test/start_chrome_debug.sh` (port 9222).
- Un onglet ouvert sur l’enseigne cible (profil `.chrome-debug`).
- Playwright accessible dans l’environnement (`maxicourses_test/.venv` si besoin).

## Enregistrement (script `record_leclerc_navigation.py`)
Lors de chaque session, c'est l'utilisateur qui lance l'enregistreur et qui le stoppe manuellement (création du fichier `--stop-flag` ou touche Entrée). Le GPT se contente de fournir les commandes prêtes à copier/coller et attend le signal de fin avant d'exploiter la trace.

1. Lancer Chrome remote :
   ```bash
   cd maxicourses_test
   ./start_chrome_debug.sh
   ```
2. Ouvrir l’onglet cible dans ce Chrome (ex. https://www.intermarche.com/accueil). Valider cookies / magasin manuellement une première fois.
3. En console :
   ```bash
   cd maxicourses_test
   python3 record_leclerc_navigation.py \
     --url "https://www.intermarche.com/accueil" \
     --out ../traces/intermarche-20240922.jsonl
   ```
   - L’outil se connecte au Chrome existant et injecte un script de capture.
   - Chaque clic, saisie clavier, scroll, navigation est horodaté.
   - Pour fermer l’enregistrement : `Ctrl+C` ou créer le fichier `--stop-flag` si option utilisée.
4. Vérifier que le fichier `traces/*.jsonl` est présent et lisible.

### Bonnes pratiques de capture
- Noter les objectifs avant de commencer (ex. “Bruges → recherche Coca 1,75 L → ouvrir fiche → attendre refresh”).
- Inclure les délais humains (pause 1 à 2 s si besoin). Playwright respectera ces durées au replay.
- Garder un unique onglet pour éviter la capture de bruits inutiles.
- Nommer le fichier `traces/<enseigne>-<YYYYMMDD>-<mot-cle>.jsonl` pour retrouver facilement.

## Relecture / validation (`replay_leclerc_navigation.py`)
1. Relancer Chrome 9222 si besoin.
2. Rejouer :
   ```bash
   cd maxicourses_test
   python3 replay_leclerc_navigation.py \
     traces/intermarche-20240922.jsonl
   ```
   - Utiliser `--speed` pour ralentir/accélérer (défaut 1.0).
   - Vérifier que la fiche affichée est bien atteinte sans blocage et que l’EAN attendu apparaît.

## Exploitation dans les scrapers
- Les traces servent de **documentation vivante** : même si le fetcher reste automatisé, on sait comment contourner les anti-bots (ordres de clic, champs à remplir, délais).
- Les scripts Playwright (ex. `fetch_leclerc_drive_price.py`, `fetch_intermarche_price.py`) peuvent intégrer ces étapes (
  réouverture du magasin, `wait_for_timeout`, champs spécifiques) en s’inspirant de la trace.
- Conserver les traces dans `traces/` et référencer la date/le fichier dans `docs/HANDOVER_DAILY.md`.

## À transmettre au prochain GPT/Codex
1. Lire ce document + les traces existantes (`traces/*.jsonl`).
2. Avant d’ajouter une nouvelle enseigne sensible : enregistrer le parcours humain complet.
3. Si le site change : refaire un enregistrement, l’archiver (ancienne trace `traces/archive/…` si besoin) et documenter.
4. Lors des relevés :
   - Lancer le script fetch.
   - Si l’enseigne se re-bloque, rejouer la trace pour vérifier, adapter le fetcher, puis relancer.
5. Toute nouvelle trace ou adaptation doit être mentionnée dans `docs/HANDOVER_DAILY.md` (date + chemin du fichier).

Ces consignes garantissent que les prochains GPT/Codex disposent d’un mode opératoire clair et réutilisable sans repartir de zéro.


Avant toute capture Carrefour, vérifier visuellement le bandeau de magasin (`City ...` / `Market ...`). Si nécessaire, utiliser le bouton « Changer de Drive » avant de lancer l'enregistreur ou le fetch.

Toutes les valeurs utilisées dans le comparateur doivent provenir des captures automatisées (trace + fetch). Pas de saisie manuelle dans les JSON.