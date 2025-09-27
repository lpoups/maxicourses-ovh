# Journal de Collaboration Copilote

Dernière mise à jour: 2025-09-12

## 1. Objectif Global du Projet
Construire un service de comparaison de prix multi‑enseignes (Carrefour, Leclerc, Intermarché, etc.) à partir d’un EAN (issu d’un code‑barres) en générant un “produit canonique” (métadonnées normalisées) qui servira ensuite à lancer des recherches textuelles sur les enseignes ne supportant pas la recherche directe par EAN.

## 2. Rôles et Choix Stratégiques
- **Carrefour = Source pivot** : permet la recherche directe par EAN → on récupère HTML + prix + attributs pour fabriquer le produit canonique.
- **Produit canonique (Étape A)** : contient marque, libellé, variantes, grammage/poids, pack_count, keywords normalisés.
- **Leclerc** : plus fragile (DataDome / puzzle anti‑bot). Besoin d’un mode HEADFUL + pause manuelle configurable (à implémenter: `LECLERC_DEBUG_PAUSE`).
- **Intermarché** : logicielle Playwright/HTTP modularisée dans `stores/intermarche.py`.
- **Architecture** : migration progressive vers `maxicoursesapp/api/stores/*.py` (carrefour, intermarche, futur leclerc, auchan stub, monoprix stub).
- **Instrumentation Carrefour** : HTTP direct → fallback Playwright avec capture réseau (requests/responses) + classification `price_source` (html, network_recommendations_param, network_body_snippet).

## 3. Chronologie Résumée
| Ordre | Événement / Décision | Détails |
|-------|----------------------|---------|
| 1 | Monolithe initial Leclerc | Scraping direct, sensible au blocage. |
| 2 | Ajout Carrefour | HTTP + fallback Playwright; extraction prix multi sources. |
| 3 | Modularisation partielle | Création dossier `stores/` pour carrefour, intermarche. |
| 4 | Intégration Intermarché | Similaire à Carrefour, wrappers rétrocompatibles. |
| 5 | Canonical product (Étape A) | Module `productinfo/canonical.py` — dérive attributs à partir du HTML Carrefour (force Playwright si nécessaire). |
| 6 | Ajout `debug_html` Carrefour | Permet d’enregistrer la page pour parsing canonique fiable. |
| 7 | Problèmes d’import | Erreurs relatives: ajout de `__init__.py` (paquet Python) dans `maxicoursesapp/`, `api/`, `api/stores/`. |
| 8 | Compat Python 3.9 | Ajout `from __future__ import annotations` à `scraper.py` pour unions `type1 | type2`. |
| 9 | Corruption `_compare_ean` | Duplications multiples → plan de réécriture propre unique. |
|10 | Fallback dynamique manquant | Sur EAN inconnu: décider de toujours tenter Carrefour + Intermarché. |
|11 | EAN réel fourni | 3033491485756 (extrait d’une photo). |
|12 | Requête `/compare` vide | Restitue `note: EAN inconnu...` → nécessité de corriger `_compare_ean`. |
|13 | Plan futur Leclerc | Pause manuelle (40s+) pour résoudre puzzle DataDome quand HEADFUL=1. |

## 4. EAN de Référence
- Code fourni par l’utilisateur (photo): **3033491485756** (checksum EAN13 validé).

## 5. État Actuel (avant réécriture finale propre de `_compare_ean`)
- `_compare_ean` présent en double dans `scraper.py` → conflit et fragments résiduels.
- La version souhaitée doit :
  1. Nettoyer les duplications.
  2. Si pas dans `_PRODUCT_URLS`: lancer Carrefour + Intermarché dynamiquement et ajouter `note: dynamic_fallback_no_mapping`.
  3. Si mapping présent: utiliser URL Leclerc (si existante), Carrefour (multi‑slugs si demandé), Intermarché.
  4. Injecter le produit canonique quand disponible.

