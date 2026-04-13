"""Thread-safe SQLite read-only connection pool.

Maintains pre-opened connections with optimal PRAGMAs so each request
avoids the overhead of opening a 15GB database file. Connections use
WAL mode with autocheckpoint disabled (data is ingested offline).
"""

from __future__ import annotations

import queue
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

import config

_POOL_SIZE = 32


def _create_ro_connection() -> sqlite3.Connection:
    """Create a read-only connection with performance PRAGMAs."""
    uri = f"file:{config.PAPERS_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA wal_autocheckpoint = 0")
    conn.execute(f"PRAGMA busy_timeout = {config.SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute(f"PRAGMA cache_size = {config.SQLITE_CACHE_SIZE}")
    conn.execute(f"PRAGMA mmap_size = {config.SQLITE_MMAP_SIZE}")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA query_only = ON")
    return conn


class _ConnectionPool:
    """Simple fixed-size connection pool for read-only SQLite access."""

    def __init__(self, size: int = _POOL_SIZE) -> None:
        self._size = size
        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=size)
        self._lock = threading.Lock()
        self._created = 0

    def _get(self) -> sqlite3.Connection:
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self._size:
                    self._created += 1
                    return _create_ro_connection()
            return self._pool.get(timeout=10.0)

    def _put(self, conn: sqlite3.Connection) -> None:
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            conn.close()

    @contextmanager
    def connection(self, row_factory: bool = False) -> Iterator[sqlite3.Connection]:
        """Borrow a connection from the pool.

        Args:
            row_factory: If True, set sqlite3.Row as row_factory.

        Yields:
            sqlite3.Connection configured for read-only use.
        """
        conn = self._get()
        if row_factory:
            conn.row_factory = sqlite3.Row
        else:
            conn.row_factory = None
        try:
            yield conn
        except sqlite3.OperationalError:
            conn.close()
            with self._lock:
                self._created = max(0, self._created - 1)
            raise
        finally:
            if row_factory:
                conn.row_factory = None
            self._put(conn)

    def close_all(self) -> None:
        """Close all pooled connections."""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break
        with self._lock:
            self._created = 0


pool = _ConnectionPool(size=_POOL_SIZE)
