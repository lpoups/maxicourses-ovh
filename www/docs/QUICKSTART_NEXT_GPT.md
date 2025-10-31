# QUICKSTART – PROCHAINE SESSION GPT

Merci de lire attentivement ce mémo avant toute action. Chaque assistant doit compléter ou corriger ce document lorsque la situation évolue ; ajouter une section « Mise à jour <date> » en fin de fichier pour noter les changements.

## Vision rapide
- Projet : comparateur de prix grande distribution (Carrefour City/Market, Leclerc, Auchan, Chronodrive, Intermarché) avec preuve visuelle et JSON complet.
- Modes de recherche à maintenir : EAN brut (seed OpenFoodFacts), descriptif libre (marque + type/goût + contenance), upload photo (décodage code-barres).
- Les visuels proviennent toujours des enseignes ; OpenFoodFacts ne fournit que le descriptif/Nutri-score/Green-score.
- Les données produits sont figées après une seed réussie et ne changent qu’à la prochaine collecte volontaire.

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
- Dès qu’un composant long-lived est modifié (API Flask `server.py`, pipeline, fetchers…), **tu stoppes et relances toi-même** les services concernés (kill process + redémarrage) avant de rendre la main ; ne jamais repousser cette étape sur Laurent.
- **Gel fetchers existants** : ne **modifie JAMAIS** les scripts `fetch_*.py` suivants (ni leurs modules auxiliaires) sans ordre explicite de Laurent : Carrefour Market, Carrefour City, Auchan, Chronodrive, CourseU, Intermarché, Leclerc, Monoprix. Toute évolution doit se limiter à `fetch_carrefour_price_super.py` tant que Laurent n’a pas levé ce gel.
- Démarrer Chrome via `./start_chrome_debug.sh`, travailler avec `USE_CDP=1`; basculer `HEADLESS=0` uniquement pour les vérifications humaines.
- Recherche seed : Carrefour Market → Carrefour City → Auchan → Chronodrive → Intermarché → Monoprix → Leclerc (les quatre premiers en EAN brut, Intermarché/Monoprix/Leclerc exploitent le descriptif enrichi). Arrêter si aucune enseigne seed ne retourne le produit.
- Pour Carrefour City/Market, Auchan et Chronodrive : la requête doit être l’EAN brut. Les wrappers City/Market injectent `FRONTAL_STORE` (`800041` / `1911`) pour verrouiller le drive ; adapter la valeur si un autre magasin est requis.
- Auchan Talence-Gallieni est préchargé via `state/auchan.json` (`storeReference.id = 6117`). Si vous changez de drive, regénérez ce state (Chrome 9222) avant de relancer.
- Collecte déclenchable par EAN ou descriptif (front index2.html + serveur) : toujours vérifier que le descriptif résout vers le bon EAN avant d’enchaîner.
- Enseignes sans recherche EAN (Leclerc, Intermarché, etc.) : utiliser le descriptif seed généré, jamais « produit <EAN> ».
- Aucune saisie manuelle : scripts seulement. Chaque résultat JSON doit inclure prix TTC, prix unitaire (€/kg ou €/L), quantité, magasin, note horodatée (Europe/Paris), URL, matched_ean.
- Image locale obligatoire dans `maxicourses_test/pipeline/assets/`, référencée dans `manual_descriptors.json`, afin que « Voir image » fonctionne dans `pipeline/index2.html`.
- Priorité immédiate : stabiliser les fetchers Carrefour City/Market, Auchan, Chronodrive, Intermarché, Monoprix et Leclerc Drive pour les démonstrations (collecte complète + traces archivées).
- Toute collecte seed doit produire un descriptif complet : marque en premier, titre descriptif, quantité, Nutri-score (badge local) et visuel enseigne téléchargé dans `maxicourses_test/pipeline/assets/`.
- Documenter chaque session dans `docs/HANDOVER_DAILY.md` avec preuves (captures, commandes). Utiliser `docs/SESSION_TEMPLATE.md`.
- Ne pas toucher aux scripts stables (Leclerc, Intermarché, Carrefour, Chronodrive) sans nouvelle trace validée par Laurent.
- Avant de relancer la pipeline ou l’API, fermer les onglets Carrefour encore ouverts ou redémarrer Chrome 9222.
- Pour chaque run, générer et archiver les traces (captures, stdout/stderr) puis consigner les actions dans docs/HANDOVER_DAILY.md en suivant le plan de refonte V2.
- Adopter une posture proactive : raisonner, challenger les anomalies et proposer les correctifs (ne jamais se contenter d’appliquer un patch sans comprendre l’impact métier).
- Lors de l’upload d’une photo, afficher l’EAN détecté (13 chiffres obligatoires) et attendre la validation explicite avant de lancer la collecte ; investiguer immédiatement toute lecture partielle (`decode_image_to_ean` trace les candidats rejetés).

