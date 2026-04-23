from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from tqdm import tqdm

from common import QDRANT_TASK_FILE_NAME, save_json_atomic

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

ENCODE_BATCH_SIZE = 64
SELECT_BATCH_SIZE = 5000
CHECKPOINT_EVERY = 200
LOAD_CACHE_CHUNK_BATCHES = 20


def _load_input_cache(cache_path: Path) -> list[tuple[str, str, str]] | None:
    if not cache_path.exists():
        return None
    data = dict(np.load(cache_path, allow_pickle=True))
    paper_ids = data["paper_ids"].tolist()
    titles = data["titles"].tolist()
    abstracts = data["abstracts"].tolist()
    return list(zip(paper_ids, titles, abstracts))


def _save_input_cache(cache_path: Path, rows: list[tuple[str, str, str]]) -> None:
    tmp_path = cache_path.with_suffix(".tmp.npz")
    paper_ids = np.array([row[0] for row in rows], dtype=object)
    titles = np.array([row[1] for row in rows], dtype=object)
    abstracts = np.array([row[2] for row in rows], dtype=object)
    with open(tmp_path, "wb") as fh:
        np.savez_compressed(fh, paper_ids=paper_ids, titles=titles, abstracts=abstracts)
    tmp_path.replace(cache_path)


def _load_rows_from_part(part_path: Path) -> list[tuple[str, str, str]]:
    data = dict(np.load(part_path, allow_pickle=True))
    paper_ids = data["paper_ids"].tolist()
    titles = data["titles"].tolist()
    abstracts = data["abstracts"].tolist()
    return list(zip(paper_ids, titles, abstracts))


def _save_rows_part(part_path: Path, rows: list[tuple[str, str, str]]) -> None:
    tmp_path = part_path.with_suffix(".tmp.npz")
    paper_ids = np.array([row[0] for row in rows], dtype=object)
    titles = np.array([row[1] for row in rows], dtype=object)
    abstracts = np.array([row[2] for row in rows], dtype=object)
    with open(tmp_path, "wb") as fh:
        np.savez_compressed(fh, paper_ids=paper_ids, titles=titles, abstracts=abstracts)
    tmp_path.replace(part_path)


def _load_from_chunk_parts(parts_dir: Path) -> tuple[list[tuple[str, str, str]], int]:
    rows: list[tuple[str, str, str]] = []
    loaded_batches = 0
    for part_path in sorted(parts_dir.glob("part_*.npz")):
        rows.extend(_load_rows_from_part(part_path))
        loaded_batches += 1
    return rows, loaded_batches


def _load_task(incr_dir: Path) -> tuple[Path, dict]:
    task_path = incr_dir / QDRANT_TASK_FILE_NAME
    if not task_path.exists():
        raise FileNotFoundError(f"Qdrant task file not found: {task_path}")
    with open(task_path, "r", encoding="utf-8") as fh:
        return task_path, json.load(fh)


def _mark_encoded_shard(task_path: Path, task: dict, shard: int) -> None:
    status = task.setdefault("task_status", {})
    encoded_shards = set(status.get("encoded_shards", []))
    encoded_shards.add(shard)
    status["encoded_shards"] = sorted(encoded_shards)
    save_json_atomic(task_path, task)


