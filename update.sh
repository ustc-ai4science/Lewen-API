#!/usr/bin/env bash
#
# One-command incremental update for Semantic Scholar data.
#
# Usage:
#   bash update.sh              # Update to the latest S2 release
#   bash update.sh 2026-03-10   # Update to a specific target date
#
# Prerequisites:
#   - corpus/current_release.txt exists with the current release date
#   - S2_API_KEY configured in .env
#   - Qdrant server running (for vector updates)
#   - GPU available (for BGE-M3 encoding)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RELEASE_FILE="corpus/current_release.txt"
END_TARGET="${1:-latest}"

# ── Preflight checks ─────────────────────────────────────────────

if [ ! -f "$RELEASE_FILE" ]; then
    echo "❌ $RELEASE_FILE not found."
    echo "   Create it with your current S2 release date, e.g.:"
    echo "   echo '2026-01-27' > $RELEASE_FILE"
    exit 1
fi

CURRENT_RELEASE="$(cat "$RELEASE_FILE" | tr -d '[:space:]')"
if [ -z "$CURRENT_RELEASE" ]; then
    echo "❌ $RELEASE_FILE is empty."
    exit 1
fi

echo "═══════════════════════════════════════════════════════════"
echo "  S2 Incremental Update"
echo "  Current release: $CURRENT_RELEASE"
echo "  Target:          $END_TARGET"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Download incremental diffs ────────────────────────────

echo "📥 Step 1: Downloading incremental diffs..."
echo ""

DOWNLOAD_LOG=$(mktemp)
trap "rm -f '$DOWNLOAD_LOG'" EXIT

python build_corpus/data/download_incremental_diffs.py \
    --start "$CURRENT_RELEASE" \
    --end "$END_TARGET" 2>&1 | tee "$DOWNLOAD_LOG"

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
    echo "✅ Already up to date (current: $CURRENT_RELEASE)"
    exit 0
fi

echo ""
echo "   Downloaded: $CURRENT_RELEASE → $END_RELEASE"
echo "   Directory:  $INCR_DIR"
echo ""

# ── Step 2: Merge into SQLite + FTS5 + Qdrant ────────────────────

echo "🔄 Step 2: Merging incremental diffs (SQLite + FTS5 + Qdrant)..."
echo ""

python build_corpus/merge_incremental.py "$INCR_DIR" || {
    echo ""
    echo "❌ Merge failed. Current release NOT updated."
    exit 1
}

echo ""

# ── Step 3: Update version tracking ──────────────────────────────

echo "$END_RELEASE" > "$RELEASE_FILE"
echo "📌 Updated $RELEASE_FILE → $END_RELEASE"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ Update complete: $CURRENT_RELEASE → $END_RELEASE"
echo "═══════════════════════════════════════════════════════════"
