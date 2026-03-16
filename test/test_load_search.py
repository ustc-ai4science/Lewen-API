"""Load test: /paper/search (sparse, hybrid, filtered).

Usage:
    python test/test_load_search.py
    python test/test_load_search.py --workers 20 --requests 100
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_utils import make_base_parser, run_load_test


def main() -> None:
    parser = make_base_parser("Load test: /paper/search (sparse / hybrid / filtered)")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    log_file = None if args.no_log else "test/load_failures_search.log"

    cases = [
        ("sparse",
         f"{base}/paper/search",
         {"query": "transformer attention", "retrieval": "sparse", "limit": 5}),
        ("hybrid",
         f"{base}/paper/search",
         {"query": "transformer attention", "retrieval": "hybrid", "limit": 5}),
        ("filter year",
         f"{base}/paper/search",
         {"query": "BERT", "year": "2019", "limit": 5}),
        ("filter venue",
         f"{base}/paper/search",
         {"query": "deep learning", "venue": "NeurIPS", "retrieval": "sparse", "limit": 5}),
        ("sparse all fields",
         f"{base}/paper/search",
         {"query": "graph neural network", "retrieval": "sparse", "limit": 10, "fields": "*"}),
        ("hybrid all fields",
         f"{base}/paper/search",
         {"query": "reinforcement learning", "retrieval": "hybrid", "limit": 10, "fields": "*"}),
    ]

    headers = {"X-API-Key": args.api_key} if args.api_key else None
    run_load_test(
        cases,
        workers=args.workers,
        requests_per_case=args.requests,
        timeout=args.timeout,
        log_file=log_file,
        title="/paper/search Load Test",
        headers=headers,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted.", flush=True)
        sys.exit(130)
