# Leclerc Drive (Bruges) – Méthode CDP humaine

## Objectif
Assurer le relevé de prix Leclerc Drive Bruges malgré Datadome en reproduisant un parcours humain complet sur Chrome remote (port 9222).

## Pré-requis
- Chrome lancé via `maxicourses_test/start_chrome_debug.sh` (profil `.chrome-debug`).
- Magasin cible : Bruges (`magasin-173301-173301-bruges`).
- Traces humaines conservées dans `traces/` (nouvelle trace `leclerc-20250924-coca175.jsonl` recommandée).
- Script d’assistance : `maxicourses_test/manual_leclerc_cdp.py` (se connecte via CDP et tape la recherche comme un humain).

## Procédure standard
1. **Seed descriptif (obligatoire)**
   - Interroger d’abord Carrefour (Chrome 9222). Si la fiche n’existe pas, basculer sur Auchan.
   - Conserver le libellé exact (titre + grammage) issu de l’enseigne seed.
   - Documenter dans le résultat JSON la source (`"source": "carrefour"` ou `"auchan"`).
2. **Initialisation**
   - Lancer Chrome remote :
     ```bash
     cd maxicourses_test
     ./start_chrome_debug.sh
     ```
   - (Optionnel) Rejouer la trace de sélection magasin si doute :
     ```bash
     cd maxicourses_test
     python3 replay_leclerc_navigation.py ../traces/leclerc-20250924-coca175.jsonl --speed 0.7
     ```
3. **Recherche humaine automatisée**
   - Option CLI direct :
     ```bash
     cd maxicourses_test
     USE_CDP=1 CDP_URL="http://127.0.0.1:9222" \
     STORE_URL="https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx" \
     EAN=5000112611861 QUERY="Coca Cola 1,75 L" \
     LECLERC_HUMAN_DELAY_MS=5000 LECLERC_RESULT_DELAY_MS=12000 LECLERC_PDP_DELAY_MS=7000 \
     python3 manual_leclerc_cdp.py
     ```
   - Variante fetch Playwright :
     ```bash
     cd maxicourses_test
     USE_CDP=1 QUERY="Dessert vegetal soja amande 500 g" EAN=5411188118961 \
       python3 fetch_leclerc_drive_price.py
     ```
   - Les scripts :
     - attend ~5 s sur l’accueil (bandeau Bruges visible),
     - clique sur « Accepter » OneTrust si présent,
     - tape `QUERY` caractère par caractère avec délai humain,
     - attend le chargement résultats (~12 s) puis clique sur la première vignette,
     - récupère prix (`2,38 €` constaté le 24/09/2025), prix/L (`1,36 € / L`), titre, URL.
   - Sortie JSON écrite sur stdout (à injecter dans `results/test-<EAN>` et `results/summary.json`).
4. **Post-traitement**
   - Mettre à jour `maxicourses_test/results/test-5000112611861/latest.json` et `summary.json`.
   - Propager dans `maxicourses_test/results/summary.json` pour alimenter `pipeline/index2.html`.
   - Capturer toute anomalie (Datadome, cookies) et noter dans `docs/HANDOVER_DAILY.md`.

## Consignes ton / relation utilisateur
- Respecter strictement les instructions de Laurent (l’utilisateur) sans familiarités ni commentaires inutiles.
- Répondre sur un ton professionnel, concis, orienté exécution.
- Ne jamais déléguer l’action manuelle de relevé : le script ci-dessus est l’outil autorisé.

## Fichiers liés
- Trace humaine : `traces/leclerc-20250924-coca175.jsonl` (sélection drive + recherche + ouverture fiche).
- Script : `maxicourses_test/manual_leclerc_cdp.py`.
- Résultat du 24/09/2025 : `maxicourses_test/results/test-5000112611861/latest.json` + `summary.json`.

Maintenir cette méthode tant que Leclerc bloque les fetchers classiques. Toute variation (nouveau magasin, changement DOM) doit faire l’objet d’une nouvelle trace + mise à jour documentaire.
