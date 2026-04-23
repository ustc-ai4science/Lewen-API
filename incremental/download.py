from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests
from tqdm import tqdm

from common import (
    BASE_URL,
    DATASETS,
    PAPER_DATA_ROOT,
    find_nearest_release,
    progress_kwargs,
    read_current_release,
    safe_filename,
)
import config

MAX_RETRIES = 10
RETRY_BACKOFF_BASE = 3
RETRY_BACKOFF_MAX = 60
RETRYABLE_STATUS_CODES = {400, 408, 429, 500, 502, 503, 504}


def get_headers() -> dict[str, str]:
    headers = {}
    if config.S2_API_KEY:
        headers["x-api-key"] = config.S2_API_KEY
    return headers


def request_with_retry(
    method: str,
    url: str,
    *,
    use_api_key: bool = True,
    **kwargs,
) -> requests.Response:
    headers = kwargs.pop("headers", {}) or {}
    if use_api_key:
        headers.update(get_headers())

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            wait = min(RETRY_BACKOFF_BASE * (2 ** attempt), RETRY_BACKOFF_MAX)
            print(
                f"   ⏳ Network error: {type(exc).__name__}. Retry {attempt + 1}/{MAX_RETRIES} in {wait}s...",
                flush=True,
            )
            time.sleep(wait)
            continue

        if response.status_code not in RETRYABLE_STATUS_CODES:
            response.raise_for_status()
            return response

        wait = min(
            int(response.headers.get("Retry-After", RETRY_BACKOFF_BASE * (2 ** attempt))),
            RETRY_BACKOFF_MAX,
        )
        label = "Rate limited" if response.status_code == 429 else f"HTTP {response.status_code}"
        print(f"   ⏳ {label}. Retry {attempt + 1}/{MAX_RETRIES} in {wait}s...", flush=True)
        time.sleep(wait)

    if last_exc:
        raise last_exc
    response.raise_for_status()  # type: ignore[possibly-undefined]
    return response  # type: ignore[possibly-undefined]


def list_releases() -> list[str]:
    response = request_with_retry("GET", f"{BASE_URL}/release/")
    return response.json()


def get_diffs(start_release: str, end_release: str, dataset_name: str) -> dict:
    response = request_with_retry("GET", f"{BASE_URL}/diffs/{start_release}/to/{end_release}/{dataset_name}")
    return response.json()


def download_file_to_path(url: str, dest_path: Path, desc: str = "") -> None:
    is_s3 = "s3.amazonaws.com" in url or "s3.us-west-2" in url
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

    existing_bytes = tmp_path.stat().st_size if tmp_path.exists() else 0
    extra_headers: dict[str, str] = {}
    if existing_bytes > 0:
        extra_headers["Range"] = f"bytes={existing_bytes}-"

    response = request_with_retry(
        "GET",
        url,
        use_api_key=not is_s3,
        stream=True,
        headers=extra_headers,
    )

    if response.status_code == 206:
        content_range = response.headers.get("Content-Range", "")
        total = int(content_range.split("/")[-1]) if "/" in content_range else 0
        mode = "ab"
        initial = existing_bytes
    else:
        total = int(response.headers.get("content-length", 0))
        mode = "wb"
        initial = 0

    if initial > 0:
        print(f"      ↪ Resuming from {initial / 1024 / 1024:.1f} MB", flush=True)

    with (
        open(tmp_path, mode) as fh,
        tqdm(
            total=total or None,
            initial=initial,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=desc or dest_path.name,
            leave=False,
            **progress_kwargs(),
        ) as pbar,
    ):
        for chunk in response.iter_content(chunk_size=65536):
            fh.write(chunk)
            pbar.update(len(chunk))

    tmp_path.rename(dest_path)


def ensure_expected_file(url: str, dest: Path, label: str) -> None:
    if dest.exists():
        print(f"      ⏭️ skip (exists): {dest.name}", flush=True)
        return
    download_file_to_path(url, dest, desc=label)
    print(f"      ✅ downloaded: {dest.name}", flush=True)


def download_incremental_diffs(
    start_release: str,
    end_release: str = "latest",
    datasets: list[str] | None = None,
    output_root: Path | None = None,
) -> Path:
    datasets = datasets or DATASETS
    output_root = output_root or PAPER_DATA_ROOT
    incr_dir = output_root / "incremental" / f"{start_release}_to_{end_release}"
    incr_dir.mkdir(parents=True, exist_ok=True)

    print(f"📂 Incremental output: {incr_dir}", flush=True)
    print(f"📅 Range: {start_release} → {end_release}", flush=True)
    print(f"📦 Datasets: {datasets}", flush=True)
    print("🛠️ Mode: download", flush=True)

    for dataset in datasets:
        print(f"\n🚀 Fetching diffs for {dataset}...", flush=True)
        try:
            response = get_diffs(start_release, end_release, dataset)
        except requests.HTTPError as exc:
            print(f"⚠️ API error for {dataset}: {exc}", flush=True)
            continue

        diffs = response.get("diffs", [])
        if not diffs:
            print(f"   No diffs for {dataset} (already up to date)", flush=True)
            continue

        dataset_dir = incr_dir / dataset
        updates_dir = dataset_dir / "updates"
        deletes_dir = dataset_dir / "deletes"
        updates_dir.mkdir(parents=True, exist_ok=True)
        deletes_dir.mkdir(parents=True, exist_ok=True)

        for idx, diff in enumerate(diffs):
            from_release = diff.get("from_release", "?")
            to_release = diff.get("to_release", "?")
            print(f"   Diff {idx + 1}/{len(diffs)}: {from_release} → {to_release}", flush=True)

            for file_idx, url in enumerate(diff.get("update_files", [])):
                ext = ".gz" if ".gz" in url.lower() else ".jsonl"
                name = f"{safe_filename(from_release)}_{safe_filename(to_release)}_{file_idx}{ext}"
                ensure_expected_file(url, updates_dir / name, f"[{dataset}] updates {file_idx + 1}")

            for file_idx, url in enumerate(diff.get("delete_files", [])):
                ext = ".gz" if ".gz" in url.lower() else ".jsonl"
                name = f"{safe_filename(from_release)}_{safe_filename(to_release)}_{file_idx}{ext}"
                ensure_expected_file(url, deletes_dir / name, f"[{dataset}] deletes {file_idx + 1}")

    print(f"\n✅ Incremental diffs saved to: {incr_dir}", flush=True)
    return incr_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download S2 incremental diffs between two releases.")
    parser.add_argument("--start", type=str, default=None, help="Start release date")
    parser.add_argument("--end", type=str, default="latest", help="End release date or latest")
    args = parser.parse_args()

    start = args.start or read_current_release()
    if not start:
        print("❌ No start release specified and corpus/current_release.txt not found.", flush=True)
        sys.exit(1)

    end = args.end
    releases = list_releases()
    print(f"📋 Available releases (last 5): {releases[-5:]}", flush=True)
    print(f"📌 Current release: {start}", flush=True)

    if end == "latest":
        end = releases[-1] if releases else end
        print(f"   Resolved 'latest' to: {end}", flush=True)
    elif end not in releases:
        nearest = find_nearest_release(releases, end)
        if nearest:
            print(f"   Using nearest end release: {nearest} (requested {end})", flush=True)
            end = nearest

    if start >= end:
        print(f"✅ Already up to date (current: {start}, target: {end})", flush=True)
        sys.exit(0)

    incr_dir = download_incremental_diffs(start_release=start, end_release=end)
    print(f"\n📦 END_RELEASE={end}", flush=True)
    print(f"📦 INCR_DIR={incr_dir}", flush=True)
