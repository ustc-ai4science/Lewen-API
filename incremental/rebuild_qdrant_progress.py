from __future__ import annotations

import argparse
from pathlib import Path

from qdrant_manifest import write_qdrant_task


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Repair helper: rebuild _qdrant_task.json for one incremental directory."
    )
    parser.add_argument("incr_dir", type=Path, help="Path to incremental dir")
    args = parser.parse_args()
    write_qdrant_task(args.incr_dir)
