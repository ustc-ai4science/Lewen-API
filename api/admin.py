"""Admin API — manage API keys.

All endpoints require the ``X-Admin-Secret`` header to match
``config.ADMIN_SECRET``.  When ``ADMIN_SECRET`` is empty the
entire router returns 503.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

import config
from auth.database import delete_key, list_keys, set_key_active
from auth.key_manager import create_api_key
from auth.middleware import invalidate_key_cache

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Admin auth dependency ──────────────────────────────────────────────

def _verify_admin(x_admin_secret: str = Header(..., alias="X-Admin-Secret")):
    if not config.ADMIN_SECRET:
        raise HTTPException(503, detail="Admin API disabled (ADMIN_SECRET not set).")
    if x_admin_secret != config.ADMIN_SECRET:
        raise HTTPException(403, detail="Invalid admin secret.")


# ── Request schemas ────────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str
    email: str
    expires_at: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/keys", dependencies=[Depends(_verify_admin)])
async def admin_create_key(body: CreateKeyRequest) -> dict[str, Any]:
    """Create a new API key.  The raw key is returned **once** in the response."""
    raw_key, record = create_api_key(
        name=body.name,
        email=body.email,
        expires_at=body.expires_at,
    )
    invalidate_key_cache()
    return {"key": raw_key, **record}


@router.get("/keys", dependencies=[Depends(_verify_admin)])
async def admin_list_keys() -> list[dict[str, Any]]:
    """List all API keys (without hash values)."""
    return list_keys()


@router.post("/keys/{prefix}/revoke", dependencies=[Depends(_verify_admin)])
async def admin_revoke_key(prefix: str) -> dict[str, str]:
    """Disable an API key by its prefix."""
    if not set_key_active(prefix, active=False):
        raise HTTPException(404, detail=f"Key not found: {prefix}")
    invalidate_key_cache()
    return {"status": "revoked", "key_prefix": prefix}


@router.post("/keys/{prefix}/activate", dependencies=[Depends(_verify_admin)])
async def admin_activate_key(prefix: str) -> dict[str, str]:
    """Re-enable a previously revoked API key."""
    if not set_key_active(prefix, active=True):
        raise HTTPException(404, detail=f"Key not found: {prefix}")
    invalidate_key_cache()
    return {"status": "activated", "key_prefix": prefix}


@router.delete("/keys/{prefix}", dependencies=[Depends(_verify_admin)])
async def admin_delete_key(prefix: str) -> dict[str, str]:
    """Permanently delete an API key."""
    if not delete_key(prefix):
        raise HTTPException(404, detail=f"Key not found: {prefix}")
    invalidate_key_cache()
    return {"status": "deleted", "key_prefix": prefix}
