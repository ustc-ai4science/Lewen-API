"""auth.db — SQLite storage for API keys.

Provides schema init, CRUD, and a connection helper.  The database file
is independent of papers.db so that read-only corpus connections are
never mixed with auth writes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

_SQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash        TEXT    UNIQUE NOT NULL,
    key_prefix      TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    email           TEXT    NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL,
    last_used_at    TEXT,
    expires_at      TEXT
);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_auth_db() -> None:
    """Create the api_keys table if it doesn't exist."""
    conn = _get_conn()
    try:
        conn.executescript(_SQL_SCHEMA)
    finally:
        conn.close()


def insert_key(
    key_hash: str,
    key_prefix: str,
    name: str,
    email: str,
    expires_at: str | None = None,
) -> int:
    """Insert a new API key record.  Returns the row id."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO api_keys (key_hash, key_prefix, name, email, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key_hash, key_prefix, name, email, _now_iso(), expires_at),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def get_key_by_hash(key_hash: str) -> dict[str, Any] | None:
    """Look up a key record by its SHA-256 hash."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_keys() -> list[dict[str, Any]]:
    """Return all key records (without key_hash for safety)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, key_prefix, name, email, is_active, created_at, last_used_at, expires_at FROM api_keys ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_last_used(key_hash: str) -> None:
    """Update last_used_at timestamp for a key."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
            (_now_iso(), key_hash),
        )
        conn.commit()
    finally:
        conn.close()


def set_key_active(key_prefix: str, active: bool) -> bool:
    """Enable or disable a key by prefix.  Returns True if a row was updated."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "UPDATE api_keys SET is_active = ? WHERE key_prefix = ?",
            (1 if active else 0, key_prefix),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_key(key_prefix: str) -> bool:
    """Permanently delete a key by prefix.  Returns True if a row was deleted."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM api_keys WHERE key_prefix = ?", (key_prefix,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
