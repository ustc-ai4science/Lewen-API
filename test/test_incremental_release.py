"""Verify incremental release papers via API using sampled arXiv IDs.

This test does not query SQLite directly. It samples a few arXiv papers from
incremental `papers/updates` diff files whose `publicationdate` falls inside
the target range, then fetches them from the API via `/paper/{paper_id}`.

Usage:
    python test/test_incremental_release.py
    python test/test_incremental_release.py --base-url http://localhost:4000
    python test/test_incremental_release.py --incr-dir PaperData/incremental/2026-01-27_to_2026-03-10
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

PASS = "✅"
FAIL = "❌"


def _normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _should_bypass_proxy(url: str) -> bool:
    return "://localhost" in url or "://127.0.0.1" in url


def _default_api_key() -> str | None:
    return (
        os.getenv("Lewen_API_KEY")
        or os.getenv("PAPER_SEARCH_API_KEY")
        or os.getenv("API_KEY")
    )


def _sample_arxiv_records(
    incr_dir: Path,
    start_date: str,
    end_date: str,
    sample_limit: int,
) -> list[dict]:
    updates_dir = incr_dir / "papers" / "updates"
    if not updates_dir.exists():
        raise FileNotFoundError(f"papers updates dir not found: {updates_dir}")

    by_date: dict[str, list[dict]] = {}
    files = sorted(updates_dir.glob("*.gz"))
    print(f"🔎 Scanning incremental diff files... ({len(files)} files)", flush=True)
    for path in tqdm(
        files,
        desc="[incremental verify] scan",
        unit="file",
        dynamic_ncols=True,
        ascii=True,
        mininterval=0.5,
    ):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                ext = rec.get("externalids") or {}
                arxiv_id = ext.get("ArXiv") or ext.get("arXiv")
                pub_date = rec.get("publicationdate")
                if not arxiv_id or not pub_date:
                    continue
                if not (start_date <= pub_date <= end_date):
                    continue
                by_date.setdefault(pub_date, []).append(
                    {
                        "arxiv_id": arxiv_id,
                        "publicationdate": pub_date,
                        "title": rec.get("title") or "",
                    }
                )
    if not by_date:
        return []

    dates = sorted(by_date)
    print(f"📅 Found {len(dates):,} publication date(s) with arXiv samples in range", flush=True)
    if len(dates) <= sample_limit:
        samples = []
        for date in dates:
            samples.append(by_date[date][0])
        samples = samples[:sample_limit]
        print(f"🧪 Sampled {len(samples)}/{sample_limit} papers", flush=True)
        return samples

    samples: list[dict] = []
    used_dates: set[str] = set()
    for i in range(sample_limit):
        idx = round(i * (len(dates) - 1) / (sample_limit - 1))
        date = dates[idx]
        used_dates.add(date)
        samples.append(by_date[date][0])

    if len(samples) < sample_limit:
        for date in dates:
            if date in used_dates:
                continue
            samples.append(by_date[date][0])
            if len(samples) >= sample_limit:
                break

    print(f"🧪 Sampled {len(samples)}/{sample_limit} papers", flush=True)
    return samples


def _fetch_paper(base_url: str, paper_id: str, api_key: str | None) -> requests.Response:
    headers = {"X-API-Key": api_key} if api_key else None
    with requests.Session() as s:
        if _should_bypass_proxy(base_url):
            s.trust_env = False
        return s.get(
            f"{base_url.rstrip('/')}/paper/{paper_id}",
            params={"fields": "publicationDate,title,externalIds"},
            headers=headers,
            timeout=30,
        )


def run_test(
    base_url: str,
    incr_dir: Path,
    start_date: str,
    end_date: str,
    sample_limit: int,
    api_key: str | None,
) -> bool:
    try:
        samples = _sample_arxiv_records(incr_dir, start_date, end_date, sample_limit)
    except FileNotFoundError as e:
        print(f"{FAIL} {e}")
        return False

    print("=" * 60)
    print("Incremental Release API Verification")
    print("=" * 60)
    print(f"Base URL:     {base_url}")
    print(f"Incremental:  {incr_dir}")
    print(f"Date Range:   {start_date} -> {end_date}")

    if not samples:
        print(f"\n{FAIL} No sampled arXiv records found in incremental diff.")
        return False

    print(f"\nSampled {len(samples)} arXiv IDs from incremental diff:")
    for item in samples:
        print(f"- {item['arxiv_id']}  ({item['publicationdate']})  {item['title'][:90]}")

    all_ok = True
    failure_reasons: Counter[str] = Counter()
    print("\nAPI checks:")
    for idx, item in enumerate(samples, start=1):
        arxiv_id = item["arxiv_id"]
        expected_pub = item["publicationdate"]
        expected_title = item["title"]
        print(f"  ↻ Verifying sample {idx}/{len(samples)}: {arxiv_id}", flush=True)
        try:
            r = _fetch_paper(base_url, arxiv_id, api_key)
        except requests.RequestException as e:
            print(f"  {FAIL} {arxiv_id}: request failed: {e}")
            all_ok = False
            failure_reasons["request_failed"] += 1
            continue

        if r.status_code != 200:
            print(f"  {FAIL} {arxiv_id}: HTTP {r.status_code} {r.text[:120]}")
            all_ok = False
            failure_reasons[f"http_{r.status_code}"] += 1
            continue

        try:
            data = r.json()
        except Exception:
            print(f"  {FAIL} {arxiv_id}: non-JSON response")
            all_ok = False
            failure_reasons["non_json"] += 1
            continue

        actual_pub = data.get("publicationDate")
        actual_title = data.get("title") or ""
        external_ids = data.get("externalIds") or {}
        actual_arxiv = external_ids.get("ArXiv") or external_ids.get("arXiv")
        if actual_pub != expected_pub:
            print(f"  {FAIL} {arxiv_id}: publicationDate mismatch api={actual_pub} expected={expected_pub}")
            all_ok = False
            failure_reasons["publication_date_mismatch"] += 1
            continue

        if _normalize_text(actual_title) != _normalize_text(expected_title):
            print(
                f"  {FAIL} {arxiv_id}: title mismatch "
                f"api={actual_title[:80]!r} expected={expected_title[:80]!r}",
            )
            all_ok = False
            failure_reasons["title_mismatch"] += 1
            continue

        if actual_arxiv != arxiv_id:
            print(f"  {FAIL} {arxiv_id}: externalIds mismatch api={actual_arxiv} expected={arxiv_id}")
            all_ok = False
            failure_reasons["external_ids_mismatch"] += 1
            continue

        print(f"  {PASS} {arxiv_id}: publicationDate={actual_pub}", flush=True)

    passed = len(samples) - sum(failure_reasons.values())
    print("\nSummary:")
    print(f"  Passed: {passed}/{len(samples)}", flush=True)
    print(f"  Failed: {len(samples) - passed}/{len(samples)}", flush=True)
    if failure_reasons:
        print("  Failure reasons:", flush=True)
        for reason, count in sorted(failure_reasons.items()):
            print(f"  - {reason}: {count}", flush=True)

    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify incremental release papers via API")
    parser.add_argument("--base-url", default="http://localhost:4000", help="API base URL")
    parser.add_argument(
        "--incr-dir",
        type=Path,
        default=Path("PaperData/incremental/2026-01-27_to_2026-03-10"),
        help="Incremental directory",
    )
    parser.add_argument("--start-date", default="2026-01-27", help="Inclusive start publication_date")
    parser.add_argument("--end-date", default="2026-03-10", help="Inclusive end publication_date")
    parser.add_argument("--sample-limit", type=int, default=10, help="Number of uniformly sampled arXiv IDs")
    parser.add_argument("--api-key", default=_default_api_key(), help="API key for X-API-Key header")
    args = parser.parse_args()

    ok = run_test(
        base_url=args.base_url,
        incr_dir=args.incr_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        sample_limit=args.sample_limit,
        api_key=args.api_key,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