## Points techniques actuels
- Normalisation des requêtes/descripteurs assurée dans `maxicourses_test/pipeline/run_pipeline.py` (construction du seed via `descriptor_from_payload`/`build_search_query`) et dans `maxicourses_test/server.py`.
- Si Carrefour City ne trouve pas immédiatement l’EAN, basculer sans boucle vers Market, puis Auchan, puis Chronodrive.
- Ajouter l’EAN dans `EXTRA_DATASETS` si la nouvelle fiche doit apparaître dans `pipeline/index2.html`.
- Vérifier que `manual_descriptors.json` contient une entrée propre avant de lancer Leclerc/Intermarché ; l’API crée un stub assaini si besoin.
- La refonte front se déroule dans `maxicourses_front_v2/` (aperçu local : `http://localhost:8000/maxicourses_front_v2/index.html`).
- Les campagnes de tests doivent archiver leurs traces dans `logs/refonte_v2/` (structure détaillée dans `logs/refonte_v2/README.md`).
- Servir V1/V2 avec `python3 -m http.server 8000` lancé depuis `www/` (changer de port uniquement si un autre serveur est actif).

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

## Mise à jour 2025-09-29T21:39 (Refonte V2, Europe/Paris)
- Création de `maxicourses_front_v2/` (copie de l’UI actuelle) et mise en place de `logs/refonte_v2/` avec gabarit de rapport.

## Mise à jour 2025-09-29T19:49 (Codex CLI, Europe/Paris)
- Lecture complète des documents obligatoires ; consignes confirmées, pas d'autre modification de fond.

## Mise à jour 2025-09-29T23:15 (Transit V2, Europe/Paris)

- **Consignes renforcées** :
  - Consulter en début de session la section "POC Démo – Checklist express" dans `docs/HANDOVER_DAILY.md` pour connaître les tâches critiques.
  - Lire dans l’ordre docs/PROMPT_BOOTSTRAP.md → docs/REFONTE_FRONT_V2.md avant toute action.
  - Priorité : collecte stable Carrefour City/Market, Auchan, Chronodrive, Intermarché, Leclerc Drive.

## Mise à jour 2025-10-10T14:45 (Europe/Paris)
- Photo : l’API `/api/collect` accepte `preview_only=1` et renvoie l’EAN détecté sans lancer la collecte. L’UI affiche désormais l’EAN et attend une validation explicite avant d’enchaîner.
- Boutons `Stopper` opérationnels sur les flux EAN / photo (annulation via `AbortController`).
- `decode_ean.py` renforce le vote des candidats : seule la lecture majoritaire au format `EAN13` est retenue ; les codes tronqués sont rejetés.
  - Checklist Git obligatoire (`git status`, `git pull --ff-only`) avant travaux.

- **Points à adresser immédiatement** :
  1. `pipeline/run_pipeline.py` ne fallback plus sur `Produit <EAN>` ; vérifier `server.py` pour alignement.
  2. Pour chaque test, créer un dossier `logs/refonte_v2/runs/<horodatage>` (commands, stdout/stderr, captures) et consigner dans `docs/HANDOVER_DAILY.md`.
  3. Seed descriptif = marque + type/goût + contenance (ex. "Orangina soda 1,5 L").
  4. Ne pas toucher au design `maxicourses_test/pipeline/index2.html`; la V2 vit dans `maxicourses_front_v2/`.
  5. Servir V1 & V2 avec un unique `python3 -m http.server 8000` lancé depuis `www/` (prévenir si port occupé).
  6. Supprimer/ignorer runs temporaires (`logs/refonte_v2/runs/`, `maxicourses_test/results/test-*`).

- **ToDo court terme** :
  - Neutraliser le fallback dans `server.py` et s’assurer que le seed OpenFoodFacts alimente bien marque/goût/contenance.
  - Relancer les fetchers Carrefour City→Market→Auchan→Chronodrive et Leclerc/Intermarché avec captures/JSON archivés.
  - Mettre à jour `docs/HANDOVER_DAILY.md`, `docs/PROMPT_LOG.md` et `docs/PRICE_COMPARATOR_PLAN.md` au fil de l’eau.

- **À signaler** : le dossier `maxicourses_test/results/test-3124480200433/` peut être supprimé s’il n’est plus utile.

## Mise à jour 2025-10-01T17:09 (Europe/Paris) – GPT (Codex CLI)
- Intermarché : le fetcher s’appuie dorénavant sur la recherche native (`input` « Lait, oeuf, pain… »), analyse les cartes produits de la page et clique la PDP en scorant les liens (`href` contenant l’EAN prioritaire). Ne plus rajouter de paramètres `trier=` dans les URLs manuelles.
- En cas de changement de magasin, regénérer `state/intermarche.json` via Chrome 9222 avant de relancer; la collecte Super Talence est validée (`5000112611861`, `5411188118961`).

## Mise à jour 2025-10-01T17:41 (Europe/Paris) – GPT (Codex CLI)
- Chronodrive : fallback systématique sur les requêtes descriptives (`seed_query` + `alternate_queries` dans `manual_descriptors.json`) lorsque l’EAN ne renvoie rien ; scoring renforcé pour privilégier les cartes correspondant aux tokens différenciants (ex. « amande »).
- Leclerc Drive : la collecte valide désormais un match sans GTIN si le titre recoupe les mots-clés du descriptif ; s’assurer que `manual_descriptors.json` contient marque + type + contenance pour tous les nouveaux produits.

