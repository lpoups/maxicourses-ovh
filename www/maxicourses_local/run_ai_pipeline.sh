#!/bin/zsh
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: ./run_ai_pipeline.sh <EAN>" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

if [ -z "${OPENAI_API_KEY:-}" ]; then
  CONFIG_KEY=$(OPENAI_CONFIG_PATH="$SCRIPT_DIR/ai_helpers.toml" python3 <<'PY'
import os
import pathlib
import sys

try:
    import tomllib  # Python ≥ 3.11
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

path_value = os.environ.get("OPENAI_CONFIG_PATH")
if not path_value:
    sys.exit(0)

path = pathlib.Path(path_value)
if not path.exists():
    sys.exit(0)

try:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
except Exception:  # pragma: no cover
    sys.exit(0)

key = data.get("openai", {}).get("api_key") if isinstance(data, dict) else None
if isinstance(key, str) and key.strip():
    sys.stdout.write(key.strip())
PY
  ) || CONFIG_KEY=""

  if [ -z "${CONFIG_KEY:-}" ]; then
    echo "Erreur : définir OPENAI_API_KEY (export ou ai_helpers.toml) avant de lancer ce script." >&2
    exit 1
  fi

  export OPENAI_API_KEY="$CONFIG_KEY"
fi

export USE_AI_ASSIST=${USE_AI_ASSIST:-true}
export USE_CDP=${USE_CDP:-1}

cd "$SCRIPT_DIR"

python3 pipeline/run_pipeline.py --ean "$1"
