
"""Unified SQLite database for paper_metadata, citations, and ID mappings.

All tables live in a single papers.db file (config.PAPERS_DB_PATH).
Uses WAL mode and large cache for high-throughput ingest.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import config

_SQL_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS paper_metadata (
    paper_id TEXT PRIMARY KEY,
    corpus_id INTEGER NOT NULL UNIQUE,
    title TEXT,
    abstract TEXT,
    year INTEGER,
    venue TEXT,
    citation_count INTEGER DEFAULT 0,
    reference_count INTEGER DEFAULT 0,
    authors_json TEXT,
    fields_of_study_json TEXT,
    publication_types_json TEXT,
    publication_date TEXT,
    open_access_pdf_json TEXT,
    external_ids_json TEXT,
    journal_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_metadata_corpus ON paper_metadata(corpus_id);

CREATE TABLE IF NOT EXISTS corpus_id_mapping (
    corpus_id INTEGER PRIMARY KEY,
    paper_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_corpus_mapping_paper ON corpus_id_mapping(paper_id);

CREATE TABLE IF NOT EXISTS arxiv_to_paper (
    arxiv_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citations (
    citation_id INTEGER PRIMARY KEY,
    citing_corpus_id INTEGER NOT NULL,
    cited_corpus_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_citations_cited ON citations(cited_corpus_id);
CREATE INDEX IF NOT EXISTS idx_citations_citing ON citations(citing_corpus_id);
"""

_FTS5_TITLE_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts_title USING fts5(paper_id, title);
"""

_FTS5_COMBINED_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts_combined USING fts5(paper_id, title_abstract);
"""


