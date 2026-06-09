#!/usr/bin/env python3
"""Extract ISO images from the current directory into extract_iso/."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

OUTPUT_ROOT = Path("extract_iso")


def _extract_command(exe: str, iso_path: Path, output_dir: Path) -> list[str]:
    if exe in {"7z", "7za"}:
        return [exe, "x", "-y", f"-o{output_dir}", str(iso_path)]
    if exe == "bsdtar":
        return [exe, "-C", str(output_dir), "-xf", str(iso_path)]
    if exe == "unar":
        return [exe, "-o", str(output_dir), str(iso_path)]
    raise ValueError(f"Unsupported extractor: {exe}")


def extract_iso(iso_path: Path) -> None:
    target_dir = OUTPUT_ROOT / iso_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)

    for exe in ("7z", "7za", "bsdtar", "unar"):
        if not shutil.which(exe):
            continue
        try:
            subprocess.run(_extract_command(exe, iso_path, target_dir), check=True)
            return
        except subprocess.CalledProcessError:
            continue

    raise SystemExit(
        f"Could not extract {iso_path.name}: install 7z, bsdtar, or unar on the remote system."
    )


def main() -> int:
    iso_files = sorted(Path.cwd().glob("*.iso"))
    if not iso_files:
        print("No ISO files found in the current directory.")
        return 0

    OUTPUT_ROOT.mkdir(exist_ok=True)
    failed: list[str] = []
    for iso_path in iso_files:
        try:
            extract_iso(iso_path)
            print(f"Extracted {iso_path.name} -> {OUTPUT_ROOT / iso_path.stem}")
        except Exception as exc:
            failed.append(f"{iso_path.name}: {exc}")

    if failed:
        for line in failed:
            print(line, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
