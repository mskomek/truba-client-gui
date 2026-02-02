from __future__ import annotations

"""Lightweight external process registry.

Purpose
-------
TrubaGUI may spawn external helper processes (e.g. VcXsrv, plink/ssh for X11).
On Windows, these can be left orphaned if the app crashes or is killed.

This registry is best-effort and **log-only**: it helps cleanup stale records
and optionally terminates known orphan helpers at startup.

No UI is shown from here.
"""

import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from truba_gui.core.logging import get_logger


_DIR = Path.home() / ".truba_slurm_gui"
_PATH = _DIR / "processes.json"
_log = get_logger("truba_gui.proc")


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _read_all() -> Dict[str, Any]:
    try:
        if _PATH.exists():
            return json.loads(_PATH.read_text(encoding="utf-8", errors="ignore") or "{}") or {}
    except Exception:
        return {}
    return {}


def _write_all(data: Dict[str, Any]) -> None:
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def register(pid: int, *, kind: str, cmd: str = "", meta: Optional[Dict[str, Any]] = None) -> None:
    """Register an externally spawned process."""
    try:
        pid = int(pid)
    except Exception:
        return
    if pid <= 0:
        return
    data = _read_all()
    data[str(pid)] = {
        "pid": pid,
        "kind": str(kind or ""),
        "cmd": str(cmd or ""),
        "meta": meta or {},
        "ts": int(time.time()),
        "host_pid": os.getpid(),
    }
    _write_all(data)


def unregister(pid: int) -> None:
    try:
        pid = int(pid)
    except Exception:
        return
    data = _read_all()
    if str(pid) in data:
        data.pop(str(pid), None)
        _write_all(data)


def _pid_exists_windows(pid: int) -> bool:
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (proc.stdout or "")
        return str(pid) in out
    except Exception:
        return False


def _kill_tree_windows(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def cleanup_orphans(*, aggressive: bool = False, age_s: int = 2 * 3600) -> None:
    """Cleanup stale records and (optionally) terminate known orphan helpers.

    - Always removes records for PIDs that no longer exist.
    - If aggressive=True on Windows, will taskkill remaining registered PIDs.
      This is intended only for helpers spawned by TrubaGUI.
    """
    data = _read_all()
    if not data:
        return

    changed = False
    now = int(time.time())
    for pid_s, rec in list(data.items()):
        try:
            pid = int(pid_s)
        except Exception:
            data.pop(pid_s, None)
            changed = True
            continue

        exists = True
        if _is_windows():
            exists = _pid_exists_windows(pid)
        # Non-windows: don't assume we can check/kill.

        if not exists:
            data.pop(pid_s, None)
            changed = True
            continue

        if aggressive and _is_windows():
            kind = str((rec or {}).get("kind") or "")
            ts = int((rec or {}).get("ts") or 0)
            # Be conservative: only kill helpers that look like ours and are "old".
            if kind.startswith("vcxsrv") or kind.startswith("x11_"):
                if ts and (now - ts) >= max(60, int(age_s)):
                    _log.info(f"orphan cleanup: killing pid={pid} kind={kind}")
                    _kill_tree_windows(pid)
                    data.pop(pid_s, None)
                    changed = True

    if changed:
        _write_all(data)
