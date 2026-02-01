from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

import re


def default_history_path() -> Path:
    """Persistent command history path.

    Stored alongside other app artifacts:
      ~/.truba_slurm_gui/history.jsonl
    """
    base = Path.home() / ".truba_slurm_gui"
    base.mkdir(parents=True, exist_ok=True)
    return base / "history.jsonl"


# Commands that likely contain secrets. If matched, they must NOT be persisted.
_SENSITIVE_PATTERNS = [
    # Generic secret keywords
    r"\b(pass(word|wd)?|parola|sifre|secret|token|apikey|api[_-]?key|bearer)\b",
    # Shell-style assignments: PASSWORD=..., TOKEN: ..., etc.
    r"\b(pass(word|wd)?|parola|sifre|secret|token|apikey|api[_-]?key)\s*[:=]",
    # Typical auth headers / tokens
    r"authorization\s*:\s*bearer\s+",
    # Tools that embed passwords
    r"\bsshpass\b",
    # PuTTY/Plink password arg (rare, but don't store)
    r"\b(-pw|--pw)\b",
]


def is_sensitive_command(cmd: str) -> bool:
    """Return True if the command likely contains a secret.

    This is intentionally conservative: if in doubt, skip persisting.
    """
    s = (cmd or "").strip()
    if not s:
        return False
    low = s.lower()
    for pat in _SENSITIVE_PATTERNS:
        try:
            if re.search(pat, low):
                return True
        except re.error:
            continue
    return False


_GLOBAL_STORE: "CommandHistoryStore | None" = None


def get_global_history_store() -> "CommandHistoryStore":
    """Process-wide singleton store.

    History is a single shared list + single backing file.
    UI widgets keep their own navigation cursor.
    """
    global _GLOBAL_STORE
    if _GLOBAL_STORE is None:
        _GLOBAL_STORE = CommandHistoryStore()
    return _GLOBAL_STORE


@dataclass
class CommandHistoryStore:
    """In-memory history + persistent append-only backing file (jsonl)."""

    path: Path = default_history_path()
    max_items: int = 300

    def __post_init__(self) -> None:
        self.items: List[str] = []
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self.path.exists():
            self.items = []
            return

        items: List[str] = []
        try:
            with self.path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        cmd = (obj.get("cmd") or "").strip()
                        if cmd:
                            items.append(cmd)
                    except Exception:
                        continue
        except Exception:
            items = []

        # Keep last N, remove consecutive duplicates
        cleaned: List[str] = []
        for c in items[-self.max_items :]:
            if cleaned and cleaned[-1] == c:
                continue
            cleaned.append(c)

        self.items = cleaned

    def _append_disk(self, cmd: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"cmd": cmd}, ensure_ascii=False) + "\n")
        except Exception:
            # Never break UI due to IO issues
            pass

    def add(self, cmd: str) -> None:
        cmd = (cmd or "").strip()
        if not cmd:
            return
        if is_sensitive_command(cmd):
            # Never persist secrets
            return
        if self.items and self.items[-1] == cmd:
            return

        self.items.append(cmd)
        if len(self.items) > self.max_items:
            self.items = self.items[-self.max_items :]
        self._append_disk(cmd)

    def clear_disk(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            pass
        self.items = []
