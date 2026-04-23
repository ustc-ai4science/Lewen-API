from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from tqdm import tqdm

from common import QDRANT_TASK_FILE_NAME, save_json_atomic

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

INSERT_BATCH_SIZE = 5000
DELETE_BATCH_SIZE = 1000


def _load_task(incr_dir: Path) -> tuple[Path, dict]:
    task_path = incr_dir / QDRANT_TASK_FILE_NAME
    if not task_path.exists():
        raise FileNotFoundError(f"Qdrant task file not found: {task_path}")
    with open(task_path, "r", encoding="utf-8") as fh:
        return task_path, json.load(fh)


def _save_task(task_path: Path, task: dict) -> None:
    save_json_atomic(task_path, task)


def load_incremental_qdrant(incr_dir: Path, embeddings_dir: Path | None = None, shards: list[int] | None = None) -> None:
    from core.retrieve.dense import delete_vectors, ensure_index, insert_vectors

    task_path, task = _load_task(incr_dir)
    delete_ids = list(dict.fromkeys(task.get("delete_paper_ids", [])))

    in_dir = embeddings_dir or (incr_dir / "qdrant_embeddings")
    if not in_dir.exists():
        print(f"❌ Incremental embeddings directory not found: {in_dir}", flush=True)
        sys.exit(1)

    npz_files = sorted(
        path
        for path in in_dir.glob("incremental_embeddings_shard_*.npz")
        if not path.name.endswith(".checkpoint.npz")
    )
    if shards is not None:
        wanted = {in_dir / f"incremental_embeddings_shard_{shard}.npz" for shard in shards}
        npz_files = [path for path in npz_files if path in wanted]
    if not npz_files:
        print(f"❌ No incremental_embeddings_shard_*.npz files in {in_dir}", flush=True)
        sys.exit(1)

    if delete_ids:
        print(f"🗑️ Deleting {len(delete_ids):,} vectors from Qdrant...", flush=True)
        for i in tqdm(
            range(0, len(delete_ids), DELETE_BATCH_SIZE),
            desc="[incremental qdrant] delete",
            unit="batch",
            dynamic_ncols=True,
            ascii=True,
        ):
            delete_vectors(delete_ids[i : i + DELETE_BATCH_SIZE])

    total_inserted = 0
    t0 = time.time()
    print(f"🚀 Loading {len(npz_files)} incremental embedding shard(s) into Qdrant...", flush=True)
    for npz_path in npz_files:
        data = dict(np.load(npz_path, allow_pickle=True))
        paper_ids = data["paper_ids"].tolist()
        vectors = data["vectors"]
        if len(paper_ids) != len(vectors):
            raise RuntimeError(f"Mismatch in {npz_path}: {len(paper_ids)} ids vs {len(vectors)} vectors")

        for i in tqdm(
            range(0, len(paper_ids), INSERT_BATCH_SIZE),
            desc=f"Insert {npz_path.name}",
            unit="batch",
            leave=False,
            dynamic_ncols=True,
            ascii=True,
        ):
            batch_ids = paper_ids[i : i + INSERT_BATCH_SIZE]
            batch_vecs = vectors[i : i + INSERT_BATCH_SIZE]
            insert_vectors(batch_ids, batch_vecs)
            total_inserted += len(batch_ids)

    elapsed = time.time() - t0
    print(
        f"🎉 Incremental Qdrant load complete: {total_inserted:,} vectors in {elapsed:.1f}s "
        f"({total_inserted / elapsed:.0f} vectors/s)",
        flush=True,
    )
    ensure_index()

    task.setdefault("task_status", {})
    task["task_status"]["loaded"] = True
    _save_task(task_path, task)
    print(f"✅ Marked Qdrant task as loaded: {task_path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load incremental embedding shards into Qdrant")
    parser.add_argument("incr_dir", type=Path, help="Path to incremental dir")
    parser.add_argument("--embeddings-dir", type=Path, default=None, help="Path to incremental embeddings dir")
    parser.add_argument("--shards", type=str, default=None, help="Comma-separated shard indices to load")
    args = parser.parse_args()

    shard_list = None
    if args.shards:
        shard_list = [int(item.strip()) for item in args.shards.split(",")]

    load_incremental_qdrant(args.incr_dir, embeddings_dir=args.embeddings_dir, shards=shard_list)
