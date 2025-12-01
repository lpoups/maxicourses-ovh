#!/bin/bash
set -e

# Wrapper to run the pipeline on OVH server with CDP
# Usage: ./run_pipeline_server.sh <EAN> [args...]

export USE_CDP=1
export CDP_URL="http://127.0.0.1:9222"

# Ensure we are in the right directory (maxicourses_test)
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -z "$1" ]; then
    echo "Usage: $0 <EAN> [args...]"
    exit 1
fi

echo "🚀 Running pipeline for EAN $1 on OVH..."
python3 pipeline/run_pipeline.py "$@"