## Mise à jour 2025-10-01T19:25 (Europe/Paris) – GPT (Codex CLI)
- Règle d’or pour le descriptif : interroger d’abord l’API OpenFoodFacts (`/api/v2/product/<EAN>.json`), puis – uniquement si nécessaire – fallback Auchan → Carrefour → Chronodrive pour compléter marque/nom/quantité.
- Les fiches produits affichent désormais Eco-score (A–E) et NOVA (1–4) aux côtés du Nutri-score ; toute nouvelle entrée `manual_descriptors.json` doit renseigner ces champs dès que disponibles.
- Le front propose un formulaire « Upload code-barres » qui envoie la photo au backend (`/api/collect` multipart). Ne rien modifier à l’API sans vérifier la compatibilité avec cette nouvelle voie (décodage zxing côté serveur).
- Nouveau script utilitaire `maxicourses_test/watch_uploads.py` : surveille `uploads/` et déclenche `run_pipeline.py` dès qu’une image est déposée. Lancer via `USE_CDP=1 python3 watch_uploads.py` (pip3 : `pillow`, `zxing-cpp`).

## Mise à jour 2025-10-02T14:34 (Europe/Paris) – GPT (Codex CLI)
- Collecter systématiquement marque + descriptif + quantité : `seed_query` = `marque + titre + quantité`.
- Téléchargement auto des visuels enseignes (`maxicourses_test/pipeline/assets/<EAN>.*`).
- Nutri-score : badge local (`../assets/nutriscore/nutriscore-*.svg`) ou fallback `unknown` si absent.
- Vérifier après chaque collecte : visuel disponible, badge Nutri-score, descriptif FR (sinon relancer OFF/Auchan).

## Mise à jour 2025-10-02T14:50 (Europe/Paris) – GPT (Codex CLI)
- Icônes Nutri-score : préférer les fichiers locaux (`../assets/nutriscore/nutriscore-*.svg`) \+ fallback `nutriscore-unknown.svg`, les URLs distantes sont proscrites.
- `run_pipeline.py` recalcule désormais automatiquement `seed_query` (marque en premier), télécharge l’image enseigne et applique le fallback Nutri-score ; ne jamais modifier `manual_descriptors.json` à la main.
- Chronodrive : lancer la recherche en EAN pur d'abord ; si `NO_RESULTS`, relancer avec le descriptif seed (attente 20 s avant de lire les cartes).

## Mise à jour 2025-10-02T15:26 (Europe/Paris) – GPT (Codex CLI)
- Seed obligatoire : `marque + descriptif + quantité` (60 caractères max, tokens uniques) – `run_pipeline.py` recalcule cette valeur automatiquement après chaque seed (aucune édition manuelle). – généré automatiquement par `run_pipeline.py`.
- Visuel : téléchargement enseigne (`maxicourses_test/pipeline/assets/<EAN>.*`) avant d’ajouter le produit.
- Nutri-score : utiliser uniquement `../assets/nutriscore/nutriscore-*.svg` (fallback `nutriscore-unknown.svg`).
- Chronodrive : première recherche en EAN pur > si `NO_RESULTS`, relancer avec `seed_query` (attente 20 s avant de lire les cartes).
- Après collecte : vérifier image, badge Nutri-score, descriptif FR ; relancer si besoin.

- Pour récupérer le slug Chronodrive du drive actif : `USE_CDP=1 python3 extract_chronodrive_slug.py` (Chrome 9222 ouvert sur le drive).
- TODO: renforcer `manual_leclerc_cdp.py` (requêtes courtes + scoring EAN/quantité) pour éviter le fallback multi-pack (ex. x50).

## Mise à jour 2025-10-02T20:44 (Europe/Paris) – GPT (Codex CLI)
- `maxicourses_test/pipeline/index2.html` : bandeau V1 mis à niveau pour les démos investisseurs.
  * Logo + formulaires alignés à gauche, résumé compact à droite (suppression du CTA inutile).
  * Bloc « Économie potentielle » recalculé via `computePortfolioDelta` : 7,80 € et badge `−23 %` en rouge (ou vert si hausse).
  * Résumé simplifié : rappel unique du pipeline multi-enseignes + archivage JSON/captures.
- Fichiers de backup `index2.html.option1*`, `index2.html.revamp` conservés pour rollback.
- Option 2 (tableaux) et Option 3 (cartes compactes) encore en attente, ne pas lancer sans feu vert.

## Mise à jour 2025-10-02T20:25 (Europe/Paris) – GPT (Codex CLI)
- `maxicourses_test/pipeline/index2.html` : bandeau d’intro modernisé → logo + formulaires alignés à gauche, résumé compact à droite, CTA supprimé.
- Nouveau bloc « Économie potentielle » (calcul via `computePortfolioDelta`) : montant + badge pourcentage (`masthead__delta-percent--loss` rouge si gain, vert sinon), cache automatique si 0 %.
- Textes du résumé allégés : la ligne « Tarification unitaire… » est supprimée.
- Sauvegardes conservées (`index2.html.option1*`, `.revamp`) pour rollback ; ne pas écraser ces fichiers sans validation.
- À garder pour la suite : Option 2 (lisibilité des tableaux) et Option 3 (cartes compactes) encore en attente, demander validation avant de modifier la page.
## Mise à jour 2025-10-02T20:55 (Europe/Paris) – GPT (Codex CLI)
- `run_pipeline.py` : `ensure_local_image_asset()` nettoie désormais les URLs (`html.unescape`, suppression des espaces) avant téléchargement ; les images enseignes sont rapatriées même si la source encode `&amp;`.
- `descriptor_from_payload()` dés-encode les URLs avant de sauvegarder le descriptor (évite de conserver des liens Auchan avec HTML entities dans `manual_descriptors.json`).
- EAN `3502110008329` : asset local `pipeline/assets/3502110008329.jpg` ajouté et référencé dans `manual_descriptors.json`, `results/test-3502110008329/latest.json`, `results/summary.json`.
- Conserver les sauvegardes `index2.html.option1*` / `.revamp` ; toute nouvelle collecte doit vérifier que chaque `image_path` pointe bien vers `../pipeline/assets/<EAN>.*` (gestion automatique désormais).

