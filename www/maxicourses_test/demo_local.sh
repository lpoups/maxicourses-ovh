#!/usr/bin/env bash
set -euo pipefail

EAN="${1:-7613035676497}"
DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$DIR/state"

# Ensure logos for local static serving
mkdir -p "$DIR/logos"
cp -f ../maxicourses-web/logos/* "$DIR/logos/" 2>/dev/null || true

# Start API server in background if not running
if ! lsof -i :5001 >/dev/null 2>&1; then
  echo "Starting API on 5001..."
  (cd "$DIR" && python3 server.py) &
  SERVER_PID=$!
  # Wait for readiness
  for i in {1..20}; do
    sleep 0.5
    curl -s "http://127.0.0.1:5001/" >/dev/null && break || true
  done
fi

# Fetch comparison via API (headful Chrome for anti-bot)
curl -s "http://127.0.0.1:5001/api/compare?ean=${EAN}&headless=0&use_chrome=1&state_dir=${STATE_DIR}" \
  > "$DIR/results.json"
echo "WROTE $DIR/results.json"

# Serve static test page
if ! lsof -i :8001 >/dev/null 2>&1; then
  echo "Serving test page on http://localhost:8001/index.html"
  (cd "$DIR" && python3 -m http.server 8001) &
fi

# Open browser
python3 - <<'PY'
import webbrowser; webbrowser.open('http://localhost:8001/index.html')
PY

echo "Done. If pages demand captcha, redo cookies via: python3 maxicourses_test/login_and_save_state.py <site>"

