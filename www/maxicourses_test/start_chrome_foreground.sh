#!/usr/bin/env bash
# Headless Chrome remote debugging bootstrapper for OVH (Foreground for Systemd).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE_DIR="${CHROME_PROFILE_DIR:-$DIR/.chrome-debug}"
PORT="${CHROME_REMOTE_PORT:-9222}"
ADDRESS="${CHROME_REMOTE_ADDRESS:-127.0.0.1}"

mkdir -p "$PROFILE_DIR"

find_chrome() {
  for bin in "${CHROME_BIN:-}" google-chrome-stable google-chrome chromium chromium-browser; do
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
  echo "ERR: Chrome/Chromium introuvable sur ce serveur." >&2
  exit 1
}

# Cleanup previous locks if any (careful with this, but for systemd it's usually fine)
rm -f "$PROFILE_DIR/SingletonLock"

mkdir -p "$PROFILE_DIR/First Run"

echo "Démarrage de Chrome headless ($CHROME_PATH) sur $ADDRESS:$PORT (Foreground)..."
CMD=(
  "$CHROME_PATH"
  --disable-gpu
  --disable-dev-shm-usage
  --no-sandbox
  --disable-setuid-sandbox
  --use-gl=swiftshader
  --no-first-run
  --no-default-browser-check
  --window-size=1366,768
  --disable-blink-features=AutomationControlled
  --remote-debugging-port="$PORT"
  --remote-allow-origins="*"
  --remote-allow-http://127.0.0.1:*
  --remote-allow-http://localhost:*
  --user-data-dir="$PROFILE_DIR"
  --enable-logging=stderr
  --v=0
  about:blank
)

XVFB_BIN=$(command -v xvfb-run || true)
if [[ -n "$XVFB_BIN" ]]; then
  # exec replaces the shell with the command, keeping the PID for systemd
  exec "$XVFB_BIN" -a --server-args="-screen 0 1366x768x24" "${CMD[@]}"
else
  exec "${CMD[@]}"
fi
