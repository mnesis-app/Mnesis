#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


def _is_tmp_artifact(path: Path) -> bool:
    name = path.name
    return name.startswith(".tmp") or name == ".tmphome"


def _remove_path(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink(missing_ok=True)
        except TypeError:
            if path.exists():
                path.unlink()
    return True


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    removed: list[str] = []

    for item in repo_root.iterdir():
        if not _is_tmp_artifact(item):
            continue
        if _remove_path(item):
            removed.append(item.name)

    # Remove nested Python cache dirs as housekeeping.
    for cache_dir in repo_root.rglob("__pycache__"):
        _remove_path(cache_dir)

    if removed:
        print(f"Removed {len(removed)} workspace tmp artifact(s): {', '.join(sorted(removed))}")
    else:
        print("No workspace tmp artifacts found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