## 6. Prochaines Étapes Prioritaires
1. (EN COURS) Réécrire `_compare_ean` proprement et supprimer toutes les définitions anciennes / fragments.
2. Relancer serveur en mode module: `python3 -m maxicoursesapp.api.scraper --serve 127.0.0.1:5001`.
3. Tester `/compare?ean=3033491485756` → vérifier présence éventuelle de résultats Carrefour et du bloc `product`.
4. Implémenter `LECLERC_DEBUG_PAUSE` dans `_scrape_leclerc_headless` :
   - Détection puzzle (mots clés DataDome, absence sélecteur prix, code HTTP atypique).
   - Boucle d’attente (ex: pas de blocage > 40s) interrompable dès apparition prix.
5. Migrer toute la logique Leclerc dans `stores/leclerc.py` (supprimer l’ancienne version interne une fois stable).
6. Construire fallback de recherche textuelle (générer requêtes à partir du produit canonique: marque + forme + quantité).
7. Ajouter tests unitaires légers (parsing canonical + classification `price_source`).
8. Préparer extension d’enseignes (Auchan, Monoprix) via la même abstraction.

## 7. Variables d’Environnement Clés
| Variable | Usage |
|----------|-------|
| `HEADFUL` | Lancement navigateur non headless pour résoudre captchas. |
| `CARREFOUR_FORCE_PLAYWRIGHT` | Forcer directement Playwright (bypass HTTP). |
| `CARREFOUR_DEBUG_PAUSE` | Pause manuelle après chargement Playwright Carrefour. |
| `LECLERC_DEBUG_PAUSE` (à venir) | Pause puzzle DataDome manuelle. |
| `MAXI_DEBUG` | Mode debug global (logs supplémentaires). |

## 8. Schéma Résultats (objectif convergent)
Structure cible par entrée `results[]` :
```json
{
  "store": "carrefour|leclerc|intermarche|carrefour_slug",
  "ok": true,
  "price": 1.99,
  "ean": "3033491485756",
  "desc": "Libellé produit",
  "url": "https://...",
  "store_slug": "optionnel",
  "product_forced": false,
  "playwright": true,
  "price_source": "html|network_body_snippet|network_recommendations_param",
  "multi": false,
  "bot": false
}
```

Bloc `product` (canonique) envisagé :
```json
{
  "ean": "3033491485756",
  "brand": "...",
  "name": "...",
  "variant": "...",
  "weight_kg": 0.5,
  "pack_count": 6,
  "keywords": ["marque","forme","dosettes","..."],
  "normalized_query": "marque forme ..."
}
```

## 9. Principales Sources de Bugs Rencontrés
| Problème | Cause | Solution |
|----------|-------|----------|
| ImportError relatifs (`attempted relative import`) | Absence de `__init__.py` | Ajout fichiers vides marquant les paquets. |
| TypeError union types | Python 3.9 sans `from __future__ import annotations` | Ajout de l’import future. |
| `_compare_ean` dupliqué/corrompu | Patches successifs partiels | Réécriture complète prévue. |
| Leclerc puzzle anti‑bot | DataDome / challenge JS | Prévoir HEADFUL + pause manuelle + heuristique détection. |

## 10. Heuristiques Prévue Détection Puzzle Leclerc
- Contenu HTML contient `datadome` ou script challenge.
- Absence de motif prix après X secondes / X tentatives.
- Réponse HTTP atypique (403, 429) ou redirection challenge.

## 11. Sécurité & Anti‑blocage (idées futures)
- Rotation user‑agents raisonnable (pas encore mise en place).
- Limiter fréquence Playwright (caching TTL sur canonical product, déjà amorcé côté `get_canonical_product`).
- Stocker hash HTML Carrefour pour éviter re‑fetch si identique durant TTL.

## 12. TODO Technique Détaillé
- [ ] Finaliser `_compare_ean` (single source of truth) propre.
- [ ] Implémenter `LECLERC_DEBUG_PAUSE` avec boucle progressive (5s step).
- [ ] Extraire Leclerc dans `stores/leclerc.py` avec API `search_by_ean` (même interface que Carrefour/Intermarché).
- [ ] Normaliser champs `desc` (nettoyage espaces, suppression marque en double).
- [ ] Générateur de requêtes textuelles (priorité: marque + type + taille).
- [ ] Ajouter endpoint `/canonical?ean=` pour introspection/debug.
- [ ] Tests parsing canonical (au moins 3 cas : simple, pack, poids + unité séparée).
- [ ] Logger `price_source` systématiquement (même pour Intermarché/Leclerc plus tard).
- [ ] Mettre un cache mémoire (LRU simple) sur appels réseau récurrents.

