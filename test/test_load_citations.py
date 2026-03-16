"""Load test: /paper/{id}/citations and /paper/{id}/references.

Usage:
    python test/test_load_citations.py
    python test/test_load_citations.py --workers 20 --requests 100
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_utils import get_sample_paper_id, make_base_parser, run_load_test


def main() -> None:
    parser = make_base_parser("Load test: citations & references")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    log_file = None if args.no_log else "test/load_failures_citations.log"

    headers = {"X-API-Key": args.api_key} if args.api_key else None

    print("📋 Fetching sample paper_id ...", flush=True)
    paper_id = get_sample_paper_id(base, timeout=args.timeout, headers=headers)
    if not paper_id:
        print("❌ Failed to get sample paper. Abort.")
        sys.exit(1)
    print(f"   paper_id: {paper_id[:16]}...\n", flush=True)

    cases = [
        ("citations",
         f"{base}/paper/{paper_id}/citations",
         None),
        ("citations page",
         f"{base}/paper/{paper_id}/citations",
         {"limit": 3, "offset": 1}),
        ("citations all fields",
         f"{base}/paper/{paper_id}/citations",
         {"limit": 10, "fields": "*"}),
        ("references",
         f"{base}/paper/{paper_id}/references",
         None),
        ("references limit",
         f"{base}/paper/{paper_id}/references",
         {"limit": 5}),
    ]

    run_load_test(
        cases,
        workers=args.workers,
        requests_per_case=args.requests,
        timeout=args.timeout,
        log_file=log_file,
        title="Citations & References Load Test",
        headers=headers,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted.", flush=True)
        sys.exit(130)
