#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find and delete __pycache__ directories under src/."
    )
    parser.add_argument(
        "--root",
        default="src",
        help="Root directory to scan. Defaults to src.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching directories without deleting them.",
    )
    return parser.parse_args()


def collect_pycache_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")

    matches = [path for path in root.rglob("__pycache__") if path.is_dir()]
    matches.sort(key=lambda path: len(path.parts), reverse=True)
    return matches


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    root = Path(args.root)
    if not root.is_absolute():
        root = (repo_root / root).resolve()
    else:
        root = root.resolve()

    try:
        matches = collect_pycache_dirs(root)
    except NotADirectoryError as exc:
        print(exc, file=sys.stderr)
        return 2

    if not matches:
        print(f"No __pycache__ directories found under {root}.")
        return 0

    action = "Would remove" if args.dry_run else "Removing"
    for path in matches:
        print(f"{action}: {path}")
        if not args.dry_run:
            shutil.rmtree(path)

    print(f"{'Would remove' if args.dry_run else 'Removed'} {len(matches)} __pycache__ directories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
