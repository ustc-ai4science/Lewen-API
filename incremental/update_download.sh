#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

RELEASE_FILE="corpus/current_release.txt"
END_TARGET="${1:-latest}"

if [ ! -f "$RELEASE_FILE" ]; then
    echo "❌ $RELEASE_FILE not found."
    exit 1
fi

CURRENT_RELEASE="$(tr -d '[:space:]' < "$RELEASE_FILE")"
if [ -z "$CURRENT_RELEASE" ]; then
    echo "❌ $RELEASE_FILE is empty."
    exit 1
fi

echo "═══════════════════════════════════════════════════════════"
echo "  S2 Incremental Download"
echo "  Current release: $CURRENT_RELEASE"
echo "  Target:          $END_TARGET"
echo "═══════════════════════════════════════════════════════════"
echo ""

python -u incremental/download.py --start "$CURRENT_RELEASE" --end "$END_TARGET"