## 13. Commandes Utiles (Rappel)
```bash
# Lancer serveur API en mode module
python3 -m maxicoursesapp.api.scraper --serve 127.0.0.1:5001

# Requête comparaison
curl -s "http://127.0.0.1:5001/compare?ean=3033491485756" | jq .

# Forcer Playwright Carrefour
CARREFOUR_FORCE_PLAYWRIGHT=1 python3 -m maxicoursesapp.api.scraper --serve 127.0.0.1:5001

# Pause debug Carrefour (ex: 30s)
CARREFOUR_DEBUG_PAUSE=30 HEADFUL=1 python3 -m maxicoursesapp.api.scraper --serve 127.0.0.1:5001
```

## 14. Politique de Patchs À Suivre
1. Toujours vérifier s’il existe une définition dupliquée avant d’insérer une nouvelle fonction.
2. Ne patcher que la zone nécessaire (éviter reformat global pour limiter conflits).
3. Après patch: exécuter un `grep` du symbole clé pour confirmer unicité.
4. Tester l’endpoint principal immédiatement après (feedback rapide).

## 15. Check‑list Reprise Après Redémarrage
- [ ] Activer venv: `source .venv/bin/activate`
- [ ] Lancer serveur module.
- [ ] Tester EAN pivot Carrefour.
- [ ] Si résultat vide → vérifier `_compare_ean` unique + logs Carrefour.
- [ ] Implémenter ou vérifier pause Leclerc si puzzle récurrent.

## 16. Notes Diverses
- L’EAN réel 3033491485756 sert de test récurrent; peut être ajouté plus tard dans un petit script d’intégration.
- Éviter multiplication des flags; documenter chaque nouvelle variable d’env dans ce fichier.
- Une future persistance (SQLite / JSON) pourrait mémoriser les produits canoniques pour réduire le nombre de navigations Playwright.

## 17. Historique Mini des Décisions Clés
- (Décision) Carrefour pivot : validé.
- (Décision) Ajout canonical avant text fallback : validé.
- (Décision) Attente manuelle Leclerc nécessaire : validé.
- (Décision) Ne pas abandonner sur EAN inconnu : fallback dynamique : validé.

---
Ce fichier sert de mémoire durable. Mettre à jour la section "Dernière mise à jour" quand vous ajoutez / modifiez une partie significative.

Fin du journal.

## 18. Mise à jour Carrefour (Phase Avancée Prix Affiché 2,50€)

### 18.1 Contexte du Problème
Objectif strict: retourner le prix affiché en rayon/site (2,50 €) pour l’EAN 3033491485756 et ne jamais confondre avec:
- Prix interne / unitaire (2.05 / 2,05) provenant d’objets JSON intermédiaires (souvent liés à unitOfMeasure KG/G).
- Frais de livraison (2.99, 4.99, 6.99, etc.).

### 18.2 Évolution des Tentatives
1. Extraction naïve JSON → renvoie 2.05 (mauvaise valeur unitaire).
2. Apparition de frais livraison dans les candidats (sélection erronée parfois 2.99 / 4.99).
3. Ajout filtrage shipping + tagging `unit_measure_price` → 2.05 isolé mais plus sélectionné quand doute.
4. Reconstruction fragments DOM `.product-price__content` (double: `2` + `,50`; triple: `2` + `,` + `50`).
5. Ajouts heuristiques supplémentaires: `dom_live`, `dom_seq`, `dom_cluster`, `dom_scan`, `dom_guess_pair`, `dom_shadow`, `window_state_price`.
6. Garde finale: si seul petit prix <3 (json) sans candidat plausible 2.3–2.7 → retour `price=null` (évite faux positifs).

### 18.3 Nouveautés Implémentées (Dernier Patch)
- Interception réseau élargie: capture de TOUTES les réponses (`_match` toujours vrai) plutôt que filtre mot-clé.
- Ajout d’un `add_init_script` précoce patchant `fetch` et `XMLHttpRequest` pour journaliser:
  * URL, status, content-type.
  * Petit extrait (25k chars) du corps de réponse.
  * Erreurs fetch éventuelles.
