from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

from common import (
    BATCH_SIZE,
    CHECKPOINT_RECORD_CHUNK,
    PROGRESS_FILE_NAME,
    STEP_ABSTRACTS_DELETES,
    STEP_ABSTRACTS_UPDATES,
    STEP_CITATIONS_DELETES,
    STEP_CITATIONS_UPDATES,
    STEP_PAPER_IDS_DELETES,
    STEP_PAPER_IDS_UPDATES,
    STEP_PAPERS_DELETES,
    STEP_PAPERS_UPDATES,
    get_step_offset,
    iter_diff_files,
    load_merge_progress,
    mark_step_completed,
    mark_step_offset,
    normalize_arxiv_id,
    safe_json,
    step_completed,
)
from qdrant_manifest import write_qdrant_task

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.citation.database import (
    delete_by_corpus_ids,
    delete_by_paper_ids,
    delete_citations_by_ids,
    get_connection,
    insert_arxiv_mapping_batch,
    insert_citations_batch,
    insert_corpus_mapping_batch,
    insert_fts_combined_batch,
    insert_fts_title_batch,
    insert_paper_metadata_batch,
)


def _refresh_fts_for_corpus_ids(conn: sqlite3.Connection, corpus_ids: list[int]) -> None:
    if not corpus_ids:
        return
    unique_corpus_ids = list(dict.fromkeys(corpus_ids))
    for i in range(0, len(unique_corpus_ids), BATCH_SIZE):
        corpus_batch = unique_corpus_ids[i : i + BATCH_SIZE]
        placeholders = ",".join("?" for _ in corpus_batch)
        cur = conn.execute(
            f"""SELECT paper_id, title, abstract FROM paper_metadata
               WHERE corpus_id IN ({placeholders})""",
            corpus_batch,
        )
        rows = cur.fetchall()
        if not rows:
            continue

        paper_ids = [paper_id for paper_id, _, _ in rows]
        batch_placeholders = ",".join("?" for _ in paper_ids)
        conn.execute(f"DELETE FROM paper_fts_title WHERE paper_id IN ({batch_placeholders})", paper_ids)
        conn.execute(
            f"DELETE FROM paper_fts_combined WHERE paper_id IN ({batch_placeholders})",
            paper_ids,
        )

        title_batch = [(paper_id, title or "") for paper_id, title, _ in rows]
        combined_batch = [
            (paper_id, f"{(title or '')} {(abstract or '')}".strip())
            for paper_id, title, abstract in rows
        ]
        insert_fts_title_batch(conn, title_batch)
        insert_fts_combined_batch(conn, combined_batch)


def _load_arxiv_corpus_ids(conn: sqlite3.Connection) -> set[int]:
    cur = conn.execute(
        """SELECT pm.corpus_id
           FROM paper_metadata pm
           JOIN arxiv_to_paper ap ON ap.paper_id = pm.paper_id"""
    )
    return {row[0] for row in cur.fetchall()}


def _get_paper_ids_for_corpus_ids(conn: sqlite3.Connection, corpus_ids: list[int]) -> list[str]:
    paper_ids: list[str] = []
    for i in range(0, len(corpus_ids), BATCH_SIZE):
        batch_ids = corpus_ids[i : i + BATCH_SIZE]
        placeholders = ",".join("?" for _ in batch_ids)
        cur = conn.execute(
            f"SELECT paper_id FROM corpus_id_mapping WHERE corpus_id IN ({placeholders})",
            batch_ids,
        )
        paper_ids.extend(row[0] for row in cur.fetchall())
    return paper_ids


def _commit_papers_update_chunk(
    conn: sqlite3.Connection,
    *,
    meta_batch: list[tuple],
    arxiv_batch: list[tuple[str, str]],
    chunk_corpus_ids: list[int],
    chunk_label: str,
) -> None:
    if meta_batch:
        print(f"  ↻ Flushing papers metadata chunk: {len(meta_batch):,} ({chunk_label})", flush=True)
        insert_paper_metadata_batch(conn, meta_batch)
    if arxiv_batch:
        print(f"  ↻ Flushing arXiv mapping chunk: {len(arxiv_batch):,} ({chunk_label})", flush=True)
        insert_arxiv_mapping_batch(conn, arxiv_batch)
    if chunk_corpus_ids:
        print(f"  ↻ Refreshing FTS for {len(chunk_corpus_ids):,} papers ({chunk_label})...", flush=True)
        _refresh_fts_for_corpus_ids(conn, chunk_corpus_ids)
    print(f"  ↻ Committing papers updates chunk: {chunk_label}", flush=True)
    conn.commit()
    print(f"  ✅ Committed papers updates chunk: {chunk_label}", flush=True)


