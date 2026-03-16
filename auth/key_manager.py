"""API key generation, hashing, and verification."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

from auth.database import (
    get_key_by_hash,
    insert_key,
    update_last_used,
)

_KEY_PREFIX = "lw-"
_KEY_RANDOM_BYTES = 16  # 32 hex chars → 128 bits of randomness


def generate_raw_key() -> str:
    """Generate a new raw API key string like ``lw-a3f8c7e2...``."""
    return _KEY_PREFIX + secrets.token_hex(_KEY_RANDOM_BYTES)


def hash_key(raw_key: str) -> str:
    """SHA-256 hash of a raw key (used for storage and lookup)."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_api_key(
    name: str,
    email: str,
    expires_at: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Create a new API key.

    Returns:
        (raw_key, record_dict) — raw_key is shown once; record_dict is the DB row info.
    """
    raw_key = generate_raw_key()
    key_hash = hash_key(raw_key)
    key_prefix = raw_key[:11]  # "lw-" + first 8 hex chars

    row_id = insert_key(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
        email=email,
        expires_at=expires_at,
    )

    record = {
        "id": row_id,
        "key_prefix": key_prefix,
        "name": name,
        "email": email,
        "expires_at": expires_at,
    }
    return raw_key, record


def verify_api_key(raw_key: str) -> dict[str, Any] | None:
    """Verify a raw API key.

    Returns the key record if the key is valid and active, else None.
    """
    key_hash = hash_key(raw_key)
    record = get_key_by_hash(key_hash)
    if record is None:
        return None
    if not record["is_active"]:
        return None
    if record.get("expires_at"):
        try:
            exp = datetime.fromisoformat(record["expires_at"])
            if datetime.now(timezone.utc) > exp:
                return None
        except ValueError:
            pass

    update_last_used(key_hash)
    return record
