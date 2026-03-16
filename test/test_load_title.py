"""Load test: /paper/search/title (title FTS5 search).

Usage:
    python test/test_load_title.py
    python test/test_load_title.py --workers 20 --requests 100
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_utils import make_base_parser, run_load_test


def main() -> None:
    parser = make_base_parser("Load test: /paper/search/title")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    log_file = None if args.no_log else "test/load_failures_title.log"

    cases = [
        ("title plain",
         f"{base}/paper/search/title",
         {"query": "attention mechanism", "limit": 5}),
        ("title + year",
         f"{base}/paper/search/title",
         {"query": "attention", "year": "2019", "limit": 5}),
        ("title long",
         f"{base}/paper/search/title",
         {"query": "large language model reasoning", "limit": 10}),
        ("title all fields",
         f"{base}/paper/search/title",
         {"query": "transformer", "limit": 10, "fields": "*"}),
    ]

    headers = {"X-API-Key": args.api_key} if args.api_key else None
    run_load_test(
        cases,
        workers=args.workers,
        requests_per_case=args.requests,
        timeout=args.timeout,
        log_file=log_file,
        title="/paper/search/title Load Test",
        headers=headers,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted.", flush=True)
        sys.exit(130)