def _commit_abstracts_update_chunk(
    conn: sqlite3.Connection,
    *,
    chunk_corpus_ids: list[int],
    chunk_label: str,
) -> None:
    if chunk_corpus_ids:
        print(
            f"  ↻ Refreshing FTS for {len(chunk_corpus_ids):,} abstract updates ({chunk_label})...",
            flush=True,
        )
        _refresh_fts_for_corpus_ids(conn, chunk_corpus_ids)
    print(f"  ↻ Committing abstracts updates chunk: {chunk_label}", flush=True)
    conn.commit()
    print(f"  ✅ Committed abstracts updates chunk: {chunk_label}", flush=True)


def apply_paper_ids_updates(conn: sqlite3.Connection, updates_dir: Path) -> None:
    batch: list[tuple[int, str]] = []
    count = 0
    for rec in iter_diff_files(updates_dir, desc="[paper-ids] updates"):
        corpus_id = rec.get("corpusid")
        sha = rec.get("sha")
        is_primary = rec.get("primary", False)
        if corpus_id is None or not sha or not is_primary:
            continue
        batch.append((int(corpus_id), str(sha)))
        count += 1
        if len(batch) >= BATCH_SIZE:
            insert_corpus_mapping_batch(conn, batch)
            batch.clear()
    if batch:
        print(f"  ↻ Flushing final paper-ids batch: {len(batch):,}", flush=True)
        insert_corpus_mapping_batch(conn, batch)
    print("  ↻ Committing paper-ids updates...", flush=True)
    conn.commit()
    if count:
        print(f"  ✅ paper-ids updates: {count:,}", flush=True)


def apply_paper_ids_deletes(conn: sqlite3.Connection, deletes_dir: Path) -> None:
    paper_ids: list[str] = []
    for rec in iter_diff_files(deletes_dir, desc="[paper-ids] deletes"):
        paper_id = rec.get("sha")
        if paper_id:
            paper_ids.append(str(paper_id))
    if paper_ids:
        delete_by_paper_ids(conn, paper_ids)
        print("  ↻ Committing paper-ids deletes...", flush=True)
        conn.commit()
        print(f"  ✅ paper-ids deletes: {len(paper_ids):,}", flush=True)


def apply_papers_updates(
    conn: sqlite3.Connection,
    updates_dir: Path,
    progress_path: Path,
    progress_state: dict,
) -> None:
    meta_batch: list[tuple] = []
    arxiv_batch: list[tuple[str, str]] = []
    updated_corpus_ids: list[int] = []
    count = 0
    committed_offset = get_step_offset(progress_state, STEP_PAPERS_UPDATES)
    if committed_offset:
        print(f"  ↻ Resuming {STEP_PAPERS_UPDATES} from committed offset {committed_offset:,}", flush=True)

    corpus_to_sha = dict(conn.execute("SELECT corpus_id, paper_id FROM corpus_id_mapping"))

    for rec in iter_diff_files(updates_dir, desc="[papers] updates"):
        corpus_id = rec.get("corpusid")
        if corpus_id is None:
            continue
        corpus_id = int(corpus_id)
        sha = corpus_to_sha.get(corpus_id)
        if not sha:
            continue

        ext_ids = rec.get("externalids") or {}
        arxiv_id = ext_ids.get("ArXiv") or ext_ids.get("arXiv")
        if not arxiv_id:
            continue

        fos_raw = rec.get("s2fieldsofstudy")
        fos = [item.get("category") for item in fos_raw if item.get("category")] if fos_raw else None

        existing = conn.execute(
            "SELECT abstract, open_access_pdf_json FROM paper_metadata WHERE corpus_id = ?",
            (corpus_id,),
        ).fetchone()
        abstract = existing[0] if existing else None
        oa_pdf = existing[1] if existing else None

        count += 1
        if count <= committed_offset:
            continue

        meta_batch.append((
            sha,
            corpus_id,
            rec.get("title"),
            abstract,
            rec.get("year"),
            rec.get("venue"),
            rec.get("citationcount", 0),
            rec.get("referencecount", 0),
            safe_json(rec.get("authors")),
            safe_json(fos),
            safe_json(rec.get("publicationtypes")),
            rec.get("publicationdate"),
            oa_pdf,
            safe_json(ext_ids),
            safe_json(rec.get("journal")),
        ))
        arxiv_batch.append((normalize_arxiv_id(str(arxiv_id)), sha))
        updated_corpus_ids.append(corpus_id)

        if len(meta_batch) >= BATCH_SIZE:
            insert_paper_metadata_batch(conn, meta_batch)
            meta_batch.clear()
        if len(arxiv_batch) >= BATCH_SIZE:
            insert_arxiv_mapping_batch(conn, arxiv_batch)
            arxiv_batch.clear()

        if len(updated_corpus_ids) >= CHECKPOINT_RECORD_CHUNK:
            chunk_label = f"{count - len(updated_corpus_ids) + 1:,}-{count:,}"
            _commit_papers_update_chunk(
                conn,
                meta_batch=meta_batch,
                arxiv_batch=arxiv_batch,
                chunk_corpus_ids=updated_corpus_ids,
                chunk_label=chunk_label,
            )
            mark_step_offset(progress_path, progress_state, STEP_PAPERS_UPDATES, count)
            meta_batch.clear()
            arxiv_batch.clear()
            updated_corpus_ids.clear()

    if meta_batch or arxiv_batch or updated_corpus_ids:
        chunk_start = max(committed_offset + 1, count - len(updated_corpus_ids) + 1)
        chunk_label = f"{chunk_start:,}-{count:,}" if updated_corpus_ids else "final"
        _commit_papers_update_chunk(
            conn,
            meta_batch=meta_batch,
            arxiv_batch=arxiv_batch,
            chunk_corpus_ids=updated_corpus_ids,
            chunk_label=chunk_label,
        )
        mark_step_offset(progress_path, progress_state, STEP_PAPERS_UPDATES, count)
    if count:
        print(f"  ✅ papers updates: {count:,}", flush=True)


