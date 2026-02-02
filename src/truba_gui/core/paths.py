from __future__ import annotations

import os
from pathlib import Path


def app_data_dir() -> Path:
    """Per-user app data directory used for logs/config/3rd-party downloads."""

    # Keep the historic folder name for backwards compatibility.
    base = Path.home() / ".truba_slurm_gui"
    base.mkdir(parents=True, exist_ok=True)
    return base


def third_party_dir() -> Path:
    d = app_data_dir() / "third_party"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_frozen_exe() -> bool:
    return bool(getattr(os, "frozen", False) or getattr(__import__("sys"), "frozen", False))
