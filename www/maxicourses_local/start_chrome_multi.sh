#!/usr/bin/env bash
# Launch one Chrome remote-debug instance per enseigne for local runs.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

find_chrome() {
  for bin in "${CHROME_BIN:-}" "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" google-chrome-stable google-chrome chromium chromium-browser; do
    if [[ -n "$bin" && -x "$bin" ]]; then
      echo "$bin"
      return 0
    fi
    if command -v "$bin" >/dev/null 2>&1; then
      command -v "$bin"
      return 0
    fi
  done
  return 1
}

CHROME_PATH="$(find_chrome)" || {
  echo "ERR: Chrome/Chromium introuvable." >&2
  exit 1
}

# Liste nom:port pour compat macOS (bash 3.x sans assoc arrays)
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

start_instance() {
  local name="$1"
  local port="$2"
  local profile_dir="$DIR/.chrome-${name}"
  mkdir -p "$profile_dir"

  if lsof -Pi :"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "Chrome ${name} déjà actif sur le port ${port} (profil ${profile_dir})."
    return 0
  fi

  nohup "$CHROME_PATH" \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port="$port" \
    --remote-allow-origins="*" \
    --user-data-dir="$profile_dir" \
    --no-first-run --no-default-browser-check \
    --disable-features=AutomationControlled \
    about:blank \
    >/tmp/chrome-${name}.log 2>&1 &

  for attempt in $(seq 1 10); do
    sleep 0.5
    if curl -s "http://127.0.0.1:${port}/json/version" >/dev/null 2>&1; then
      echo "Chrome ${name} démarré sur port ${port} (profil ${profile_dir})."
      return 0
    fi
  done
  echo "WARN: Chrome ${name} ne répond pas sur le port ${port} (voir /tmp/chrome-${name}.log)."
}

for entry in "${PORT_LIST[@]}"; do
  name="${entry%%:*}"
  port="${entry##*:}"
  start_instance "$name" "$port"
done

echo "Instances prêtes. Logs : /tmp/chrome-<enseigne>.log"
