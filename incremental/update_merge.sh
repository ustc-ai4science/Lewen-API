#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

RELEASE_FILE="corpus/current_release.txt"
INCR_DIR="${1:-}"

if [ -z "$INCR_DIR" ]; then
    echo "❌ Missing incremental directory."
    echo "   Usage: bash incremental/update_merge.sh PaperData/incremental/2026-01-27_to_2026-03-10"
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
DIR_NAME="$(basename "$INCR_DIR")"
START_RELEASE="${DIR_NAME%%_to_*}"
END_RELEASE="${DIR_NAME##*_to_}"

echo "═══════════════════════════════════════════════════════════"
echo "  S2 Incremental SQLite + FTS Merge"
echo "  Current release: $CURRENT_RELEASE"
echo "  Merge range:     $START_RELEASE -> $END_RELEASE"
echo "  Directory:       $INCR_DIR"
echo "═══════════════════════════════════════════════════════════"
echo ""

python -u incremental/sqlite_fts_merge.py "$INCR_DIR"

echo ""
echo "✅ SQLite + FTS merge complete."
echo "   Qdrant task: $INCR_DIR/_qdrant_task.json"
echo "   current_release not updated yet."
