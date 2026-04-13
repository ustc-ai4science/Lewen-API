#!/usr/bin/env bash
#
# One-command wrapper: download incremental diffs, validate them, then merge.
#
# Preferred split entrypoints:
#   bash update_download.sh [END_RELEASE]
#   bash update_validate.sh [END_RELEASE]
#   bash update_merge.sh PaperData/incremental/START_to_END
#
# Legacy convenience usage:
#   bash update.sh
#   bash update.sh 2026-03-10

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RELEASE_FILE="corpus/current_release.txt"
END_TARGET="${1:-latest}"

# ── Step 1: Download incremental diffs ────────────────────────────

DOWNLOAD_LOG=$(mktemp)
trap "rm -f '$DOWNLOAD_LOG'" EXIT

bash update_download.sh "$END_TARGET" 2>&1 | tee "$DOWNLOAD_LOG"

DOWNLOAD_EXIT=${PIPESTATUS[0]}
if [ "$DOWNLOAD_EXIT" -ne 0 ]; then
    echo ""
    echo "❌ Download failed."
    exit 1
fi

END_RELEASE=$(grep "^📦 END_RELEASE=" "$DOWNLOAD_LOG" | sed 's/^📦 END_RELEASE=//')
INCR_DIR=$(grep "^📦 INCR_DIR=" "$DOWNLOAD_LOG" | sed 's/^📦 INCR_DIR=//')

if [ -z "$END_RELEASE" ] || [ -z "$INCR_DIR" ]; then
    echo ""
    CURRENT_RELEASE="$(tr -d '[:space:]' < "$RELEASE_FILE")"
    echo "✅ Already up to date (current: $CURRENT_RELEASE)"
    exit 0
fi

echo ""
echo "   Downloaded incremental diffs to: $INCR_DIR"
echo "   Directory:  $INCR_DIR"
echo ""

# ── Step 2: Validate downloaded diffs ─────────────────────────────

bash update_validate.sh "$END_RELEASE" || {
    echo ""
    echo "❌ Validation failed."
    exit 1
}

# ── Step 3: Merge into SQLite + FTS5 + Qdrant ────────────────────

bash update_merge.sh "$INCR_DIR" || {
    echo ""
    echo "❌ Merge failed."
    exit 1
}
