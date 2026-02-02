from __future__ import annotations

from pathlib import Path


def _pkg_root() -> Path:
    # truba_gui/core/resources.py -> truba_gui/
    return Path(__file__).resolve().parents[1]


def read_doc_text(filename: str) -> str:
    """Read a documentation file shipped inside the package (best-effort)."""
    candidates = [
        _pkg_root() / "docs" / filename,
        Path.cwd() / "src" / "truba_gui" / "docs" / filename,
        Path.cwd() / "docs" / filename,
    ]
    for p in candidates:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except Exception:
            continue
    return ""