## Mise à jour 2025-10-02T22:04 (Europe/Paris) – GPT (Codex CLI)
- `run_pipeline.py` : `ensure_local_image_asset()` et `descriptor_from_payload()` dés-encodent désormais toutes les URLs image (`html.unescape`, suppression espaces) avant de stocker/télécharger → chaque collecte rapatrie automatiquement `pipeline/assets/<EAN>.*`.
- Les résultats (`results/test-<EAN>/latest.json` + `summary.json`) sont mis à jour avec `image_path` local ; plus de lien externe Auchan/Carrefour dans les descriptors.
- Pepsico 1,5 L (`3502110008329`) sert d’exemple : image locale ajoutée, fichiers alignés.
- Rappels : garder les sauvegardes `index2.html.option1*`/`.revamp` tant que les options 2/3 ne sont pas validées.
## Mise à jour 2025-10-02T22:20 (Europe/Paris) – GPT (Codex CLI)
- `run_pipeline.py` mémorise désormais le premier descriptif validé (Carrefour City/Market en priorité) dans `seed_primary_name/quantity` et s’en sert directement pour `leclerc_query` (libellé mot‑pour‑mot, quantité incluse).
- `ensure_local_image_asset()` + `descriptor_from_payload()` nettoient toujours les URLs (`html.unescape`, suppression espaces) avant stockage/téléchargement → toutes les collectes créent `pipeline/assets/<EAN>.*` sans intervention manuelle.
- `manual_descriptors.json` enrichi pour 3502110008329 (Pepsi) avec `seed_primary_*`; les futurs descriptors suivront automatiquement la même structure.
- Pour récupérer les prix Leclerc/Intermarché, rejouer les fetchers via Chrome 9222 : les nouvelles requêtes utiliseront directement le libellé Carrefour.

## Mise à jour 2025-10-04T11:55 (Europe/Paris) – GPT (Codex CLI)
**Objectif** : préparer l’intégration d’une IA dans la recherche Leclerc (génération de requêtes + validation) sans casser l’existant.

1. **Phase 0 – Préparation immédiate**
   - Lire ce plan + dernière entrée `docs/HANDOVER_DAILY.md` avant modif.
   - Mettre en pause toute collecte Leclerc automatique le temps que la boucle IA soit en place.
   - Créer `maxicourses_test/ai_helpers.py` avec des stubs pour :
     `summarize_product_seed(seed_payloads)`, `suggest_search_queries(ai_profile)`,
     `score_leclerc_candidates(ai_profile, candidates)`, `suggest_equivalent(ai_profile, candidates)` (optionnel).
   - Fournir un `ai_helpers.sample.toml` décrivant les variables d’environnement attendues (ex. `OPENAI_API_KEY`) — pas de secret dans le dépôt.

2. **Phase 1 – Profil produit IA**
   - Point d’entrée : juste après les seeds Carrefour/Auchan/Chronodrive.
   - Appeler `summarize_product_seed` pour obtenir un profil structuré (marque, gamme, type, quantité, attributs critiques, mots-clés).
   - Stocker `ai_profile`, `ai_keywords`, `ai_profile_generated_at` (Europe/Paris) dans `manual_descriptors.json`.

3. **Phase 2 – Requêtes Leclerc générées par l’IA**
   - `suggest_search_queries` produit ≤5 requêtes ≤40 caractères.
   - Injecter ces requêtes dans `descriptor['leclerc_queries']` (conserver `seed_primary_*` en fallback) + log `logs/refonte_v2/runs/<horodatage>/queries_leclerc.json`.

4. **Phase 3 – Collecte Leclerc multi-essais & validation IA**
   - Dans `run_adapter(... adapter=='leclerc' ...)` :
     1. lancer la recherche pour chaque requête,
     2. récupérer toutes les cartes (titre + JSON-LD + prix),
     3. demander à `score_leclerc_candidates` si chaque carte est `MATCH` / `NO_MATCH` (justification obligatoire),
     4. n’ouvrir que les cartes `MATCH`; sinon continuer la liste, sinon conclure `NO_RESULTS` (plus de pain de mie par défaut).
   - Loguer les verdicts IA dans `logs/refonte_v2/runs/<horodatage>/leclerc_verdicts.json`.

5. **Phase 4 – Équivalent (optionnel)**
   - Si tout échoue, appeler `suggest_equivalent` pour proposer un produit proche (`equivalent: true`, `difference_note`).