def _load_pending_arxiv_papers(
    incr_dir: Path,
    shard: int,
    total_shards: int,
    *,
    cache_path: Path,
) -> tuple[Path, dict, list[tuple[str, str, str]]]:
    task_path, task = _load_task(incr_dir)
    cached_rows = _load_input_cache(cache_path)
    if cached_rows is not None:
        print(f"   📂 Reusing input cache: {cache_path.name} ({len(cached_rows):,} papers)", flush=True)
        return task_path, task, cached_rows

    corpus_ids = sorted(dict.fromkeys(task.get("upsert_corpus_ids", [])))
    if not corpus_ids:
        return task_path, task, []

    if total_shards > 1:
        shard_corpus_ids = [cid for idx, cid in enumerate(corpus_ids) if idx % total_shards == shard]
    else:
        shard_corpus_ids = corpus_ids

    parts_dir = cache_path.with_suffix("")
    parts_dir = parts_dir.parent / f"{parts_dir.name}.parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    rows, completed_parts = _load_from_chunk_parts(parts_dir)
    if completed_parts:
        print(
            f"   📂 Resuming load cache from {completed_parts} part(s): "
            f"{len(rows):,} rows already cached",
            flush=True,
        )

    conn = sqlite3.connect(config.PAPERS_DB_PATH, timeout=60)
    try:
        print(
            f"   Loading shard corpus_ids from SQLite: "
            f"{len(shard_corpus_ids):,}/{len(corpus_ids):,} (shard {shard}/{total_shards})",
            flush=True,
        )
        start_index = completed_parts * LOAD_CACHE_CHUNK_BATCHES * SELECT_BATCH_SIZE
        with tqdm(
            total=len(shard_corpus_ids),
            desc="[incremental qdrant] load",
            unit="paper",
            dynamic_ncols=True,
            ascii=True,
            mininterval=0.5,
            initial=min(start_index, len(shard_corpus_ids)),
        ) as pbar:
            chunk_rows: list[tuple[str, str, str]] = []
            chunk_batch_count = 0
            part_index = completed_parts
            for i in range(start_index, len(shard_corpus_ids), SELECT_BATCH_SIZE):
                batch_ids = shard_corpus_ids[i : i + SELECT_BATCH_SIZE]
                placeholders = ",".join("?" for _ in batch_ids)
                cur = conn.execute(
                    f"""SELECT paper_id, title, abstract
                       FROM paper_metadata
                       WHERE corpus_id IN ({placeholders})""",
                    batch_ids,
                )
                batch_rows = [
                    (paper_id, title or "", abstract or "")
                    for paper_id, title, abstract in cur.fetchall()
                ]
                rows.extend(batch_rows)
                chunk_rows.extend(batch_rows)
                chunk_batch_count += 1
                pbar.update(len(batch_ids))
                pbar.set_postfix(loaded=f"{len(rows):,}", parts=part_index)

                if chunk_batch_count >= LOAD_CACHE_CHUNK_BATCHES:
                    part_path = parts_dir / f"part_{part_index:05d}.npz"
                    _save_rows_part(part_path, chunk_rows)
                    tqdm.write(
                        f"   💾 Saved load cache part {part_index + 1}: {len(chunk_rows):,} rows",
                    )
                    part_index += 1
                    chunk_rows = []
                    chunk_batch_count = 0
                    pbar.set_postfix(loaded=f"{len(rows):,}", parts=part_index)

            if chunk_rows:
                part_path = parts_dir / f"part_{part_index:05d}.npz"
                _save_rows_part(part_path, chunk_rows)
                tqdm.write(
                    f"   💾 Saved load cache part {part_index + 1}: {len(chunk_rows):,} rows",
                )
        print(f"   Deduplicating {len(rows):,} rows...", flush=True)
        rows = list(dict.fromkeys(rows))
        print(f"   Sorting {len(rows):,} shard rows...", flush=True)
        rows.sort(key=lambda row: row[0])
        print(f"   💾 Saving input cache: {cache_path.name}", flush=True)
        _save_input_cache(cache_path, rows)
        return task_path, task, rows
    finally:
        conn.close()


