from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import (
    DATASETS,
    PAPER_DATA_ROOT,
    VALIDATION_PROGRESS_FILE,
    is_valid_download,
    load_validation_progress,
    progress_kwargs,
    read_current_release,
    safe_filename,
    save_json_atomic,
)
from download import download_file_to_path, find_nearest_release, get_diffs, list_releases


def mark_validated(progress_path: Path, state: dict, file_path: Path, incr_dir: Path) -> None:
    rel_path = str(file_path.relative_to(incr_dir))
    validated = state.setdefault("validated_files", [])
    if rel_path not in validated:
        validated.append(rel_path)
        save_json_atomic(progress_path, state)


def validate_expected_file(
    *,
    url: str,
    dest: Path,
    label: str,
    incr_dir: Path,
    progress_path: Path,
    progress_state: dict,
) -> None:
    rel_path = str(dest.relative_to(incr_dir))
    if rel_path in set(progress_state.get("validated_files", [])) and dest.exists():
        print(f"      ⏭️ skip (validated): {dest.name}", flush=True)
        return

    if not dest.exists():
        print(f"      ↻ missing file, downloading: {dest.name}", flush=True)
        download_file_to_path(url, dest, desc=label)
    elif not is_valid_download(dest):
        print(f"      ♻️ re-download invalid file: {dest.name}", flush=True)
        dest.unlink()
        download_file_to_path(url, dest, desc=label)

    if not is_valid_download(dest):
        raise RuntimeError(f"Validation failed after re-download: {dest}")

    mark_validated(progress_path, progress_state, dest, incr_dir)
    print(f"      ✅ validated: {dest.name}", flush=True)


def validate_incremental_diffs(
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
    print("🛠️ Mode: validate", flush=True)

    progress_path = incr_dir / VALIDATION_PROGRESS_FILE
    progress_state = load_validation_progress(progress_path)

    for dataset in datasets:
        print(f"\n🚀 Fetching diffs for {dataset}...", flush=True)
        response = get_diffs(start_release, end_release, dataset)
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
                validate_expected_file(
                    url=url,
                    dest=updates_dir / name,
                    label=f"[{dataset}] updates {file_idx + 1}",
                    incr_dir=incr_dir,
                    progress_path=progress_path,
                    progress_state=progress_state,
                )

            for file_idx, url in enumerate(diff.get("delete_files", [])):
                ext = ".gz" if ".gz" in url.lower() else ".jsonl"
                name = f"{safe_filename(from_release)}_{safe_filename(to_release)}_{file_idx}{ext}"
                validate_expected_file(
                    url=url,
                    dest=deletes_dir / name,
                    label=f"[{dataset}] deletes {file_idx + 1}",
                    incr_dir=incr_dir,
                    progress_path=progress_path,
                    progress_state=progress_state,
                )

    print(f"\n✅ Incremental diffs validated under: {incr_dir}", flush=True)
    return incr_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate S2 incremental diffs between two releases.")
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

    incr_dir = validate_incremental_diffs(start_release=start, end_release=end)
    print(f"\n📦 END_RELEASE={end}", flush=True)
    print(f"📦 INCR_DIR={incr_dir}", flush=True)