6. **Phase 5 – Tests & garde-fous**
   - Cas tests : café Carte Noire (EAN 8000070075207), croquettes Ultima (3700260216148), produit volontairement absent.
   - Ajouter des tests unitaires simulant les réponses IA (`tests/test_ai_helpers.py`).
   - Prévoir un flag `USE_AI_ASSIST=false` → si désactivé ou clé API absente, retomber sur la logique actuelle (warning dans les logs).

7. **Documentation / suivi**
   - Chaque jalon validé → nouvelle entrée `docs/HANDOVER_DAILY.md` (horodatage Europe/Paris + captures + logs).
   - Reporter ici les prompts finaux et modèles utilisés (pour audit).

## Mise à jour 2025-10-04T13:04 (Europe/Paris) – GPT (Codex CLI)
- Activation IA : placer un fichier `ai_helpers.toml` (cf. `ai_helpers.sample.toml`), exporter `OPENAI_API_KEY` et `USE_AI_ASSIST=true` avant de lancer `run_pipeline.py`. Sans ces variables tout retombe sur le comportement historique (queries heuristiques + validation locale).
- `run_pipeline.py` crée à chaque run AI un dossier `logs/refonte_v2/runs/<horodatage>-<EAN>-<PID>/` et y déverse :
  - `01_seed_profile_*` → prompt/réponse brute + JSON parsé par `summarize_product_seed` (profil produit + mots-clés).
  - `04/05/06` → requêtes Leclerc proposées par l’IA (≤5 items / 40 caractères).
  - `07/08/09` → pour chaque tentative Leclerc : prompt de validation, réponse brute, couples `{candidates, verdicts}`.
- Seed side : les payloads Carrefour/Market/Auchan/Chronodrive sont passés à `summarize_product_seed`; le descriptif est enrichi automatiquement avec `ai_profile`, `ai_keywords`, `ai_profile_generated_at_eur`. Les requêtes IA sont stockées dans `descriptor['leclerc_ai_queries']` (persistées dans `manual_descriptors.json`) et ressérées en tête de l’ordre de recherche.
- Fetch Leclerc : `manual_leclerc_cdp.py` expose maintenant la liste complète des cartes (`debug.candidates`). Le fetcher conserve ce bloc quand `LECLERC_KEEP_DEBUG=1`; `run_pipeline.py` le transmet à `score_leclerc_candidates`. Si l’IA retourne `NO_MATCH`, le statut bascule immédiatement sur `NO_MATCH` et le prix est vidé afin de forcer l’essai suivant. Les verdicts sont enregistrés dans `result.metadata['ai']['attempt_XX']`.
- Après validation IA, le `debug` est retiré du payload final (JSON de sortie identique à l’existant). En cas d’erreur IA, la collecte continue avec les heuristiques classiques (aucun blocage).
- Prochain GPT : ne pas modifier `run_pipeline.py`/`manual_leclerc_cdp.py` sans maintenir cette journalisation. En cas de changement de modèle ou d’API, adapter `ai_helpers.py` (fonctions `summarize_product_seed`, `suggest_search_queries`, `score_leclerc_candidates`) et documenter les nouveaux endpoints ici.

## Mise à jour 2025-10-04T13:25 (Europe/Paris) – GPT (Codex CLI)
- Pré-configuration IA simplifiée :
  1. Le fichier `maxicourses_test/ai_helpers.toml` est déjà prêt (copie du sample). Il suffit d’y mettre la clé ou de passer par l’environnement.
  2. Nouveau script d’exécution `maxicourses_test/run_ai_pipeline.sh` :
     - usage : `./run_ai_pipeline.sh <EAN>`
     - vérifie la présence de `OPENAI_API_KEY`, force `USE_AI_ASSIST=true` (sauf override) et `USE_CDP=1`.
- Workflow minimal pour une collecte :
  1. `cd maxicourses_test && ./start_chrome_debug.sh`
  2. Dans un second terminal : `cd maxicourses_test`
  3. `export OPENAI_API_KEY="sk-..."` (si non défini dans le TOML)
  4. `./run_ai_pipeline.sh 5000112611861`
  5. Consulter les journaux dans `logs/refonte_v2/runs/` (mêmes noms de fichiers qu’indiqué ci-dessus).
- Toute divergence (absence de clé, IA désactivée) déclenche un message clair dans le script, évitant les runs silencieux.

## Mise à jour 2025-10-04T16:15 (Europe/Paris) – GPT (Codex CLI)
- Rappel impératif : **aucun seed ne doit être modifié manuellement sans accord de Laurent**. Le descriptif canonique vient exclusivement du premier fetch EAN strict (Carrefour Market → City → Auchan → Chronodrive). L’IA n’intervient qu’après pour proposer éventuel équivalent.
- `manual_descriptors.json` contient désormais l’entrée alignée Carrefour Market pour l’EAN `3700260216148` (Ultima). Toute évolution devra être validée par Laurent avant modification.
- `ai_helpers.toml` reste la copie du sample : ne jamais versionner de clé. Exporter `OPENAI_API_KEY` et `USE_AI_ASSIST=true` avant chaque run (ou renseigner la clé dans le `.toml` local non versionné).
- `maxicourses_test/run_ai_pipeline.sh` est le lanceur unique : il s’assure de l’activation IA et de `USE_CDP=1`. Ne jamais recourir aux anciens scripts manuellement.
- Page V1 (`pipeline/index2.html`) affiche maintenant un badge « Produit différent » lorsqu’un équivalent IA est utilisé : la note fournie par l’IA (`difference_note`) est visible dans la colonne produit. Un statut `EQUIVALENT` doit être considéré comme « différent » et entraine validation explicite côté démo.
- Vérifier systématiquement `logs/refonte_v2/runs/<horodatage>-<EAN>-<PID>/` pour chaque collecte :
  - `01/02/03` = profil produit seed
  - `04/05/06` = requêtes IA
  - `07/08/09` = verdicts (MATCH/EQUIVALENT/NO_MATCH)
  Toute absence de ces fichiers signifie que l’IA n’a pas tourné (quota, erreur).