def apply_papers_deletes(conn: sqlite3.Connection, deletes_dir: Path) -> None:
    ids: list[int] = []
    for rec in iter_diff_files(deletes_dir, desc="[papers] deletes"):
        corpus_id = rec.get("corpusid")
        if corpus_id is not None:
            ids.append(int(corpus_id))
    if ids:
        delete_by_corpus_ids(conn, ids)
        print("  ↻ Committing papers deletes...", flush=True)
        conn.commit()
        print(f"  ✅ papers deletes: {len(ids):,}", flush=True)


def apply_abstracts_updates(
    conn: sqlite3.Connection,
    updates_dir: Path,
    progress_path: Path,
    progress_state: dict,
) -> None:
    updated_corpus_ids: list[int] = []
    count = 0
    committed_offset = get_step_offset(progress_state, STEP_ABSTRACTS_UPDATES)
    valid_corpus_ids = _load_arxiv_corpus_ids(conn)
    if committed_offset:
        print(f"  ↻ Resuming {STEP_ABSTRACTS_UPDATES} from committed offset {committed_offset:,}", flush=True)

    for rec in iter_diff_files(updates_dir, desc="[abstracts] updates"):
        corpus_id = rec.get("corpusid")
        if corpus_id is None:
            continue
        corpus_id_int = int(corpus_id)
        if corpus_id_int not in valid_corpus_ids:
            continue
        count += 1
        if count <= committed_offset:
            continue

        abstract = rec.get("abstract")
        oa_info = rec.get("openaccessinfo")
        oa_pdf_json = None
        if oa_info:
            oa_pdf_json = safe_json({"url": oa_info.get("url"), "status": oa_info.get("status")})

        conn.execute(
            """UPDATE paper_metadata
               SET abstract = COALESCE(?, abstract),
                   open_access_pdf_json = COALESCE(?, open_access_pdf_json)
               WHERE corpus_id = ?""",
            (abstract, oa_pdf_json, corpus_id_int),
        )
        updated_corpus_ids.append(corpus_id_int)

        if len(updated_corpus_ids) >= CHECKPOINT_RECORD_CHUNK:
            chunk_label = f"{count - len(updated_corpus_ids) + 1:,}-{count:,}"
            _commit_abstracts_update_chunk(
                conn,
                chunk_corpus_ids=updated_corpus_ids,
                chunk_label=chunk_label,
            )
            mark_step_offset(progress_path, progress_state, STEP_ABSTRACTS_UPDATES, count)
            updated_corpus_ids.clear()

    if updated_corpus_ids:
        chunk_start = max(committed_offset + 1, count - len(updated_corpus_ids) + 1)
        chunk_label = f"{chunk_start:,}-{count:,}"
        _commit_abstracts_update_chunk(
            conn,
            chunk_corpus_ids=updated_corpus_ids,
            chunk_label=chunk_label,
        )
        mark_step_offset(progress_path, progress_state, STEP_ABSTRACTS_UPDATES, count)
    if count:
        print(f"  ✅ abstracts updates: {count:,}", flush=True)


