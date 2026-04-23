from __future__ import annotations

import gzip
import json
import re
import sys
import zlib
from pathlib import Path
from typing import Any, Iterator

from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

BASE_URL = "https://api.semanticscholar.org/datasets/v1"
DATASETS = ["papers", "authors", "citations", "abstracts", "paper-ids"]
PAPER_DATA_ROOT = PROJECT_ROOT / "PaperData"
PROGRESS_FILE_NAME = "_merge_progress.json"
VALIDATION_PROGRESS_FILE = "_download_validation_progress.json"
QDRANT_TASK_FILE_NAME = "_qdrant_task.json"

BATCH_SIZE = config.INGEST_BATCH_SIZE
CHECKPOINT_RECORD_CHUNK = 100_000

STEP_PAPER_IDS_UPDATES = "paper-ids-updates"
STEP_PAPER_IDS_DELETES = "paper-ids-deletes"
STEP_PAPERS_UPDATES = "papers-updates"
STEP_PAPERS_DELETES = "papers-deletes"
STEP_ABSTRACTS_UPDATES = "abstracts-updates"
STEP_ABSTRACTS_DELETES = "abstracts-deletes"
STEP_CITATIONS_UPDATES = "citations-updates"
STEP_CITATIONS_DELETES = "citations-deletes"


def progress_kwargs() -> dict[str, Any]:
    return {
        "dynamic_ncols": True,
        "ascii": True,
        "mininterval": 0.5,
    }


def safe_filename(value: str) -> str:
    return re.sub(r"[^\w\-.]", "_", value)


def read_current_release() -> str | None:
    release_file = PROJECT_ROOT / "corpus" / "current_release.txt"
    if not release_file.exists():
        return None
    text = release_file.read_text().strip()
    return text if text else None


def find_nearest_release(releases: list[str], target: str) -> str | None:
    sorted_releases = sorted(releases)
    best = None
    for release in sorted_releases:
        if release <= target:
            best = release
    return best


def iter_diff_files(diff_dir: Path, desc: str) -> Iterator[dict[str, Any]]:
    if not diff_dir.exists():
        return

    files = sorted(
        f for f in diff_dir.iterdir() if f.is_file() and f.suffix in (".gz", ".jsonl", ".json")
    )
    if not files:
        return

    record_count = 0
    with tqdm(total=len(files), desc=desc, unit="file", **progress_kwargs()) as pbar:
        for file_path in files:
            try:
                if file_path.suffix == ".gz":
                    with gzip.open(file_path, "rt", encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                yield json.loads(line)
                                record_count += 1
                            except json.JSONDecodeError:
                                continue
                else:
                    with open(file_path, "r", encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                yield json.loads(line)
                                record_count += 1
                            except json.JSONDecodeError:
                                continue
            except EOFError as exc:
                raise RuntimeError(
                    f"Corrupted gzip diff file detected: {file_path}. "
                    "Please re-download the incremental diffs before continuing."
                ) from exc
            except zlib.error as exc:
                raise RuntimeError(
                    f"Corrupted gzip diff file detected: {file_path}. "
                    "Please re-download the incremental diffs before continuing."
                ) from exc
            except UnicodeDecodeError as exc:
                raise RuntimeError(
                    f"Invalid UTF-8 diff file detected: {file_path}. "
                    "Please re-download the incremental diffs before continuing."
                ) from exc
            except OSError as exc:
                raise RuntimeError(
                    f"Unreadable diff file detected: {file_path} ({exc}). "
                    "Please re-download the incremental diffs before continuing."
                ) from exc
            pbar.update(1)
            pbar.set_postfix(records=f"{record_count:,}")


def is_valid_download(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                while fh.read(1024 * 1024):
                    pass
        else:
            with open(path, "rt", encoding="utf-8") as fh:
                while fh.read(1024 * 1024):
                    pass
        return True
    except (EOFError, UnicodeDecodeError, OSError, zlib.error):
        return False


def load_merge_progress(progress_path: Path) -> dict[str, Any]:
    if not progress_path.exists():
        return {"completed_steps": [], "step_offsets": {}}
    try:
        with open(progress_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"completed_steps": [], "step_offsets": {}}
    state.setdefault("completed_steps", [])
    state.setdefault("step_offsets", {})
    state.pop("completed_files", None)
    state.pop("completed_file_counts", None)
    state.pop("qdrant_upsert_corpus_ids", None)
    state.pop("qdrant_delete_paper_ids", None)
    return state


def save_json_atomic(path: Path, state: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def save_merge_progress(progress_path: Path, state: dict[str, Any]) -> None:
    save_json_atomic(progress_path, state)


def mark_step_completed(progress_path: Path, state: dict[str, Any], step: str) -> None:
    completed_steps = state.setdefault("completed_steps", [])
    if step not in completed_steps:
        completed_steps.append(step)
    state.setdefault("step_offsets", {}).pop(step, None)
    save_merge_progress(progress_path, state)


def step_completed(state: dict[str, Any], step: str) -> bool:
    return step in set(state.get("completed_steps", []))


def get_step_offset(state: dict[str, Any], step: str) -> int:
    return int(state.setdefault("step_offsets", {}).get(step, 0) or 0)


def mark_step_offset(progress_path: Path, state: dict[str, Any], step: str, offset: int) -> None:
    state.setdefault("step_offsets", {})[step] = offset
    save_merge_progress(progress_path, state)
    print(f"  💾 Checkpoint saved: {step} -> {offset:,}", flush=True)


def load_validation_progress(progress_path: Path) -> dict[str, Any]:
    if not progress_path.exists():
        return {"validated_files": []}
    try:
        with open(progress_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"validated_files": []}
    state.setdefault("validated_files", [])
    return state


def normalize_arxiv_id(arxiv_id: str) -> str:
    value = str(arxiv_id).strip()
    match = re.match(r"^(\d{4}\.\d{4,5})(v\d+)?$", value)
    if match:
        return match.group(1)
    return value


def safe_json(obj: Any) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False)