- Consigner dans `docs/HANDOVER_DAILY.md` toute modification post-collecte (horodatage Europe/Paris, EAN, statut IA, éventuels équivalents).

## Mise à jour 2025-10-04T18:31 (Europe/Paris) – GPT (Codex CLI)
- Stratégie IA actée :
  1. Toujours collecter en EAN brut (Market → City → Auchan → Chronodrive) et stocker les libellés, quantités et images renvoyés par ces drives, puis enchaîner Intermarché, Monoprix et enfin Leclerc en s’appuyant sur ce descriptif.
  2. Passer l’ensemble de ces retours à `ai_helpers.summarize_product_seed` pour obtenir un profil canonique : `brand`, `product_name`, `quantity`, `keywords`, `ai_profile_generated_at_eur`.
  3. Écrire/mettre à jour ce profil dans `manual_descriptors.json` (`ai_profile.brand`, `ai_profile.title`, `ai_profile.quantity`, `ai_keywords`, `canonical_descriptor`) pour que toutes les enseignes textuelles partent de la même base.
- Utilisation descendante :
  - `ai_helpers.suggest_search_queries(ai_profile)` doit générer les libellés courts (≤40 caractères) pour Leclerc/Intermarché ; ces requêtes sont injectées en tête dans `descriptor['search_queries']` avant les fallback historiques.
  - `ai_helpers.score_leclerc_candidates(ai_profile, candidates)` valide le meilleur match. Si tout échoue, appeler `ai_helpers.suggest_equivalent` pour identifier le produit le plus proche et retourner `status = "EQUIVALENT"` + `difference_note` (prix conservé mais marqué « produit différent » côté front).
  - Pour les enseignes seed (City/Market/Auchan/Chronodrive), on ne lance la passe descriptive IA que si la recherche EAN n’a pas donné de fiche (statuts `NO_RESULTS`/`NO_PRICE`). Si le produit est trouvé dès l’EAN, on conserve ce résultat sans seconde recherche.
- Pistes de code :
  - `maxicourses_test/pipeline/run_pipeline.py`
    1. Agréger tous les payloads seed (`carrefour_city`, `carrefour_market`, `carrefour_super`, `auchan`, `chronodrive`) puis appeler `summarize_product_seed` juste après leur réussite.
    2. Ajouter un helper `store_ai_canonical_descriptor(descriptor, ai_profile)` qui écrit les champs `ai_profile`, `ai_keywords`, `ai_profile_generated_at_eur`, `canonical_descriptor` dans `manual_descriptors.json`.
    3. Propager `canonical_descriptor` dans `descriptor['leclerc_ai_queries']`, `descriptor['intermarche_ai_queries']` et `descriptor['seed_ai_queries']` (pour City/Market/Auchan/Chronodrive). Lors de la boucle des fetchers, n’exécuter ces requêtes IA que pour les enseignes ayant échoué en EAN.
  - `maxicourses_test/ai_helpers.py`
    - Vérifier que `summarize_product_seed` renvoie clairement `brand`, `title`, `quantity`, `key_attributes`, `keywords`.
    - Étendre `suggest_search_queries` pour produire des variantes `marque + produit + quantité` triées par pertinence.
    - Implémenter `suggest_equivalent` (ou déplacer la logique dans `score_leclerc_candidates`) pour renvoyer `{ean?, label, difference_note}` lorsqu’aucun match exact n’existe.
  - `maxicourses_test/fetch_leclerc_drive_price.py` & `manual_leclerc_cdp.py`
    - S’assurer que le statut `EQUIVALENT` entraîne l’ajout d’un champ `metadata['ai']['difference_note']` et que le front affiche déjà le badge « produit différent ».
- Consigne : aucune modification manuelle du descriptif canonique ; seule une nouvelle collecte seed + passage IA peut réécrire `ai_profile`. Documenter chaque run IA (horodatage Europe/Paris) dans `logs/refonte_v2/runs/` et `docs/HANDOVER_DAILY.md`.

## Mise à jour 2025-10-04T19:10 (Europe/Paris) – GPT (Codex CLI)
- Rappel opérationnel : Laurent (chef de projet) ne relance jamais les services. Tout assistant GPT doit redémarrer lui-même les composants impactés par ses modifications (ex. `server.py`, scripts de collecte, Chrome 9222) avant de déclarer la tâche terminée.