- Stockage dans `window.__MC_NET_LOGS__` puis restitution côté Python (à compléter pour extraction future si besoin).
- Champs `network_logs['hooks']` réservé si on rapatrie plus tard les logs client patchés.

### 18.4 Classification & Tags Clés
- `unit_measure_price`: détecté via contexte contenant `unitOfMeasure` + unité.
- `shipping_fee`: contexte `frais de livraison` ou valeur typique + alternative disponible.
- `article_price_candidate`: appliqué sur toute occurrence 2.50 identifiée via DOM, réseau ou state.
- Démotions explicites: `demoted_unit` sur 2.05 lorsqu’un 2.50 fiable apparaît.

### 18.5 Sources Actuellement Explorées
- HTML statique initial.
- JSON-LD / attributs meta `itemprop=price`.
- Réponses réseau (corps JSON partiels, priceInteger/priceDecimal, pattern "price":2.50 hors unitOfMeasure KG).
- Fragments DOM (séquences de nœuds texte disjoints).
- Pattern corps complet (recherche globale `2[\s,.]?50 €`).
- État global `window` (parcours de propriétés sérialisables JSON contenant l’EAN + 2,50).
- Shadow DOM récursif.

### 18.6 Prochaines Actions (Phase suivante)
1. Rapatrier dans `network_logs['hooks']` le contenu de `window.__MC_NET_LOGS__` en fin de session (évaluer côté page) pour inspecter fetch/XHR dynamiques (pas encore remonté dans l’objet Python final).
2. Détecter JS chunks (MIME `text/javascript`) et parser pour valeurs embarquées 2,50 liées à l’EAN.
3. Tentative proactive: exécuter (si nécessaire) la requête GraphQL / API produit par EAN (si passive interception échoue) et classifier résultat.
4. Ajouter métrique debug: `price_resolution_stage` (ex: `dom_frag`, `network_display_frag`, `window_state_price`, ou `unresolved`).
5. Implémenter un mode trace minimal (limiter taille logs à N réponses / M caractères cumulés pour éviter inflation mémoire).

### 18.7 Critères d’Acceptation Prix Carrefour
Un prix est accepté si:
1. Valeur 2.50 détectée dans une source marquée visuelle (`dom_*`) OU réseau sans contexte unitOfMeasure OU état global window contenant l’EAN et 2.50.
2. Aucune classification shipping ou unit_measure associée.
3. Différence >= 0.30 avec prix unitaire plus bas (ex: 2.05) renforce la sélection.
4. En cas d’incertitude, résultat doit rester `null` (fail-safe). 

### 18.8 Risques Restants
- Prix 2.50 potentiellement rendu en retard via micro-front JS après nos fenêtres de polling (besoin d’allonger/adapter triggers scroll/mutation?).
- Obfuscation possible (2 et 50 générés via canvas ou pseudo-elements CSS) → prévoir inspection computed style ou snapshots.
- Variation selon storeId: garantir injection correcte du store (env `CARREFOUR_STORE_ID`).

### 18.9 Décisions Validées dans Cette Phase
- Ne jamais promouvoir 2.05 si un 2.50 potentiel apparaît plus tard (même tardivement).
- Capture large (toutes réponses) temporaire pour cartographier la source réelle avant réaffinage.
- Préférence à la véracité sur la complétude: renvoyer null plutôt qu’un prix faux.

### 18.10 TODO Spécifique (Delta par rapport Section 12)
- [ ] Récupérer `__MC_NET_LOGS__` (fetch/XHR hooks) dans l’output debug.
- [ ] Ajouter parsing JS chunk (regex EAN + pattern prix).
- [ ] Ajouter champ `price_resolution_stage`.
- [ ] Ajouter heuristique pseudo-elements (via `getComputedStyle(::before/::after)` si suspicion d’absence fragments).
- [ ] Introduire timeout adaptatif si seul `json_price` <3 observé (ex: prolonger jusqu’à 20s max avant abandon).

---