def apply_abstracts_deletes(conn: sqlite3.Connection, deletes_dir: Path) -> None:
    ids: list[int] = []
    for rec in iter_diff_files(deletes_dir, desc="[abstracts] deletes"):
        corpus_id = rec.get("corpusid")
        if corpus_id is not None:
            ids.append(int(corpus_id))
    if ids:
        delete_by_corpus_ids(conn, ids)
        print("  ↻ Committing abstracts deletes...", flush=True)
        conn.commit()
        print(f"  ✅ abstracts deletes (removed from corpus): {len(ids):,}", flush=True)


def apply_citations_updates(
    conn: sqlite3.Connection,
    updates_dir: Path,
    progress_path: Path,
    progress_state: dict,
) -> None:
    valid_corpus_ids = {row[0] for row in conn.execute("SELECT corpus_id FROM corpus_id_mapping")}
    batch: list[tuple[int, int, int]] = []
    count = 0
    committed_offset = get_step_offset(progress_state, STEP_CITATIONS_UPDATES)
    if committed_offset:
        print(f"  ↻ Resuming {STEP_CITATIONS_UPDATES} from committed offset {committed_offset:,}", flush=True)

    for rec in iter_diff_files(updates_dir, desc="[citations] updates"):
        citation_id = rec.get("citationid")
        citing = rec.get("citingcorpusid")
        cited = rec.get("citedcorpusid")
        if citation_id is None or citing is None or cited is None:
            continue
        citing_int = int(citing)
        cited_int = int(cited)
        if citing_int not in valid_corpus_ids or cited_int not in valid_corpus_ids:
            continue
        count += 1
        if count <= committed_offset:
            continue
        batch.append((int(citation_id), citing_int, cited_int))
        if len(batch) >= BATCH_SIZE:
            insert_citations_batch(conn, batch)
            batch.clear()
        if (count - committed_offset) % CHECKPOINT_RECORD_CHUNK == 0:
            if batch:
                print(f"  ↻ Flushing citations chunk: {len(batch):,}", flush=True)
                insert_citations_batch(conn, batch)
                batch.clear()
            print(f"  ↻ Committing citations updates chunk at {count:,} records...", flush=True)
            conn.commit()
            mark_step_offset(progress_path, progress_state, STEP_CITATIONS_UPDATES, count)

    if batch:
        print(f"  ↻ Flushing final citations batch: {len(batch):,}", flush=True)
        insert_citations_batch(conn, batch)
    print("  ↻ Committing citations updates...", flush=True)
    conn.commit()
    if count > committed_offset:
        mark_step_offset(progress_path, progress_state, STEP_CITATIONS_UPDATES, count)
    if count:
        print(f"  ✅ citations updates: {count:,}", flush=True)


def apply_citations_deletes(
    conn: sqlite3.Connection,
    deletes_dir: Path,
    progress_path: Path,
    progress_state: dict,
) -> None:
    ids: list[int] = []
    total = 0
    committed_offset = get_step_offset(progress_state, STEP_CITATIONS_DELETES)
    if committed_offset:
        print(f"  ↻ Resuming {STEP_CITATIONS_DELETES} from committed offset {committed_offset:,}", flush=True)

    for rec in iter_diff_files(deletes_dir, desc="[citations] deletes"):
        citation_id = rec.get("citationid")
        if citation_id is None:
            continue
        total += 1
        if total <= committed_offset:
            continue
        ids.append(int(citation_id))
        if len(ids) >= BATCH_SIZE:
            delete_citations_by_ids(conn, ids)
            ids.clear()
        if (total - committed_offset) > 0 and (total - committed_offset) % CHECKPOINT_RECORD_CHUNK == 0:
            if ids:
                print(f"  ↻ Flushing citation delete chunk: {len(ids):,}", flush=True)
                delete_citations_by_ids(conn, ids)
                ids.clear()
            print(f"  ↻ Committing citations deletes chunk at {total:,} records...", flush=True)
            conn.commit()
            mark_step_offset(progress_path, progress_state, STEP_CITATIONS_DELETES, total)

    if ids:
        print(f"  ↻ Flushing final citation delete batch: {len(ids):,}", flush=True)
        delete_citations_by_ids(conn, ids)
    print("  ↻ Committing citations deletes...", flush=True)
    conn.commit()
    if total > committed_offset:
        mark_step_offset(progress_path, progress_state, STEP_CITATIONS_DELETES, total)
    if total:
        print(f"  ✅ citations deletes: {total:,}", flush=True)