## Mise à jour 2025-10-05T12:07 (Europe/Paris) – GPT (Codex CLI)
- Étapes obligatoires pour chaque collecte IA :
  1. `cd maxicourses_test && ./start_chrome_debug.sh` (Chrome 9222 actif).
  2. `export USE_AI_ASSIST=true` + `export OPENAI_API_KEY=...` (ou clé dans `ai_helpers.toml` non versionné).
  3. `./run_ai_pipeline.sh <EAN>` (ou `/api/collect` équivalent). Vérifier la création de `logs/refonte_v2/runs/<horodatage>-<EAN>-<PID>/`.
  4. Contrôler dans ce dossier les fichiers `01/02/03` (profil), `04/05/06` (requêtes), `07_seed_retry_*` (relances City/Market/Auchan/Chronodrive après échec EAN), `07/08/09` (verdicts Leclerc) et, si besoin, `10/11/12` (suggestion équivalente).
- Consignes impératives :
- Toujours exécuter la recherche EAN en premier. Les requêtes descriptives IA ne sont déclenchées que lorsque l’EAN échoue sur l’enseigne cible.
- Utiliser en priorité les modèles `gpt-5.0` / `gpt-5.0-mini` (voir `maxicourses_test/ai_helpers.toml`). En cas de quota ou d’erreur d’API, rétrograder explicitement vers `gpt-4.1*` et documenter le switch dans le handover.
- Ne jamais contester les instructions de Laurent : appliquer ses décisions à la lettre et documenter le résultat.
- Après chaque run, mettre à jour `manual_descriptors.json` (profil canonique, requêtes IA) et vérifier que le front affiche le badge « produit différent » lorsque `result.status == EQUIVALENT`.
- Priorité immédiate : corriger le pipeline IA pour ne conserver que les seeds dont `matched_ean == EAN`, faire recalculer `brand` via `ai_profile.brand`, et garantir que les requêtes générées suivent strictement le format « marque + produit + type + contenance » (≤30 caractères) pour Leclerc, Monoprix, Intermarché.
- Bloquer les fetchers Leclerc qui renvoient des packs (ex. 4x1,5L) lorsque l’EAN cible est une unité ; ajuster `manual_leclerc_cdp.py` en conséquence.
- Relancer des runs complets (seed + IA + toutes enseignes) pour les EAN 8712100731822 / 3124480200433 / 3700260216148 et vérifier que `results/summary.json` affiche les entrées Monoprix et Intermarché correctes.
- Directions de développement :
  - Implémenter une normalisation automatique du `descriptor['brand']` à partir de `ai_profile.brand` quand la valeur existante est un code interne (ex. `C1746425`).
  - Étendre les requêtes IA (`seed_ai_queries`) si une enseigne seed reste sans résultat malgré la relance actuelle.

## Mise à jour 2025-10-08T09:40 (Europe/Paris) – GPT (Codex CLI)
- IA refondue :
  - `primary_keywords` = requête à envoyer (`marque` → `quantité/format` → `type` → variante optionnelle) ; `secondary_keywords` = mots à vérifier sur la fiche (ex. stérilisé, aromates, grandiose).
  - Templates automatiques par type détecté (croquettes, lessive, condiments, fallback générique). Termes bannis des requêtes primaires : `stérilisé`, `adulte`, `promo`, `lot`, `pack`, `xN`, etc.
  - Prompts OpenAI à conserver :
    ```
    summarize_product_seed.system = "Tu synthétises les seeds Carrefour/Auchan/Chronodrive. JSON strict {profile, keywords}. keywords ≤8 entrées, ≤30 caractères, centrées sur marque + produit + contenance."
    suggest_search_queries.system = "Tu génères des requêtes ultra-compactes pour {store}. JSON {queries} ≤{max_queries} entrées, ≤{max_length} caractères. Commencer par la marque, enchaîner sur le produit puis la contenance si possible. Interdits : termes génériques (produit, promo, course...)."
    ```
- Pipeline :
  - Rejet automatique des seeds où `matched_ean` est absent/différent (exclusion des Chronodrive « Purina 3 kg »).
  - `manual_descriptors.json` stocke désormais `primary_keywords`, `secondary_keywords` et les listes secondaires par enseigne (`leclerc_secondary_keywords`, etc.).
  - Les fetchers texte n’utilisent que `primary_keywords` pour la requête et valident les cartes via tous les `secondary_keywords`. Sinon → `NO_MATCH` + consigne dans `docs/SEED_RULES.md`.
  - Nouveau mémo `docs/SEED_RULES.md` (format : « Faire ceci = erreur » / « Faire cela = OK » par EAN).

