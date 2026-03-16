"""Load test: /paper/{paper_id} (paper detail).

Usage:
    python test/test_load_detail.py
    python test/test_load_detail.py --workers 20 --requests 100
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_utils import get_sample_paper_id, make_base_parser, run_load_test


def main() -> None:
    parser = make_base_parser("Load test: /paper/{paper_id} (detail)")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    log_file = None if args.no_log else "test/load_failures_detail.log"

    headers = {"X-API-Key": args.api_key} if args.api_key else None

    print("📋 Fetching sample paper_id ...", flush=True)
    paper_id = get_sample_paper_id(base, timeout=args.timeout, headers=headers)
    if not paper_id:
        print("❌ Failed to get sample paper. Abort.")
        sys.exit(1)
    print(f"   paper_id: {paper_id[:16]}...\n", flush=True)

    cases = [
        ("detail default",
         f"{base}/paper/{paper_id}",
         None),
        ("detail fields",
         f"{base}/paper/{paper_id}",
         {"fields": "abstract,year,authors"}),
        ("detail all",
         f"{base}/paper/{paper_id}",
         {"fields": "*"}),
    ]

    run_load_test(
        cases,
        workers=args.workers,
        requests_per_case=args.requests,
        timeout=args.timeout,
        log_file=log_file,
        title="/paper/{id} Detail Load Test",
        headers=headers,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted.", flush=True)
        sys.exit(130)
