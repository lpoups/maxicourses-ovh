#!/usr/bin/env bash
set -euo pipefail

# === PARAMS (adapte si besoin) ===
PY="/Users/laurentpoupet/venv/bin/python3"
SCRAPER="/Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicoursesapp/api/leclerc_price_scraper.py"
SEED_API="http://maxicourses.fr/maxicoursesapp/api/compare_api.php"
TOKEN="maxi_dev_seed"

URLS=(
  "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges/fiche-produits-214087-Soda-Coca-cola-.aspx"
  "https://www.carrefour.fr/p/soda-au-cola-gout-original-coca-cola-5000112611861"
  "https://www.intermarche.com/produit/soda-au-cola-gout-original/5000112611861"
  "https://www.auchan.fr/coca-cola-boisson-gazeuse-aux-extraits-vegetaux-gout-original/pr-C1211988"
  "https://courses.monoprix.fr/products/coca-cola-original-1-75l/MPX_3341719"
)

echo "==> SEED depuis le poste local vers OVH…"
for U in "${URLS[@]}"; do
  echo "----"
  echo "Scrape local: $U"
  # Ne pas forcer Chrome/9222 : certains sites (ex. Carrefour) déclenchent une protection quand MAXI_ATTACH=1
  JSON=$("$PY" "$SCRAPER" "$U" || true)

  # Extrait price+title avec python (pas de dépendance jq)
  PRICE=$("$PY" -c 'import sys,json; d=json.loads(sys.stdin.read() or "{}"); print(d.get("price",""))' <<<"$JSON")
  TITLE=$("$PY" -c 'import sys,json; d=json.loads(sys.stdin.read() or "{}"); print(d.get("title",""))' <<<"$JSON")

  if [[ -z "$PRICE" ]]; then
    echo "!! Pas de prix local -> on saute le SEED pour cette URL"
    continue
  fi

  echo "Seed OVH: price=$PRICE | title=$TITLE"
  curl -sG "$SEED_API" \
    --data-urlencode 'seed=1' \
    --data-urlencode "token=$TOKEN" \
    --data-urlencode "url=$U" \
    --data-urlencode "price=$PRICE" \
    --data-urlencode "title=$TITLE" \
    --data-urlencode 'currency=EUR' \
  | sed -e $'s/{/\\\n{/g' | tail -n 1
done

echo "==> Terminé."