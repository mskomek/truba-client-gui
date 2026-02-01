from __future__ import annotations

from pathlib import Path
from datetime import datetime

def _log_dir() -> Path:
    d = Path.home() / ".truba_slurm_gui"
    d.mkdir(parents=True, exist_ok=True)
    return d

def log_path() -> Path:
    return _log_dir() / "app.log"

def append_log(line: str) -> None:
    p = log_path()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        p.open("a", encoding="utf-8").write(f"[{ts}] {line}\n")
    except Exception:
        # logging must never crash the GUI
        pass
