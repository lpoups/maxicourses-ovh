#!/usr/bin/env bash
set -euo pipefail

# Snapshot all project files at time T into maxicourses_test/snapshots
# Run from anywhere.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="${SCRIPT_DIR}"/..
SNAP_DIR="${SCRIPT_DIR}/snapshots"
mkdir -p "${SNAP_DIR}"

stamp="$(date +%Y%m%d_%H%M%S)"
archive="${SNAP_DIR}/snap_${stamp}.tar.gz"

# Create archive of the whole workspace (parent dir of maxicourses_test)
# Exclude the snapshots dir itself to avoid recursion
tar -czf "${archive}" \
  --exclude="${SNAP_DIR}" \
  -C "${BASE_DIR}" .

# Write checksum
if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "${archive}" > "${archive}.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${archive}" > "${archive}.sha256"
fi

echo "SNAPSHOT_CREATED ${archive}"