def encode_incremental_qdrant(
    incr_dir: Path,
    gpu_id: int,
    shard: int,
    total_shards: int,
    output_dir: Path | None = None,
    batch_size: int = ENCODE_BATCH_SIZE,
) -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    config.GPU_DEVICE_ID = 0

    from core.retrieve.embedding import encode

    out_dir = output_dir or (incr_dir / "qdrant_embeddings")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"incremental_embeddings_shard_{shard}.npz"
    checkpoint_path = out_path.with_suffix(out_path.suffix + ".checkpoint")
    input_cache_path = out_dir / f"incremental_inputs_shard_{shard}.npz"

    print(f"🚀 Encode incremental Qdrant embeddings (GPU {gpu_id}, shard {shard}/{total_shards}) -> {out_path}", flush=True)
    task_path, task, papers = _load_pending_arxiv_papers(
        incr_dir,
        shard=shard,
        total_shards=total_shards,
        cache_path=input_cache_path,
    )
    print(f"   Found {len(papers):,} pending arXiv papers for this shard", flush=True)
    if not papers:
        print("⚠️ No pending arXiv papers found. Skipping.", flush=True)
        _mark_encoded_shard(task_path, task, shard)
        return

    print("   Loading BGE-M3 model (may take 10-30s)...", flush=True)
    encode(["warmup"])
    print("✅ BGE-M3 model ready.", flush=True)

    paper_ids: list[str] = []
    all_vectors: list[np.ndarray] = []
    start_offset = 0

    if checkpoint_path.exists():
        print(f"   📂 Resuming from checkpoint: {checkpoint_path.name}", flush=True)
        ckpt = dict(np.load(checkpoint_path, allow_pickle=True))
        paper_ids = ckpt["paper_ids"].tolist()
        all_vectors = [ckpt["vectors"]]
        start_offset = len(paper_ids)
        print(f"   Resumed: {start_offset:,} papers already encoded", flush=True)

    t0 = time.time()
    for batch_idx, batch_start in enumerate(
        tqdm(
            range(start_offset, len(papers), batch_size),
            desc=f"Encode incremental (shard {shard})",
            unit="batch",
            dynamic_ncols=True,
            mininterval=1.0,
        ),
        start=1,
    ):
        batch = papers[batch_start : batch_start + batch_size]
        texts = [f"{title} {abstract}".strip() for _, title, abstract in batch]
        paper_ids.extend(pid for pid, _, _ in batch)
        vectors = encode(texts, batch_size=batch_size)
        all_vectors.append(vectors)

        if batch_idx % CHECKPOINT_EVERY == 0:
            vec_stack = np.vstack(all_vectors).astype(np.float32)
            ids_arr = np.array(paper_ids, dtype=object)
            np.savez_compressed(checkpoint_path, paper_ids=ids_arr, vectors=vec_stack)
            tqdm.write(f"   💾 Checkpoint saved ({len(paper_ids):,} papers)")

    vectors_arr = np.vstack(all_vectors).astype(np.float32)
    paper_ids_arr = np.array(paper_ids, dtype=object)
    np.savez_compressed(out_path, paper_ids=paper_ids_arr, vectors=vectors_arr)

    if checkpoint_path.exists():
        checkpoint_path.unlink()
        print("   🗑️ Checkpoint removed (complete)", flush=True)

    _mark_encoded_shard(task_path, task, shard)
    elapsed = time.time() - t0
    print(
        f"🎉 Incremental shard {shard} complete: {len(paper_ids):,} vectors in {elapsed:.1f}s "
        f"({len(paper_ids) / elapsed:.0f} papers/s) -> {out_path}",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Encode incremental Qdrant embeddings to NPZ")
    parser.add_argument("incr_dir", type=Path, help="Path to incremental dir")
    parser.add_argument("--gpu", type=int, required=True, help="GPU device ID")
    parser.add_argument("--shard", type=int, default=0, help="Shard index")
    parser.add_argument("--total-shards", type=int, default=1, help="Total shards")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory")
    parser.add_argument("--batch-size", type=int, default=ENCODE_BATCH_SIZE, help="Encoding batch size")
    args = parser.parse_args()

    encode_incremental_qdrant(
        incr_dir=args.incr_dir,
        gpu_id=args.gpu,
        shard=args.shard,
        total_shards=args.total_shards,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
    )
