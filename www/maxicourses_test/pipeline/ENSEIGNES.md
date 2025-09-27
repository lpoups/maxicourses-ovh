# Stratégie de validation par enseigne

Objectif : sécuriser l'extraction des prix pack + prix unitaire + descriptif pour chaque enseigne en reproduisant un parcours "humain" avant d'automatiser.

## Carrefour
- Utiliser `fetch_carrefour_price.py` avec un EAN (`STORE_QUERY=Bordeaux City` par défaut).
- Home local: https://www.carrefour.fr/courses (chargée avant la recherche pour fixer la zone).
- Variantes: `carrefour_city` (Bordeaux City) et `carrefour_market` (Bordeaux Market) via le pipeline; bascule magasin pilotée par `STORE_QUERY` + CDP `state/carrefour*.json`.
- Étapes manuelles à reproduire : page recherche → premier résultat → sélection magasin (City/Market/Drive) → vérifier prix affiché + bloc €/L.
- Si Cloudflare bloque (`status=CF_BLOCK`), relancer via proxy/ngrok ou `HEADLESS=0` pour observer le flux et ajuster les clics (cookies, magasin).
- Validation : confirmer que `store` est renseigné (ex. "Carrefour City Bordeaux Pessac") et que `price` contient le pack.

## Leclerc Drive
- Script `fetch_leclerc_drive_price.py` utilise le drive de Bruges par défaut : https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx.
- Parcours manuel : accepter cookies → choisir magasin → taper requête texte (`QUERY`) → ouvrir fiche produit → vérifier JSON-LD pour prix pack et €/L.
- Validation : `matched_ean` dans payload, `price` pack, `title` complet (marque + volume).

## Intermarché
- Script `fetch_intermarche_price.py` déjà orienté UI : ouvre home, clique recherche, sélectionne magasin si modal.
- Home par défaut : https://www.intermarche.com/accueil.
- Vérifier que le parcours enclenche `button:has-text('Choisir mon magasin')` puis affiche le prix pack + €/L (souvent dans `data-price-unit`).
- Validation : payload `status=OK` et présence de `note` mentionnant le magasin si besoin.

## Auchan
- `fetch_auchan_price.py` : vérifier cookie Datadome éventuel. Simuler parcours home → recherche texte → premier résultat → fiche.
- Home par défaut : https://www.auchan.fr.
- Ajouter si besoin `STORE_URL` (drive ou livraison Bordeaux) pour fixer la zone.
- Validation : prix pack et unitaire dans JSON-LD ou bloc `.product-price`.

## Chronodrive
- `fetch_chronodrive_price.py` : commence par la home https://www.chronodrive.com (à ajuster avec un slug drive précis si besoin).
- Parcours : accepter cookies (Onetrust) → barre recherche → fiche produit → vérifier section "Prix au litre".
- Validation : `title` et `price` pack, et extraction parallèle du prix unitaire.

### Procédure de test
1. Lancer `pipeline/run_pipeline.py --ean <EAN> --adapters <enseigne>` en `--headed` pour observer.
2. Ajuster le script de l'enseigne (cookies, sélection magasin, selectors) jusqu'à statut `OK` with price + unit.
3. Documenter le magasin sélectionné (slug, URL) dans `config.toml` ou variables d'environnement pour les runs suivants.
4. Une fois les 5 enseignes validées, lancer le pipeline complet et vérifier la sortie JSON + rendu HTML.

Sauvegarder les captures manuelles (si besoin) dans `maxicourses_test/incoming/screenshots/` pour référence.
- Carrefour: tests 18/09 — `home.html` montre une page Cloudflare "Un instant…" lorsque l’IP NGrok est grillée; penser à renouveler l’IP/proxy avant de rejouer le parcours.
