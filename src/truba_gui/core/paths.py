from __future__ import annotations

from pathlib import Path


def app_data_dir() -> Path:
    """Return user-writable app data directory (~/.truba_slurm_gui)."""
    d = Path.home() / ".truba_slurm_gui"
    d.mkdir(parents=True, exist_ok=True)
    return d


def third_party_dir() -> Path:
    """Return directory for downloaded third-party tools."""
    d = app_data_dir() / "third_party"
    d.mkdir(parents=True, exist_ok=True)
    return d
