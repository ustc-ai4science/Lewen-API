#!/usr/bin/env bash
#
# Download incremental diffs only.
#
# Usage:
#   bash update_download.sh              # Download up to latest release
#   bash update_download.sh 2026-03-10   # Download up to a specific target date

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RELEASE_FILE="corpus/current_release.txt"
END_TARGET="${1:-latest}"

if [ ! -f "$RELEASE_FILE" ]; then
    echo "❌ $RELEASE_FILE not found."
    echo "   Create it with your current S2 release date, e.g.:"
    echo "   echo '2026-01-27' > $RELEASE_FILE"
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

python -u build_corpus/data/download_incremental_diffs.py \
    --start "$CURRENT_RELEASE" \
    --end "$END_TARGET"

