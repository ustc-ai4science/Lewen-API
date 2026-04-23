"""Shared utilities for per-endpoint load tests.

Provides session management, request execution, statistics, report formatting,
and sample paper_id fetching. Each test_load_*.py script imports from here.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from dotenv import load_dotenv

load_dotenv()

_thread_local = threading.local()


def _should_bypass_proxy(url: str) -> bool:
    return "://localhost" in url or "://127.0.0.1" in url


def default_api_key() -> str | None:
    return (
        os.getenv("Lewen_API_KEY")
        or os.getenv("PAPER_SEARCH_API_KEY")
        or os.getenv("API_KEY")
    )


def get_session() -> requests.Session:
    """Return a per-thread reusable Session."""
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
        _thread_local.session.trust_env = False
    return _thread_local.session


SAMPLE_PAPER_QUERY = (
    "TimeDART: A Diffusion Autoregressive Transformer "
    "for Self-Supervised Time-Series Representations"
)


def get_sample_paper_id(base: str, timeout: int = 30, headers: dict | None = None) -> str | None:
    """Get paper_id for TimeDART via title search.

    Args:
        base: API base URL.
        timeout: Request timeout in seconds.
        headers: Optional request headers (e.g. API key).

    Returns:
        paper_id string or None.
    """
    for query in [SAMPLE_PAPER_QUERY, "TimeDART"]:
        try:
            with requests.Session() as s:
                if _should_bypass_proxy(base):
                    s.trust_env = False
                r = s.get(
                    f"{base}/paper/search/title",
                    params={"query": query, "limit": 10},
                    headers=headers,
                    timeout=timeout,
                )
            if r.status_code != 200:
                continue
            data = r.json()
            if not isinstance(data, dict) or not data.get("data"):
                continue
            for item in data["data"]:
                title = (item.get("title") or "").lower()
                if "timedart" in title:
                    return item.get("paperId")
            return data["data"][0].get("paperId")
        except Exception:
            continue
    return None


def single_request(
    url: str,
    params: dict | None = None,
    timeout: int = 30,
    headers: dict | None = None,
) -> tuple[bool, float, str | None]:
    """Execute one GET request.

    Args:
        url: Full request URL.
        params: Query parameters.
        timeout: Request timeout in seconds.
        headers: Optional request headers (e.g. API key).

    Returns:
        (success, elapsed_seconds, error_msg_or_None).
    """
    session = get_session()
    start = time.perf_counter()
    try:
        r = session.get(url, params=params, headers=headers, timeout=timeout)
        elapsed = time.perf_counter() - start
        if r.status_code == 200:
            return True, elapsed, None
        return False, elapsed, f"HTTP {r.status_code}"
    except requests.RequestException as e:
        elapsed = time.perf_counter() - start
        return False, elapsed, f"{type(e).__name__}: {e}"


def percentile(arr: list[float], p: float) -> float:
    """Compute percentile (p in 0..1)."""
    if not arr:
        return 0.0
    s = sorted(arr)
    idx = max(0, int(len(s) * p) - 1)
    return s[idx]


def run_load_test(
    cases: list[tuple[str, str, dict | None]],
    *,
    workers: int = 10,
    requests_per_case: int = 200,
    timeout: int = 30,
    log_file: str | None = None,
    title: str = "Load Test",
    headers: dict | None = None,
) -> None:
    """Run a concurrent load test on specified cases and print a report.

    Args:
        cases: List of (name, url, params) tuples.
        workers: Concurrent worker threads.
        requests_per_case: Number of requests per case.
        timeout: Per-request timeout in seconds.
        log_file: If set, append failures to this file.
        title: Title for the report header.
        headers: Optional request headers (e.g. API key).
    """
    tasks: list[tuple[str, str, dict | None]] = []
    for name, url, params in cases:
        for _ in range(requests_per_case):
            tasks.append((name, url, params))

    total = len(tasks)
    print("=" * 60)
    print(f"📊 {title}")
    print(f"   Workers: {workers}  |  Cases: {len(cases)}  |  "
          f"Requests: {total} ({requests_per_case}/case)")
    print("=" * 60, flush=True)

    results: list[tuple[str, bool, float, str | None, str, dict | None]] = []
    start = time.perf_counter()
    last_print = start
    done = 0

    def worker(task: tuple[str, str, dict | None]):
        name, url, params = task
        ok, elapsed, err = single_request(url, params, timeout, headers=headers)
        return name, ok, elapsed, err, url, params

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(worker, t) for t in tasks]
        for f in as_completed(futures):
            results.append(f.result())
            done += 1
            step = max(50, total // 10)
            if done % step == 0 or done == total:
                now = time.perf_counter()
                print(f"   ⏳ {done}/{total} ({100*done/total:.0f}%) — "
                      f"{now - start:.1f}s (+{now - last_print:.1f}s)",
                      flush=True)
                last_print = now

    elapsed_total = time.perf_counter() - start

    success_count = sum(1 for _, ok, *_ in results if ok)
    all_lat = [e for _, _, e, *_ in results]
    sorted_lat = sorted(all_lat) if all_lat else []

    print()
    print("-" * 60)
    print(f"  Total:    {total}")
    pct = 100 * success_count / total if total else 0
    print(f"  Success:  {success_count} ({pct:.1f}%)")
    print(f"  Failed:   {total - success_count}")
    print(f"  Duration: {elapsed_total:.2f}s")
    print(f"  QPS:      {total / elapsed_total:.1f}" if elapsed_total > 0 else "  QPS:      N/A")
    print(f"  Latency:  p50={statistics.median(all_lat):.3f}s  "
          f"p95={percentile(sorted_lat, 0.95):.3f}s  "
          f"p99={percentile(sorted_lat, 0.99):.3f}s")
    print("-" * 60)

    by_ep: dict[str, list[tuple[bool, float]]] = {}
    failed: list[dict] = []
    for name, ok, elapsed, err, url, params in results:
        by_ep.setdefault(name, []).append((ok, elapsed))
        if not ok:
            failed.append({"endpoint": name, "url": url, "params": params,
                           "elapsed_s": round(elapsed, 3), "error": err})

    print(f"\n  {'Endpoint':<24} {'Count':>5} {'OK':>5} {'Fail':>4}  "
          f"{'avg':>7} {'p50':>7} {'p95':>7} {'p99':>7}")
    print("  " + "-" * 76)
    case_names = [c[0] for c in cases]
    for name in case_names:
        items = by_ep.get(name, [])
        if not items:
            continue
        lats = [e for _, e in items]
        ok_n = sum(1 for o, _ in items if o)
        sl = sorted(lats)
        avg = sum(lats) / len(lats)
        print(f"  {name:<24} {len(items):>5} {ok_n:>5} {len(items)-ok_n:>4}  "
              f"{avg:>6.3f}s {statistics.median(lats):>6.3f}s "
              f"{percentile(sl, 0.95):>6.3f}s {percentile(sl, 0.99):>6.3f}s")
    print("=" * 60)

    if failed:
        fail_eps = sorted({f["endpoint"] for f in failed})
        print(f"\n⚠️  Failed endpoints: {', '.join(fail_eps)}")
        print(f"📋 Failed requests ({len(failed)}):")
        for i, req in enumerate(failed[:30], 1):
            p = f" params={req['params']}" if req["params"] else ""
            print(f"   {i}. [{req['endpoint']}] {req['url']}{p}")
            print(f"      elapsed={req['elapsed_s']}s  error={req['error']}")
        if len(failed) > 30:
            print(f"   ... and {len(failed) - 30} more")

        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n[{ts}] {title} — failed: {len(failed)}\n")
                f.write(f"  workers={workers}  requests_per_case={requests_per_case}\n")
                for req in failed:
                    p = f" params={req['params']}" if req["params"] else ""
                    f.write(f"  [{req['endpoint']}] {req['url']}{p}\n")
                    f.write(f"    elapsed={req['elapsed_s']}s  error={req['error']}\n")
            print(f"\n   📁 Logged to {log_path}")
    else:
        print("\n✅ All requests succeeded!")


def make_base_parser(description: str) -> argparse.ArgumentParser:
    """Create an ArgumentParser with common load test arguments.

    Args:
        description: Parser description string.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--base-url", default="http://localhost:4000",
                        help="API base URL")
    parser.add_argument("--workers", type=int, default=10,
                        help="Concurrent workers (default: 10)")
    parser.add_argument("--requests", type=int, default=500,
                        help="Requests per case (default: 500)")
    parser.add_argument("--timeout", type=int, default=30,
                        help="Per-request timeout in seconds (default: 30)")
    parser.add_argument("--no-log", action="store_true",
                        help="Do not log failures to file")
    parser.add_argument("--api-key", default=default_api_key(),
                        help="API key for authentication (X-API-Key header)")
    return parser
