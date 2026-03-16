"""FastAPI middleware for API key authentication.

Uses an in-memory cache with a file-based invalidation signal so that
admin operations (revoke/delete) in any worker cause all workers to
refresh their caches on the next request.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

import config
from auth.database import get_key_by_hash, update_last_used

logger = logging.getLogger(__name__)

_PUBLIC_PATHS: set[str] = {
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
}

_INVALIDATION_FILE = os.path.join(config.CORPUS_DIR, ".auth_cache_version")


class _KeyCache:
    """Thread-safe in-memory cache with cross-process invalidation."""

    def __init__(self, ttl: int = 60):
        self._ttl = ttl
        self._store: dict[str, dict[str, Any] | None] = {}
        self._timestamps: dict[str, float] = {}
        self._lock = threading.Lock()
        self._last_invalidation_check: float = 0.0
        self._known_version: float = self._read_version()

    @staticmethod
    def _read_version() -> float:
        try:
            return os.path.getmtime(_INVALIDATION_FILE)
        except OSError:
            return 0.0

    def _check_cross_process_invalidation(self) -> None:
        """If another worker bumped the version file, clear local cache."""
        now = time.monotonic()
        if now - self._last_invalidation_check < 1.0:
            return
        self._last_invalidation_check = now
        current_version = self._read_version()
        if current_version != self._known_version:
            self._known_version = current_version
            self._store.clear()
            self._timestamps.clear()

    def get(self, key_hash: str) -> tuple[bool, dict[str, Any] | None]:
        """Return (cache_hit, record_or_none)."""
        self._check_cross_process_invalidation()
        with self._lock:
            ts = self._timestamps.get(key_hash)
            if ts is not None and (time.monotonic() - ts) < self._ttl:
                return True, self._store.get(key_hash)
        return False, None

    def put(self, key_hash: str, record: dict[str, Any] | None) -> None:
        with self._lock:
            self._store[key_hash] = record
            self._timestamps[key_hash] = time.monotonic()

    def invalidate(self) -> None:
        with self._lock:
            self._store.clear()
            self._timestamps.clear()


_cache = _KeyCache(ttl=config.AUTH_CACHE_TTL)


def invalidate_key_cache() -> None:
    """Signal all workers to clear their key caches."""
    _cache.invalidate()
    try:
        with open(_INVALIDATION_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _is_key_valid(record: dict[str, Any]) -> bool:
    if not record["is_active"]:
        return False
    exp = record.get("expires_at")
    if exp:
        try:
            if datetime.now(timezone.utc) > datetime.fromisoformat(exp):
                return False
        except ValueError:
            pass
    return True


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid API key on protected paths."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ):
        path = request.url.path

        if path in _PUBLIC_PATHS or path.startswith("/admin"):
            return await call_next(request)

        raw_key = request.headers.get("X-API-Key") or request.query_params.get("apiKey")
        if not raw_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing API key. Provide X-API-Key header."},
            )

        key_hash = _hash(raw_key)
        hit, record = _cache.get(key_hash)

        if not hit:
            record = get_key_by_hash(key_hash)
            _cache.put(key_hash, record)

        if record is None or not _is_key_valid(record):
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid or inactive API key."},
            )

        request.state.api_key_record = record

        return await call_next(request)