## Mise à jour 2025-10-07T15:10 (Europe/Paris) – GPT (Codex CLI)
- Toutes les enseignes textuelles (Leclerc, Monoprix, Intermarché) utilisent désormais des requêtes générées par OpenAI à partir des seeds EAN (Carrefour/Auchan/Chronodrive). Chaque requête ≤ 30 caractères, format « marque + produit [+ contenance] ».
- Pipeline `run_pipeline.py` : après les seeds, `summarize_product_seed` produit `ai_profile`/`ai_keywords`, puis `suggest_search_queries(store=…)` génère `leclerc_ai_queries`, `monoprix_ai_queries`, `intermarche_ai_queries` (stockées dans `manual_descriptors.json`).
- `run_adapter` priorise ces listes pour les fetchers texte ; fallback = seed query + EAN. Intermarché profite du même mécanisme (mots clés courts).
- Monoprix : frappe humaine (`type` avec délai), recharge `/search?q=<query>`, parse JSON-LD pour extraire les PDPs si les cartes ne s'affichent pas ; PDP fallback lit le `body` pour récupérer prix/quantité en filtrant 0,00 €/60,00 €.
- Logs IA déposés dans `maxicourses_test/logs/refonte_v2/runs/<horodatage>-<ean>-<pid>/` (1. `01_seed_summary`, 2. `02_queries_<enseigne>`).
- Tests IA effectués sans réutiliser les anciens descripteurs :
  * 3124480200433 → Monoprix `"Orangina 1.5 L"` → fiche « Sans sucres 1,5L » / Intermarché OK.
  * 3700260216148 → Monoprix `"PURINA One croquettes saumon 3"` (équivalent 1,5kg) / Intermarché substitut valide.
  * 8712100731822 → Intermarché OK ; Monoprix ne référence plus Savora (logs `temp/monoprix-test-20251007-150457/`).

## Mise à jour 2025-10-05T19:33 (Europe/Paris) – GPT (Codex CLI)
- **Leclerc Drive**
  - Adapter `manual_leclerc_cdp.py` pour lire le tableau `ListesProduits.objPresentation.lstProduits`, extraire les cartes Finish (EAN + quantité) et ouvrir directement `sUrlPageProduit` au lieu de s’arrêter sur la page de recherche.
  - En cas d’échec (aucun produit Finish), retourner `NO_RESULTS` sans créer d’équivalent fantôme.
- **Traitement des équivalents dans le pipeline/front**
  - Idée : lorsqu’un produit alternatif est retenu, le marquer `equivalent=true` mais le sortir du bloc “Moins cher”. L’afficher en bas de tableau avec : prix total, `unit_price`, note d’écart (format différent, pack supérieur…), comparaison positive si `unit_price` est plus avantageux.
  - Ajouter un champ `difference_quantity` / `difference_note` dans `result.metadata` pour consigner l’écart (ex. “42 tablettes vs 48 tablettes”).
- **Règle produit**
  - Si Carrefour/Intermarché renvoient un format plus grand, le pipeline doit :
    1. calculer `unit_price`,
    2. afficher un badge “Format différent” et indiquer que le prix au kg/L peut être plus intéressant.
- **Documenter / tester**
  - Une fois les changements appliqués, relancer `./run_ai_pipeline.sh 3665468402529` et archiver les journaux dans `logs/refonte_v2/runs/<horodatage>-3665468402529-XXXX/` en vérifiant que Leclerc sort une cascade de véritables produits Finish.

## Mise à jour 2025-10-04T19:00 (Europe/Paris) – GPT (Codex CLI)
- Pipeline `run_pipeline.py` :
  - Nouvelle fonction `apply_ai_canonical_descriptor` → applique le profil IA aux descripteurs (`canonical_descriptor`, `canonical_descriptor_generated_at_eur`) et remplit marque/nom/quantité lorsque les seeds étaient ambigus.
  - Lorsqu’`ai_helpers.suggest_search_queries` réussit, la liste est mise en cache dans `descriptor['seed_ai_queries']` et réutilisée par tous les fetchers.
  - Deuxième passe IA automatique sur City/Market/Auchan/Chronodrive uniquement si la recherche EAN a échoué : relance via `run_adapter(..., allow_text_query_for_seed=True)` et journal `logs/refonte_v2/runs/.../07_seed_retry_<adapter>.json`.
  - Tous les fetchers non-EAN (Intermarché inclus) essaient désormais les requêtes IA en fallback (`seed_ai_queries`).
- Détection des équivalents :
  - Si un fetch retourne `matched_ean` différent de l’EAN seed, le statut bascule sur `EQUIVALENT` avec note explicite « Produit différent (EAN divergent) ».
  - Pour Leclerc : en absence de match exact, appel automatique à `suggest_equivalent` (fichiers de log `10/11/12`) afin de proposer un substitut cohérent et remplir `difference_note`.
- Impact front : le badge « produit différent » reste alimenté par `payload['equivalent']=true` + `difference_note` (inchangé côté `index2.html`).

## Mise à jour 2025-10-31T21:15 (Europe/Paris) – GPT (Codex CLI)
- Statut Carrefour Super : wrapper créé (`fetch_carrefour_price_super.py`) et intégré au pipeline/front. **À faire** : rejouer un parcours humain (Chrome 9222) pour sélectionner le drive « Lormont, Gironde, France » et regénérer `state/carrefour_super.json` (capturer `displayableUrlId`, `facilityServiceId`, `FRONTAL_STORE`). Aucun label « Lormont Super » n’existe dans l’UI, c’est normal.
- Gel strict des fetchers historiques (Market, City, Auchan, Chronodrive, CourseU, Intermarché, Leclerc, Monoprix) : n’apporte aucune modification sans instruction claire de Laurent ; concentre-toi sur Carrefour Super et la documentation.
- Avant toute prise en main, relis les fichiers listés dans la section « Lecture obligatoire (ordre strict) » ; c’est l’ordre à suivre pour le prochain GPT, ne le change pas.
