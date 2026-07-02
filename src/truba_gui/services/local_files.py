from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class LocalEntry:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    mtime: int = 0


def list_windows_drives() -> List[LocalEntry]:
    entries: List[LocalEntry] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.exists(root):
            entries.append(LocalEntry(root, root, True))
    if entries:
        return entries
    root = Path.home().anchor or os.path.abspath(os.sep)
    return [LocalEntry(root, root, True)]


def list_local_entries(directory: str) -> List[LocalEntry]:
    path = Path(directory).expanduser()
    entries: List[LocalEntry] = []
    with os.scandir(path) as iterator:
        for item in iterator:
            try:
                stat = item.stat(follow_symlinks=False)
                is_dir = item.is_dir(follow_symlinks=False)
                entries.append(
                    LocalEntry(
                        name=item.name,
                        path=os.path.abspath(item.path),
                        is_dir=is_dir,
                        size=0 if is_dir else int(stat.st_size),
                        mtime=int(stat.st_mtime),
                    )
                )
            except (OSError, PermissionError):
                continue
    entries.sort(key=lambda entry: (not entry.is_dir, entry.name.casefold()))
    return entries


def safe_initial_local_directory(saved: str = "") -> str:
    candidates = [saved, str(Path.home()), os.getcwd()]
    for candidate in candidates:
        if candidate and os.path.isdir(os.path.expanduser(candidate)):
            return os.path.abspath(os.path.expanduser(candidate))
    return os.path.abspath(os.sep)
