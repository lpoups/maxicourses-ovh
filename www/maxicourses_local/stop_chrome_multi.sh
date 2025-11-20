#!/usr/bin/env bash
# Stop Chrome instances started by start_chrome_multi.sh
set -euo pipefail

PORT_LIST=(
  "carrefour_city:9222"
  "carrefour_market:9223"
  "carrefour_super:9224"
  "auchan:9225"
  "chronodrive:9226"
  "courseu:9227"
  "g20:9228"
  "intermarche:9229"
  "leclerc:9230"
  "monoprix:9231"
)

for entry in "${PORT_LIST[@]}"; do
  name="${entry%%:*}"
  port="${entry##*:}"
  pids=$(lsof -Pi :"$port" -sTCP:LISTEN -t 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "Arrêt Chrome ${name} (port ${port}) pid(s): ${pids}"
    kill $pids >/dev/null 2>&1 || true
  else
    echo "Aucun Chrome ${name} actif (port ${port})."
  fi
done