def merge_incremental(incr_dir: Path) -> None:
    if not incr_dir.exists():
        print(f"❌ Incremental directory not found: {incr_dir}", flush=True)
        return

    conn = get_connection()
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    t0 = time.time()
    progress_path = incr_dir / PROGRESS_FILE_NAME
    progress_state = load_merge_progress(progress_path)

    if progress_state.get("completed_steps"):
        print(f"↻ Resuming incremental SQLite/FTS merge from checkpoint: {progress_path}", flush=True)

    if step_completed(progress_state, STEP_PAPER_IDS_UPDATES):
        print(f"  ↷ Skip completed step: {STEP_PAPER_IDS_UPDATES}", flush=True)
    else:
        apply_paper_ids_updates(conn, incr_dir / "paper-ids" / "updates")
        mark_step_completed(progress_path, progress_state, STEP_PAPER_IDS_UPDATES)

    if step_completed(progress_state, STEP_PAPER_IDS_DELETES):
        print(f"  ↷ Skip completed step: {STEP_PAPER_IDS_DELETES}", flush=True)
    else:
        apply_paper_ids_deletes(conn, incr_dir / "paper-ids" / "deletes")
        mark_step_completed(progress_path, progress_state, STEP_PAPER_IDS_DELETES)

    if step_completed(progress_state, STEP_PAPERS_UPDATES):
        print(f"  ↷ Skip completed step: {STEP_PAPERS_UPDATES}", flush=True)
    else:
        apply_papers_updates(conn, incr_dir / "papers" / "updates", progress_path, progress_state)
        mark_step_completed(progress_path, progress_state, STEP_PAPERS_UPDATES)

    if step_completed(progress_state, STEP_PAPERS_DELETES):
        print(f"  ↷ Skip completed step: {STEP_PAPERS_DELETES}", flush=True)
    else:
        apply_papers_deletes(conn, incr_dir / "papers" / "deletes")
        mark_step_completed(progress_path, progress_state, STEP_PAPERS_DELETES)

    if step_completed(progress_state, STEP_ABSTRACTS_UPDATES):
        print(f"  ↷ Skip completed step: {STEP_ABSTRACTS_UPDATES}", flush=True)
    else:
        apply_abstracts_updates(conn, incr_dir / "abstracts" / "updates", progress_path, progress_state)
        mark_step_completed(progress_path, progress_state, STEP_ABSTRACTS_UPDATES)

    if step_completed(progress_state, STEP_ABSTRACTS_DELETES):
        print(f"  ↷ Skip completed step: {STEP_ABSTRACTS_DELETES}", flush=True)
    else:
        apply_abstracts_deletes(conn, incr_dir / "abstracts" / "deletes")
        mark_step_completed(progress_path, progress_state, STEP_ABSTRACTS_DELETES)

    if step_completed(progress_state, STEP_CITATIONS_UPDATES):
        print(f"  ↷ Skip completed step: {STEP_CITATIONS_UPDATES}", flush=True)
    else:
        apply_citations_updates(conn, incr_dir / "citations" / "updates", progress_path, progress_state)
        mark_step_completed(progress_path, progress_state, STEP_CITATIONS_UPDATES)

    if step_completed(progress_state, STEP_CITATIONS_DELETES):
        print(f"  ↷ Skip completed step: {STEP_CITATIONS_DELETES}", flush=True)
    else:
        apply_citations_deletes(conn, incr_dir / "citations" / "deletes", progress_path, progress_state)
        mark_step_completed(progress_path, progress_state, STEP_CITATIONS_DELETES)

    conn.commit()
    conn.close()

    write_qdrant_task(incr_dir)
    if progress_path.exists():
        progress_path.unlink()

    elapsed = time.time() - t0
    print(f"🎉 Incremental SQLite/FTS merge complete in {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply incremental diffs into SQLite + FTS only")
    parser.add_argument("incr_dir", type=Path, help="Path to incremental directory")
    args = parser.parse_args()
    merge_incremental(args.incr_dir)
