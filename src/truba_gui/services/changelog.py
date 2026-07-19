from __future__ import annotations

from pathlib import Path


def changelog_path() -> Path:
    return Path(__file__).resolve().parent.parent / "docs" / "CHANGELOG.md"


def load_changelog_text() -> str:
    path = changelog_path()
    return path.read_text(encoding="utf-8", errors="replace")


def chronological_changelog(text: str) -> str:
    """Return changelog sections from newest to oldest."""
    lines = (text or "").splitlines()
    title_lines: list[str] = []
    sections: list[list[str]] = []
    current: list[str] | None = None

    for line in lines:
        if line.startswith("## "):
            if current is not None:
                sections.append(current)
            current = [line]
            continue
        if current is None:
            if line.strip():
                title_lines.append(line)
            continue
        current.append(line)

    if current is not None:
        sections.append(current)

    if not sections:
        return text.strip()

    output: list[str] = title_lines[:1] or ["# Changelog"]
    for section in sections:
        while section and not section[-1].strip():
            section.pop()
        output.extend(["", *section])
    return "\n".join(output).strip()
