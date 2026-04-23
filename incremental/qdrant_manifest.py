from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from common import QDRANT_TASK_FILE_NAME, iter_diff_files, save_json_atomic
import config


def build_qdrant_task(incr_dir: Path) -> dict[str, Any]:
    conn = sqlite3.connect(config.PAPERS_DB_PATH)
    cur = conn.cursor()
    arxiv_paper_ids = {row[0] for row in cur.execute("SELECT paper_id FROM arxiv_to_paper")}
    corpus_to_paper = dict(cur.execute("SELECT corpus_id, paper_id FROM corpus_id_mapping"))
    conn.close()

    papers_update_ids: set[int] = set()
    abstracts_update_ids: set[int] = set()
    delete_paper_ids: set[str] = set()

    for rec in iter_diff_files(incr_dir / "papers" / "updates", desc="[qdrant task] papers updates"):
        corpus_id = rec.get("corpusid")
        if corpus_id is None:
            continue
        try:
            corpus_id = int(corpus_id)
        except (TypeError, ValueError):
            continue
        paper_id = corpus_to_paper.get(corpus_id)
        if not paper_id or paper_id not in arxiv_paper_ids:
            continue
        ext_ids = rec.get("externalids") or {}
        if ext_ids.get("ArXiv") or ext_ids.get("arXiv"):
            papers_update_ids.add(corpus_id)

    for rec in iter_diff_files(incr_dir / "abstracts" / "updates", desc="[qdrant task] abstracts updates"):
        corpus_id = rec.get("corpusid")
        if corpus_id is None:
            continue
        try:
            corpus_id = int(corpus_id)
        except (TypeError, ValueError):
            continue
        paper_id = corpus_to_paper.get(corpus_id)
        if paper_id and paper_id in arxiv_paper_ids:
            abstracts_update_ids.add(corpus_id)

    for rec in iter_diff_files(incr_dir / "paper-ids" / "deletes", desc="[qdrant task] paper-ids deletes"):
        paper_id = rec.get("sha")
        if paper_id and paper_id in arxiv_paper_ids:
            delete_paper_ids.add(str(paper_id))

    for dataset in ("papers", "abstracts"):
        for rec in iter_diff_files(incr_dir / dataset / "deletes", desc=f"[qdrant task] {dataset} deletes"):
            corpus_id = rec.get("corpusid")
            if corpus_id is None:
                continue
            try:
                corpus_id = int(corpus_id)
            except (TypeError, ValueError):
                continue
            paper_id = corpus_to_paper.get(corpus_id)
            if paper_id and paper_id in arxiv_paper_ids:
                delete_paper_ids.add(paper_id)

    upsert_ids = papers_update_ids | abstracts_update_ids
    task = {
        "upsert_corpus_ids": sorted(upsert_ids),
        "delete_paper_ids": sorted(delete_paper_ids),
        "task_status": {
            "manifest_built": True,
            "encoded_shards": [],
            "loaded": False,
        },
        "summary": {
            "arxiv_paper_count": len(arxiv_paper_ids),
            "papers_update_arxiv_count": len(papers_update_ids),
            "abstracts_update_arxiv_count": len(abstracts_update_ids),
            "qdrant_upsert_arxiv_count": len(upsert_ids),
            "qdrant_delete_arxiv_count": len(delete_paper_ids),
        },
    }
    return task


def write_qdrant_task(incr_dir: Path) -> Path:
    task_path = incr_dir / QDRANT_TASK_FILE_NAME
    task = build_qdrant_task(incr_dir)
    save_json_atomic(task_path, task)
    print(json.dumps(task["summary"], ensure_ascii=False, indent=2), flush=True)
    print(f"✅ Qdrant task written: {task_path}", flush=True)
    return task_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Qdrant task manifest for one incremental directory.")
    parser.add_argument("incr_dir", type=Path, help="Path to incremental dir")
    args = parser.parse_args()
    write_qdrant_task(args.incr_dir)
