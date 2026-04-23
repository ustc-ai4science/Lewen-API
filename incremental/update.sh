#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

END_TARGET="${1:-latest}"
DOWNLOAD_LOG="$(mktemp)"
trap "rm -f '$DOWNLOAD_LOG'" EXIT

bash incremental/update_download.sh "$END_TARGET" 2>&1 | tee "$DOWNLOAD_LOG"

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
    echo "✅ Already up to date."
    exit 0
fi

bash incremental/update_validate.sh "$END_RELEASE"
bash incremental/update_merge.sh "$INCR_DIR"
bash incremental/update_qdrant_incremental.sh "$INCR_DIR"
