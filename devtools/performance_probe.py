"""Opt-in source performance recorder.

This module lives outside ``src`` and is loaded only by ``python -m truba_gui``
when TRUBA_GUI_PERF_DEBUG=1. Frozen release builds never load it.
"""

from __future__ import annotations

import atexit
import cProfile
import json
import os
import pstats
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PerformanceSession:
    def __init__(
        self,
        repo_root: Path,
        *,
        interval_ms: int = 100,
        slow_ms: int = 250,
        now=time.perf_counter,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.source_root = (self.repo_root / "src" / "truba_gui").resolve()
        self.interval_ms = interval_ms
        self.slow_ms = slow_ms
        self._now = now
        self._started_at = now()
        self._expected_tick: float | None = None
        self._timer = None
        self._finished = False
        self._profiler = cProfile.Profile()

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        report_dir = self.repo_root / "reports" / "performance"
        report_dir.mkdir(parents=True, exist_ok=True)
        self.report_path = report_dir / f"session-{stamp}-{os.getpid()}.jsonl"

    def start(self) -> None:
        self._profiler.enable()
        self.write_event(
            "session_start",
            python=sys.version.split()[0],
            pid=os.getpid(),
            interval_ms=self.interval_ms,
            slow_ms=self.slow_ms,
        )

    def mark(self, name: str) -> None:
        self.write_event(
            "startup_checkpoint",
            name=name,
            elapsed_ms=round((self._now() - self._started_at) * 1000, 3),
        )

    def attach_to_app(self, app: Any) -> None:
        from PySide6.QtCore import QTimer

        timer = QTimer(app)
        timer.setInterval(self.interval_ms)
        timer.timeout.connect(self._heartbeat)
        self._expected_tick = self._now() + (self.interval_ms / 1000)
        timer.start()
        self._timer = timer
        self.mark("event_loop_monitor_attached")

    def measure_tick(self, observed_at: float) -> float:
        if self._expected_tick is None:
            self._expected_tick = observed_at + (self.interval_ms / 1000)
            return 0.0

        delay_ms = max(0.0, (observed_at - self._expected_tick) * 1000)
        self._expected_tick = observed_at + (self.interval_ms / 1000)
        if delay_ms >= self.slow_ms:
            self.write_event(
                "event_loop_delay",
                delay_ms=round(delay_ms, 3),
                threshold_ms=self.slow_ms,
            )
        return delay_ms

    def _heartbeat(self) -> None:
        self.measure_tick(self._now())

    def write_event(self, event: str, **details: Any) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **details,
        }
        with self.report_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def finish(self, exit_code: int | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        if self._timer is not None:
            self._timer.stop()
        self._profiler.disable()
        self._write_profile_summary()
        self.write_event(
            "session_end",
            exit_code=exit_code,
            elapsed_ms=round((self._now() - self._started_at) * 1000, 3),
        )
        print(f"[perf-debug] report: {self.report_path}", file=sys.stderr)

    def _write_profile_summary(self) -> None:
        stats = pstats.Stats(self._profiler)
        rows = []
        source_prefix = os.path.normcase(str(self.source_root))
        for (filename, line, function), values in stats.stats.items():
            normalized = os.path.normcase(str(Path(filename).resolve()))
            if not normalized.startswith(source_prefix):
                continue
            primitive_calls, total_calls, total_time, cumulative_time, _callers = values
            rows.append(
                {
                    "file": str(Path(filename).resolve().relative_to(self.repo_root)),
                    "line": line,
                    "function": function,
                    "calls": total_calls,
                    "primitive_calls": primitive_calls,
                    "total_ms": round(total_time * 1000, 3),
                    "cumulative_ms": round(cumulative_time * 1000, 3),
                }
            )
        rows.sort(key=lambda row: row["cumulative_ms"], reverse=True)
        self.write_event("source_profile_summary", functions=rows[:50])


_SESSION: PerformanceSession | None = None


def start(repo_root: Path) -> None:
    global _SESSION
    if _SESSION is not None:
        return
    interval_ms = int(os.environ.get("TRUBA_GUI_PERF_INTERVAL_MS", "100"))
    slow_ms = int(os.environ.get("TRUBA_GUI_PERF_SLOW_MS", "250"))
    _SESSION = PerformanceSession(
        repo_root,
        interval_ms=max(10, interval_ms),
        slow_ms=max(1, slow_ms),
    )
    _SESSION.start()
    atexit.register(finish)


def mark(name: str) -> None:
    if _SESSION is not None:
        _SESSION.mark(name)


def attach_to_app(app: Any) -> None:
    if _SESSION is not None:
        _SESSION.attach_to_app(app)


def finish(exit_code: int | None = None) -> None:
    if _SESSION is not None:
        _SESSION.finish(exit_code)
