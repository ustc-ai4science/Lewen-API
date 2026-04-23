#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

RELEASE_FILE="corpus/current_release.txt"
INCR_DIR="${1:-}"
GPU_LIST="${2:-0,2,3}"
BATCH_SIZE="${QDRANT_INCREMENTAL_ENCODE_BATCH_SIZE:-64}"

if [ -z "$INCR_DIR" ]; then
    echo "❌ Missing incremental directory."
    echo "   Usage: bash incremental/update_qdrant_incremental.sh PaperData/incremental/2026-01-27_to_2026-03-10 [gpu_list]"
    exit 1
fi

if [ ! -d "$INCR_DIR" ]; then
    echo "❌ Incremental directory not found: $INCR_DIR"
    exit 1
fi

if [ ! -f "$INCR_DIR/_qdrant_task.json" ]; then
    echo "❌ Missing $INCR_DIR/_qdrant_task.json"
    echo "   Run incremental/update_merge.sh first."
    exit 1
fi

IFS=',' read -r -a GPUS <<< "$GPU_LIST"
TOTAL_SHARDS="${#GPUS[@]}"
if [ "$TOTAL_SHARDS" -le 0 ]; then
    echo "❌ No GPUs specified."
    exit 1
fi

DIR_NAME="$(basename "$INCR_DIR")"
END_RELEASE="${DIR_NAME##*_to_}"

echo "═══════════════════════════════════════════════════════════"
echo "  Incremental Qdrant Update"
echo "  Directory:   $INCR_DIR"
echo "  GPUs:        $GPU_LIST"
echo "  Shards:      $TOTAL_SHARDS"
echo "  Batch size:  $BATCH_SIZE"
echo "═══════════════════════════════════════════════════════════"
echo ""

for i in "${!GPUS[@]}"; do
    GPU_ID="${GPUS[$i]}"
    echo "🚀 Launch shard $i/$TOTAL_SHARDS on GPU $GPU_ID"
    python -u incremental/qdrant_encode.py \
        "$INCR_DIR" \
        --gpu "$GPU_ID" \
        --shard "$i" \
        --total-shards "$TOTAL_SHARDS" \
        --batch-size "$BATCH_SIZE" &
done

wait
echo ""
echo "✅ All incremental embedding shards encoded."

python -u incremental/qdrant_load.py "$INCR_DIR"

if [ -f "$RELEASE_FILE" ]; then
    echo "$END_RELEASE" > "$RELEASE_FILE"
    echo ""
    echo "📌 Updated $RELEASE_FILE -> $END_RELEASE"
fi

echo "✅ Incremental Qdrant update complete."
