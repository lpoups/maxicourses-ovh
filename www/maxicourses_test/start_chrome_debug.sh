#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE_DIR="$DIR/.chrome-debug"
mkdir -p "$PROFILE_DIR"

# Try common Chrome paths
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  CHROME=$(command -v google-chrome || true)
fi
if [[ ! -x "$CHROME" ]]; then
  CHROME=$(command -v chromium || true)
fi
if [[ -z "${CHROME:-}" ]]; then
  echo "ERR: Chrome/Chromium not found" >&2
  exit 1
fi

"$CHROME" \
  --remote-debugging-port=9222 \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run --no-default-browser-check \
  --disable-features=AutomationControlled \
  about:blank >/dev/null 2>&1 &
echo "Chrome started on port 9222 (profile: $PROFILE_DIR)"
