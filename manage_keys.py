#!/usr/bin/env python3
"""CLI tool for managing Lewen API keys.

Usage:
    python manage_keys.py create --name "User A" --email "a@example.com"
    python manage_keys.py list
    python manage_keys.py revoke  --prefix "lw-a3f8c7e2"
    python manage_keys.py activate --prefix "lw-a3f8c7e2"
    python manage_keys.py delete --prefix "lw-a3f8c7e2"
"""

from __future__ import annotations

import argparse
import sys

from auth.database import delete_key, init_auth_db, list_keys, set_key_active
from auth.key_manager import create_api_key


def cmd_create(args: argparse.Namespace) -> None:
    raw_key, record = create_api_key(
        name=args.name,
        email=args.email,
        expires_at=args.expires_at,
    )
    print(f"✅ API Key created (shown ONCE, save it now):\n")
    print(f"   Key:     {raw_key}")
    print(f"   Prefix:  {record['key_prefix']}")
    print(f"   Name:    {record['name']}")
    print(f"   Email:   {record['email']}")
    if record.get("expires_at"):
        print(f"   Expires: {record['expires_at']}")


def cmd_list(_args: argparse.Namespace) -> None:
    keys = list_keys()
    if not keys:
        print("No API keys found.")
        return
    fmt = "{:<4} {:<14} {:<8} {:<20} {:<28} {:<24} {:<24}"
    print(fmt.format("ID", "Prefix", "Active", "Name", "Email", "Created", "Last Used"))
    print("-" * 140)
    for k in keys:
        print(fmt.format(
            k["id"],
            k["key_prefix"],
            "Yes" if k["is_active"] else "No",
            k["name"][:20],
            k["email"][:28],
            (k["created_at"] or "")[:24],
            (k["last_used_at"] or "-")[:24],
        ))


def cmd_revoke(args: argparse.Namespace) -> None:
    if set_key_active(args.prefix, active=False):
        print(f"✅ Key {args.prefix} revoked.")
    else:
        print(f"❌ Key not found: {args.prefix}", file=sys.stderr)
        sys.exit(1)


def cmd_activate(args: argparse.Namespace) -> None:
    if set_key_active(args.prefix, active=True):
        print(f"✅ Key {args.prefix} activated.")
    else:
        print(f"❌ Key not found: {args.prefix}", file=sys.stderr)
        sys.exit(1)


def cmd_delete(args: argparse.Namespace) -> None:
    if delete_key(args.prefix):
        print(f"✅ Key {args.prefix} deleted.")
    else:
        print(f"❌ Key not found: {args.prefix}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Lewen API keys")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a new API key")
    p_create.add_argument("--name", required=True, help="Key owner / description")
    p_create.add_argument("--email", required=True, help="Requester email")
    p_create.add_argument("--expires-at", default=None, help="Expiration (ISO 8601), omit for no expiry")

    sub.add_parser("list", help="List all API keys")

    p_revoke = sub.add_parser("revoke", help="Disable a key")
    p_revoke.add_argument("--prefix", required=True, help="Key prefix (e.g. lw-a3f8c7e2)")

    p_activate = sub.add_parser("activate", help="Re-enable a key")
    p_activate.add_argument("--prefix", required=True, help="Key prefix")

    p_delete = sub.add_parser("delete", help="Permanently delete a key")
    p_delete.add_argument("--prefix", required=True, help="Key prefix")

    args = parser.parse_args()

    init_auth_db()

    {
        "create": cmd_create,
        "list": cmd_list,
        "revoke": cmd_revoke,
        "activate": cmd_activate,
        "delete": cmd_delete,
    }[args.command](args)


if __name__ == "__main__":
    main()