def get_connection(readonly: bool = False) -> sqlite3.Connection:
    """Return a new SQLite connection to papers.db.

    Args:
        readonly: If True, open in read-only mode (URI).

    Returns:
        sqlite3.Connection to PAPERS_DB_PATH.
    """
    Path(config.PAPERS_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        uri = f"file:{config.PAPERS_DB_PATH}?mode=ro"
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=config.SQLITE_BUSY_TIMEOUT_MS / 1000,
        )
    else:
        conn = sqlite3.connect(
            config.PAPERS_DB_PATH,
            timeout=config.SQLITE_BUSY_TIMEOUT_MS / 1000,
        )
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {config.SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute(f"PRAGMA cache_size = {config.SQLITE_CACHE_SIZE}")
    return conn


def init_db(create_fts: bool = False) -> None:
    """Create all tables and indexes if they do not exist.

    Args:
        create_fts: If True, also create the FTS5 virtual tables.
    """
    conn = get_connection()
    try:
        conn.executescript(_SQL_SCHEMA)
        if create_fts:
            conn.executescript(_FTS5_TITLE_SCHEMA)
            conn.executescript(_FTS5_COMBINED_SCHEMA)
        conn.commit()
        print("✅ papers.db schema initialized.")
    finally:
        conn.close()


def init_fts_title() -> None:
    """Create the paper_fts_title FTS5 virtual table (idempotent)."""
    conn = get_connection()
    try:
        conn.executescript(_FTS5_TITLE_SCHEMA)
        conn.commit()
        print("✅ paper_fts_title created.")
    finally:
        conn.close()


def init_fts_combined() -> None:
    """Create the paper_fts_combined FTS5 virtual table (idempotent)."""
    conn = get_connection()
    try:
        conn.executescript(_FTS5_COMBINED_SCHEMA)
        conn.commit()
        print("✅ paper_fts_combined created.")
    finally:
        conn.close()


# ── Batch Insert Helpers ──────────────────────────────────────────────


def insert_paper_metadata_batch(
    conn: sqlite3.Connection,
    rows: list[tuple],
) -> None:
    """Upsert a batch of paper_metadata rows.

    Args:
        conn: Active SQLite connection.
        rows: List of tuples matching paper_metadata columns:
            (paper_id, corpus_id, title, abstract, year, venue,
             citation_count, reference_count, authors_json,
             fields_of_study_json, publication_types_json,
             publication_date, open_access_pdf_json,
             external_ids_json, journal_json)
    """
    if not rows:
        return
    conn.executemany(
        """INSERT OR REPLACE INTO paper_metadata
           (paper_id, corpus_id, title, abstract, year, venue,
            citation_count, reference_count, authors_json,
            fields_of_study_json, publication_types_json,
            publication_date, open_access_pdf_json,
            external_ids_json, journal_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


def insert_corpus_mapping_batch(
    conn: sqlite3.Connection,
    rows: list[tuple[int, str]],
) -> None:
    """Upsert a batch of corpus_id_mapping rows.

    Args:
        conn: Active SQLite connection.
        rows: List of (corpus_id, paper_id) tuples.
    """
    if not rows:
        return
    conn.executemany(
        "INSERT OR REPLACE INTO corpus_id_mapping (corpus_id, paper_id) VALUES (?, ?)",
        rows,
    )


def insert_arxiv_mapping_batch(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str]],
) -> None:
    """Upsert a batch of arxiv_to_paper rows.

    Args:
        conn: Active SQLite connection.
        rows: List of (arxiv_id, paper_id) tuples.
    """
    if not rows:
        return
    conn.executemany(
        "INSERT OR REPLACE INTO arxiv_to_paper (arxiv_id, paper_id) VALUES (?, ?)",
        rows,
    )


def insert_citations_batch(
    conn: sqlite3.Connection,
    rows: list[tuple[int, int, int | None]],
) -> None:
    """Upsert a batch of citation rows (3-column).

    Args:
        conn: Active SQLite connection.
        rows: List of (citation_id, citing_corpus_id, cited_corpus_id) tuples.
    """
    if not rows:
        return
    conn.executemany(
        """INSERT OR REPLACE INTO citations
           (citation_id, citing_corpus_id, cited_corpus_id)
           VALUES (?, ?, ?)""",
        rows,
    )


def delete_by_corpus_ids(conn: sqlite3.Connection, corpus_ids: list[int]) -> None:
    """Delete paper_metadata, corpus_id_mapping, arxiv_to_paper, and FTS tables by corpus_id.

    Args:
        conn: Active SQLite connection.
        corpus_ids: List of corpus_ids to delete.
    """
    if not corpus_ids:
        return
    for i in range(0, len(corpus_ids), config.INGEST_BATCH_SIZE):
        batch_ids = corpus_ids[i : i + config.INGEST_BATCH_SIZE]
        placeholders = ",".join("?" for _ in batch_ids)
        paper_ids_subquery = f"(SELECT paper_id FROM corpus_id_mapping WHERE corpus_id IN ({placeholders}))"
        conn.execute(
            f"DELETE FROM paper_fts_title WHERE paper_id IN {paper_ids_subquery}",
            batch_ids,
        )
        conn.execute(
            f"DELETE FROM paper_fts_combined WHERE paper_id IN {paper_ids_subquery}",
            batch_ids,
        )
        conn.execute(
            f"DELETE FROM arxiv_to_paper WHERE paper_id IN {paper_ids_subquery}",
            batch_ids,
        )
        conn.execute(
            f"DELETE FROM paper_metadata WHERE corpus_id IN ({placeholders})",
            batch_ids,
        )
        conn.execute(
            f"DELETE FROM corpus_id_mapping WHERE corpus_id IN ({placeholders})",
            batch_ids,
        )


def delete_by_paper_ids(conn: sqlite3.Connection, paper_ids: list[str]) -> None:
    """Delete paper_metadata, corpus_id_mapping, arxiv_to_paper, and FTS tables by paper_id."""
    if not paper_ids:
        return
    for i in range(0, len(paper_ids), config.INGEST_BATCH_SIZE):
        batch_ids = paper_ids[i : i + config.INGEST_BATCH_SIZE]
        placeholders = ",".join("?" for _ in batch_ids)
        conn.execute(
            f"DELETE FROM paper_fts_title WHERE paper_id IN ({placeholders})",
            batch_ids,
        )
        conn.execute(
            f"DELETE FROM paper_fts_combined WHERE paper_id IN ({placeholders})",
            batch_ids,
        )
        conn.execute(
            f"DELETE FROM arxiv_to_paper WHERE paper_id IN ({placeholders})",
            batch_ids,
        )
        conn.execute(
            f"DELETE FROM paper_metadata WHERE paper_id IN ({placeholders})",
            batch_ids,
        )
        conn.execute(
            f"DELETE FROM corpus_id_mapping WHERE paper_id IN ({placeholders})",
            batch_ids,
        )


def delete_citations_by_ids(conn: sqlite3.Connection, citation_ids: list[int]) -> None:
    """Delete citation rows by citation_id.

    Args:
        conn: Active SQLite connection.
        citation_ids: List of citation_ids to delete.
    """
    if not citation_ids:
        return
    placeholders = ",".join("?" for _ in citation_ids)
    conn.execute(
        f"DELETE FROM citations WHERE citation_id IN ({placeholders})",
        citation_ids,
    )


def insert_fts_title_batch(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str]],
) -> None:
    """Insert rows into paper_fts_title.

    Args:
        conn: Active SQLite connection.
        rows: List of (paper_id, title) tuples.
    """
    if not rows:
        return
    conn.executemany(
        "INSERT INTO paper_fts_title (paper_id, title) VALUES (?, ?)",
        rows,
    )


def insert_fts_combined_batch(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str]],
) -> None:
    """Insert rows into paper_fts_combined.

    Args:
        conn: Active SQLite connection.
        rows: List of (paper_id, title_abstract) tuples.
    """
    if not rows:
        return
    conn.executemany(
        "INSERT INTO paper_fts_combined (paper_id, title_abstract) VALUES (?, ?)",
        rows,
    )


def get_paper_by_paper_id(paper_id: str) -> dict[str, Any] | None:
    """Get a single paper by paper_id (sha).

    Args:
        paper_id: SHA paper_id.

    Returns:
        S2-style paper dict, or None if not found.
    """
    from core.db_pool import pool

    with pool.connection(row_factory=True) as conn:
        cur = conn.execute(
            "SELECT * FROM paper_metadata WHERE paper_id = ?",
            (paper_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_paper_dict(dict(row))


def get_papers_by_ids(paper_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Batch fetch papers by paper_ids. Avoids N+1 queries.

    Args:
        paper_ids: List of SHA paper_ids.

    Returns:
        Dict mapping paper_id -> S2-style paper dict. Missing papers are omitted.
    """
    if not paper_ids:
        return {}

    from core.db_pool import pool

    result: dict[str, dict[str, Any]] = {}
    chunk_size = 500  # SQLite IN clause limit
    with pool.connection(row_factory=True) as conn:
        for i in range(0, len(paper_ids), chunk_size):
            chunk = paper_ids[i : i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            cur = conn.execute(
                f"SELECT * FROM paper_metadata WHERE paper_id IN ({placeholders})",
                chunk,
            )
            for row in cur.fetchall():
                d = dict(row)
                pid = d["paper_id"]
                result[pid] = _row_to_paper_dict(d)
    return result


def get_paper_by_corpus_id(corpus_id: int) -> dict[str, Any] | None:
    """Get a single paper by corpus_id.

    Args:
        corpus_id: S2 CorpusId.

    Returns:
        S2-style paper dict, or None if not found.
    """
    from core.db_pool import pool

    with pool.connection(row_factory=True) as conn:
        cur = conn.execute(
            "SELECT * FROM paper_metadata WHERE corpus_id = ?",
            (corpus_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_paper_dict(dict(row))


def get_papers_by_corpus_ids(corpus_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Batch fetch papers by corpus_ids. Avoids N+1 queries.

    Args:
        corpus_ids: List of S2 corpus_ids.

    Returns:
        Dict mapping corpus_id -> S2-style paper dict. Missing papers are omitted.
    """
    if not corpus_ids:
        return {}

    from core.db_pool import pool

    result: dict[int, dict[str, Any]] = {}
    chunk_size = 500  # SQLite IN clause limit
    with pool.connection(row_factory=True) as conn:
        for i in range(0, len(corpus_ids), chunk_size):
            chunk = corpus_ids[i : i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            cur = conn.execute(
                f"SELECT * FROM paper_metadata WHERE corpus_id IN ({placeholders})",
                chunk,
            )
            for row in cur.fetchall():
                d = dict(row)
                cid = d["corpus_id"]
                result[cid] = _row_to_paper_dict(d)
    return result


def _safe_json_loads(val: str | None) -> Any:
    """Safely parse a JSON string, returning None on failure."""
    if not val or val == "null":
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


def _row_to_paper_dict(row: dict) -> dict[str, Any]:
    """Convert a paper_metadata DB row to S2-style paper dict.

    Args:
        row: Dict from sqlite3.Row.

    Returns:
        Paper dict with camelCase keys matching S2 API format.
    """
    result: dict[str, Any] = {
        "paperId": row["paper_id"],
        "title": row.get("title"),
    }
    if row.get("abstract") is not None:
        result["abstract"] = row["abstract"]
    if row.get("year") is not None:
        result["year"] = row["year"]
    if row.get("venue"):
        result["venue"] = row["venue"]
    if row.get("citation_count") is not None:
        result["citationCount"] = row["citation_count"]
    if row.get("reference_count") is not None:
        result["referenceCount"] = row["reference_count"]
    if row.get("publication_date"):
        result["publicationDate"] = row["publication_date"]

    authors = _safe_json_loads(row.get("authors_json"))
    if authors is not None:
        result["authors"] = authors

    fos = _safe_json_loads(row.get("fields_of_study_json"))
    if fos is not None:
        result["fieldsOfStudy"] = fos

    pub_types = _safe_json_loads(row.get("publication_types_json"))
    if pub_types is not None:
        result["publicationTypes"] = pub_types

    oa_pdf = _safe_json_loads(row.get("open_access_pdf_json"))
    if oa_pdf is not None:
        result["openAccessPdf"] = oa_pdf

    ext_ids = _safe_json_loads(row.get("external_ids_json"))
    if ext_ids is not None:
        result["externalIds"] = ext_ids

    journal = _safe_json_loads(row.get("journal_json"))
    if journal is not None:
        result["journal"] = journal

    return result
