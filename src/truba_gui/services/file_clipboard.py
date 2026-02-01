from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

@dataclass
class FileClipboard:
    op: str  # "copy" or "move"
    paths: List[str]

class _GlobalClipboard:
    def __init__(self):
        self._data: Optional[FileClipboard] = None

    def set(self, op: str, paths: List[str]):
        op = (op or "").lower().strip()
        if op not in ("copy", "move"):
            raise ValueError("op must be 'copy' or 'move'")
        self._data = FileClipboard(op=op, paths=list(paths))

    def clear(self):
        self._data = None

    def get(self) -> Optional[FileClipboard]:
        return self._data

_GLOBAL = _GlobalClipboard()

def get_file_clipboard() -> _GlobalClipboard:
    return _GLOBAL
