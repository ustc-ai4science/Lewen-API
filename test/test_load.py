"""Load/concurrency test for Paper Search API.

Tests search, search/title, paper detail, citations, references under concurrent load.

  python test/test_load.py
  python test/test_load.py --base-url http://210.45.70.162:4000 --workers 20 --requests 50

Note: If the second run hangs at "Fetching sample paper", the server may still be
  recovering (connections in TIME_WAIT, executor backlog). Use --cooldown 5 to wait
  before starting.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

# One Session per worker thread for connection reuse.
_thread_local = threading.local()


def _get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
    return _thread_local.session


SAMPLE_PAPER_QUERY = "TimeDART: A Diffusion Autoregressive Transformer for Self-Supervised Time-Series Representations"


def _get_sample_paper_id(base: str, timeout: int = 30, debug: bool = False, headers: dict | None = None) -> str | None:
    """Get paper_id for TimeDART via title search.

    Tries full title first, then 'TimeDART' as fallback (FTS5 may not match long phrases).
    """
    last_query = None
    last_response = None
    for query in [SAMPLE_PAPER_QUERY, "TimeDART"]:
        last_query = query
        with requests.Session() as s:
            r = s.get(
                f"{base}/paper/search/title",
                params={"query": query, "limit": 10},
                headers=headers,
                timeout=timeout,
            )
        try:
            last_response = r.json()
        except Exception:
            last_response = r.text[:200] if r.text else None
        if debug:
            print(f"   [DEBUG] query={query!r}")
            print(f"   [DEBUG] status={r.status_code}")
            if isinstance(last_response, dict):
                print(f"   [DEBUG] response: total={last_response.get('total')}, data_len={len(last_response.get('data', []))}")
                if last_response.get("data"):
                    for i, item in enumerate(last_response["data"][:3]):
                        print(f"   [DEBUG]   [{i}] paperId={item.get('paperId', '')[:16]}... title={item.get('title', '')[:60]}...")
            else:
                print(f"   [DEBUG] response: {last_response}")
        if r.status_code == 200 and isinstance(last_response, dict) and last_response.get("data"):
            for item in last_response["data"]:
                title = (item.get("title") or "").lower()
                if "timedart" in title:
                    return item.get("paperId")
            return last_response["data"][0].get("paperId")
    # Failed: print last response for debugging
    print(f"   [DEBUG] Last query: {last_query!r}")
    print(f"   [DEBUG] Last response: {last_response}")
    return None


def _single_request(
    session: requests.Session,
    url: str,
    params: dict | None = None,
    timeout: int = 60,
    headers: dict | None = None,
) -> tuple[bool, float, str | None]:
    """Execute one request. Returns (success, elapsed_seconds, error_msg_or_None)."""
    start = time.perf_counter()
    try:
        r = session.get(url, params=params, headers=headers, timeout=timeout)
        elapsed = time.perf_counter() - start
        if r.status_code == 200:
            return True, elapsed, None
        return False, elapsed, f"HTTP {r.status_code}"
    except requests.RequestException as e:
        elapsed = time.perf_counter() - start
        return False, elapsed, type(e).__name__ + (f": {e}" if str(e) else "")


def _percentile(arr: list[float], p: float) -> float:
    """Compute percentile. p in (0, 1]."""
    if not arr:
        return 0.0
    sorted_arr = sorted(arr)
    idx = max(0, int(len(sorted_arr) * p) - 1)
    return sorted_arr[idx]


def _run_load_test(
    base: str,
    paper_id: str,
    workers: int,
    requests_per_case: int,
    timeout: int,
    headers: dict | None = None,
) -> tuple[dict, dict[str, dict], list[dict]]:
    """Run concurrent load test. Returns (overall_stats, per_endpoint_stats, failed_requests)."""

    cases = [
        ("search sparse", f"{base}/paper/search", {"query": "transformer attention", "retrieval": "sparse", "limit": 5}),
        ("search hybrid", f"{base}/paper/search", {"query": "transformer attention", "retrieval": "hybrid", "limit": 5}),
        ("search filters", f"{base}/paper/search", {"query": "BERT", "year": "2019", "limit": 5}),
        ("search/title", f"{base}/paper/search/title", {"query": "attention", "limit": 5}),
        ("search/title year", f"{base}/paper/search/title", {"query": "attention", "year": "2019", "limit": 5}),
        ("paper detail", f"{base}/paper/{paper_id}", None),
        ("paper detail fields", f"{base}/paper/{paper_id}", {"fields": "abstract,year,authors"}),
        ("citations", f"{base}/paper/{paper_id}/citations", None),
        ("citations pagination", f"{base}/paper/{paper_id}/citations", {"limit": 3, "offset": 1}),
        ("references", f"{base}/paper/{paper_id}/references", None),
        ("references limit", f"{base}/paper/{paper_id}/references", {"limit": 5}),
    ]

    tasks: list[tuple[str, str, dict | None]] = []
    for name, url, params in cases:
        for _ in range(requests_per_case):
            tasks.append((name, url, params))

    total = len(tasks)
    results: list[tuple[str, bool, float, str | None, str, dict | None]] = []

    def worker(task: tuple[str, str, dict | None]) -> tuple[str, bool, float, str | None, str, dict | None]:
        name, url, params = task
        ok, elapsed, err = _single_request(_get_session(), url, params, timeout, headers=headers)
        return name, ok, elapsed, err, url, params

    start = time.perf_counter()
    last_print_time = start
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(worker, t) for t in tasks]
        for f in as_completed(futures):
            results.append(f.result())  # (name, ok, elapsed, err, url, params)
            done += 1
            if done % 200 == 0 or done == total:
                now = time.perf_counter()
                elapsed = now - start
                interval = now - last_print_time
                last_print_time = now
                print(f"   Progress: {done}/{total} ({100*done/total:.0f}%) — total {elapsed:.1f}s (batch +{interval:.1f}s)", flush=True)
    elapsed_total = time.perf_counter() - start

    # Overall stats
    success_count = sum(1 for _, ok, _, _, _, _ in results if ok)
    all_latencies = [e for _, _, e, _, _, _ in results]
    sorted_lat = sorted(all_latencies) if all_latencies else []
    overall = {
        "total": total,
        "success": success_count,
        "fail": total - success_count,
        "elapsed": elapsed_total,
        "qps": total / elapsed_total if elapsed_total > 0 else 0,
        "p50": statistics.median(all_latencies) if all_latencies else 0,
        "p95": _percentile(sorted_lat, 0.95),
        "p99": _percentile(sorted_lat, 0.99),
    }

    # Per-endpoint stats
    by_endpoint: dict[str, list[tuple[bool, float]]] = {}
    failed_requests: list[dict] = []
    for name, ok, elapsed, err, url, params in results:
        by_endpoint.setdefault(name, []).append((ok, elapsed))
        if not ok:
            failed_requests.append({
                "endpoint": name,
                "url": url,
                "params": params,
                "elapsed_s": round(elapsed, 3),
                "error": err or "unknown",
            })

    per_endpoint: dict[str, dict] = {}
    for name, items in by_endpoint.items():
        latencies = [e for _, e in items]
        ok_count = sum(1 for ok, _ in items if ok)
        sorted_lat = sorted(latencies) if latencies else []
        per_endpoint[name] = {
            "count": len(items),
            "success": ok_count,
            "fail": len(items) - ok_count,
            "p50": statistics.median(latencies) if latencies else 0,
            "p95": _percentile(sorted_lat, 0.95),
            "p99": _percentile(sorted_lat, 0.99),
            "avg": sum(latencies) / len(latencies) if latencies else 0,
        }

    return overall, per_endpoint, failed_requests


def run_load_test(
    base_url: str,
    workers: int = 10,
    requests_per_endpoint: int = 20,
    timeout: int = 60,
    log_failures: str | None = None,
    cooldown: int = 0,
    debug: bool = False,
    api_key: str | None = None,
) -> None:
    """Run load test and print report."""
    base = base_url.rstrip("/")
    headers = {"X-API-Key": api_key} if api_key else None

    num_cases = 11
    total_req = num_cases * requests_per_endpoint
    print("=" * 60)
    print(f"Paper Search API Load Test — {base}")
    print(f"  Workers: {workers}, Requests: {total_req} total ({requests_per_endpoint} per endpoint)")
    print("=" * 60)

    if cooldown > 0:
        print(f"\n⏳ Cooldown: waiting {cooldown}s before starting...", flush=True)
        time.sleep(cooldown)

    print("\n📋 Fetching sample paper (TimeDART: A Diffusion Autoregressive Transformer...)...")
    paper_id = _get_sample_paper_id(base, timeout, debug=debug, headers=headers)
    if not paper_id:
        print("❌ Failed to get sample paper. Abort.")
        sys.exit(1)
    print(f"   paper_id: {paper_id[:16]}...")

    print(f"\n🚀 Running load test ({workers} workers, {total_req} requests)...", flush=True)
    overall, per_endpoint, failed_requests = _run_load_test(base, paper_id, workers, requests_per_endpoint, timeout, headers=headers)

    print("\n" + "=" * 60, flush=True)
    print("📊 Overall Results", flush=True)
    print("=" * 60, flush=True)
    print(f"  Total:    {overall['total']}", flush=True)
    success_pct = 100 * overall["success"] / overall["total"] if overall["total"] else 0
    print(f"  Success:  {overall['success']} ({success_pct:.1f}%)", flush=True)
    print(f"  Failed:   {overall['fail']}", flush=True)
    print(f"  Duration: {overall['elapsed']:.2f}s", flush=True)
    print(f"  QPS:      {overall['qps']:.1f}", flush=True)
    print(f"  Latency (s): p50={overall['p50']:.3f}  p95={overall['p95']:.3f}  p99={overall['p99']:.3f}", flush=True)

    print("\n" + "-" * 60, flush=True)
    print("📊 Per-Endpoint Stats (latency in seconds)", flush=True)
    print("-" * 60, flush=True)
    print(f"  {'Endpoint':<22} {'Count':>6} {'OK':>5} {'Fail':>5} {'avg':>8} {'p50':>8} {'p95':>8} {'p99':>8}", flush=True)
    print("-" * 60, flush=True)
    endpoint_order = [
        "search sparse", "search hybrid", "search filters",
        "search/title", "search/title year",
        "paper detail", "paper detail fields",
        "citations", "citations pagination",
        "references", "references limit",
    ]
    for name in endpoint_order:
        if name not in per_endpoint:
            continue
        s = per_endpoint[name]
        print(f"  {name:<22} {s['count']:>6} {s['success']:>5} {s['fail']:>5} "
              f"{s['avg']:>7.3f}s {s['p50']:>7.3f}s {s['p95']:>7.3f}s {s['p99']:>7.3f}s", flush=True)
    print("=" * 60, flush=True)

    # Failed request details
    failed_endpoints = [n for n in endpoint_order if n in per_endpoint and per_endpoint[n]["fail"] > 0]
    if failed_requests:
        print(f"\n⚠️  Failed endpoints: {', '.join(failed_endpoints)}", flush=True)
        print("\n📋 Failed requests (this run):", flush=True)
        for i, req in enumerate(failed_requests[:50], 1):  # Cap at 50 to avoid huge output
            params_str = f" params={req['params']}" if req["params"] else ""
            print(f"   {i}. [{req['endpoint']}] {req['url']}{params_str}", flush=True)
            print(f"      elapsed={req['elapsed_s']}s  error={req['error']}", flush=True)
        if len(failed_requests) > 50:
            print(f"   ... and {len(failed_requests) - 50} more", flush=True)

        # Log failed requests to file for this run
        if log_failures:
            log_path = Path(log_failures)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n[{ts}] Load test failed requests: {len(failed_requests)}\n")
                f.write(f"  base={base}  workers={workers}  requests_per_endpoint={requests_per_endpoint}\n")
                for req in failed_requests:
                    params_str = f" params={req['params']}" if req["params"] else ""
                    f.write(f"  [{req['endpoint']}] {req['url']}{params_str}\n")
                    f.write(f"    elapsed={req['elapsed_s']}s  error={req['error']}\n")
            print(f"\n   📁 Logged to {log_path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load test for Paper Search API")
    parser.add_argument(
        "--base-url",
        default="http://localhost:4000",
        help="API base URL (e.g. http://210.45.70.162:4000)",
    )
    parser.add_argument("--workers", type=int, default=10, help="Concurrent workers")
    parser.add_argument("--requests", type=int, default=200, help="Requests per endpoint type")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout (s)")
    parser.add_argument(
        "--cooldown",
        type=int,
        default=0,
        metavar="SEC",
        help="Wait SEC seconds before starting (helps when running back-to-back tests)",
    )
    parser.add_argument("--debug", action="store_true", help="Print debug info when fetching sample paper")
    parser.add_argument("--api-key", default=None, help="API key for authentication (X-API-Key header)")
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument(
        "--log-failures",
        metavar="FILE",
        help="Append failed requests to file (default: test/load_failures.log)",
    )
    log_group.add_argument(
        "--no-log-failures",
        action="store_true",
        help="Do not log failed requests to file",
    )
    args = parser.parse_args()
    log_failures = None if args.no_log_failures else (args.log_failures or "test/load_failures.log")

    try:
        run_load_test(
            base_url=args.base_url,
            workers=args.workers,
            requests_per_endpoint=args.requests,
            timeout=args.timeout,
            log_failures=log_failures,
            cooldown=args.cooldown,
            debug=args.debug,
            api_key=args.api_key,
        )
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user.", flush=True)
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Load test failed: {e}", flush=True)
        raise
