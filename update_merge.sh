#!/usr/bin/env bash
#
# Merge an already-downloaded incremental diff directory only.
#
# Usage:
#   bash update_merge.sh PaperData/incremental/2026-01-27_to_2026-03-10

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RELEASE_FILE="corpus/current_release.txt"
INCR_DIR="${1:-}"

if [ -z "$INCR_DIR" ]; then
    echo "❌ Missing incremental directory."
    echo "   Usage: bash update_merge.sh PaperData/incremental/2026-01-27_to_2026-03-10"
    exit 1
fi

if [ ! -d "$INCR_DIR" ]; then
    echo "❌ Incremental directory not found: $INCR_DIR"
    exit 1
fi

if [ ! -f "$RELEASE_FILE" ]; then
    echo "❌ $RELEASE_FILE not found."
    exit 1
fi

CURRENT_RELEASE="$(tr -d '[:space:]' < "$RELEASE_FILE")"
if [ -z "$CURRENT_RELEASE" ]; then
    echo "❌ $RELEASE_FILE is empty."
    exit 1
fi

DIR_NAME="$(basename "$INCR_DIR")"
START_RELEASE="${DIR_NAME%%_to_*}"
END_RELEASE="${DIR_NAME##*_to_}"

if [ "$START_RELEASE" = "$DIR_NAME" ] || [ "$END_RELEASE" = "$DIR_NAME" ]; then
    echo "❌ Cannot infer release range from directory name: $DIR_NAME"
    echo "   Expected format: START_to_END"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════"
echo "  S2 Incremental Merge"
echo "  Current release: $CURRENT_RELEASE"
echo "  Merge range:     $START_RELEASE -> $END_RELEASE"
echo "  Directory:       $INCR_DIR"
echo "═══════════════════════════════════════════════════════════"
echo ""

if [ "$CURRENT_RELEASE" != "$START_RELEASE" ]; then
    echo "⚠️ current release ($CURRENT_RELEASE) does not match incremental start ($START_RELEASE)"
    echo "   Continuing anyway because merge is explicitly requested."
    echo ""
fi

python -u build_corpus/merge_incremental.py "$INCR_DIR"

echo "$END_RELEASE" > "$RELEASE_FILE"
echo ""
echo "📌 Updated $RELEASE_FILE -> $END_RELEASE"
echo "✅ Merge complete."

