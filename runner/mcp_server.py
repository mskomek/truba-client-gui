from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "agent_state.json"
ACTIVE_WAVE_PATH = ROOT / "ACTIVE_WAVE.md"
CURRENT_WAVE_PATH = ROOT / "CURRENT_WAVE.md"
TASKS_PATH = ROOT / "TASKS.md"
BUILD_REPORT_PATH = ROOT / "reports" / "BUILD_REPORT.md"
TEST_REPORT_PATH = ROOT / "reports" / "TEST_REPORT.md"
WAVE_REPORT_PATH = ROOT / "reports" / "WAVE_REPORT.md"


class MCPBridgeError(RuntimeError):
    """Raised when the bridge cannot parse the local workflow state."""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MCPBridgeError(f"Missing required file: {path}") from exc
    except OSError as exc:
        raise MCPBridgeError(f"Failed to read {path}: {exc}") from exc


def load_json(path: Path) -> dict[str, Any]:
    raw = read_text(path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MCPBridgeError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise MCPBridgeError(f"Expected an object in {path}, got {type(data).__name__}")
    return data


def extract_simple_metadata(path: Path, expected_keys: set[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in read_text(path).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key in expected_keys:
            metadata[key] = value
    missing = sorted(expected_keys - set(metadata))
    if missing:
        raise MCPBridgeError(f"{path} is missing required fields: {', '.join(missing)}")
    return metadata


def extract_heading_section(lines: list[str], heading: str) -> list[str]:
    section: list[str] = []
    capture = False
    for line in lines:
        if line.strip() == heading:
            capture = True
            continue
        if capture and line.startswith("### "):
            break
        if capture:
            section.append(line.rstrip("\n"))
    return section


def extract_bullets(lines: list[str]) -> list[str]:
    bullets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            bullet = stripped[2:].strip()
            if bullet.startswith("`") and bullet.endswith("`") and len(bullet) >= 2:
                bullet = bullet[1:-1].strip()
            bullets.append(bullet)
    return bullets


def extract_first_nonempty(lines: list[str], heading: str) -> str | None:
    section = extract_heading_section(lines, heading)
    for line in section:
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def parse_current_wave_doc() -> dict[str, Any]:
    lines = read_text(CURRENT_WAVE_PATH).splitlines()
    return {
        "wave_id": extract_first_nonempty(lines, "## Wave"),
        "status": extract_first_nonempty(lines, "## Status"),
        "source": extract_first_nonempty(lines, "## Source"),
        "current_task": extract_first_nonempty(lines, "## Current Task"),
        "rule": extract_first_nonempty(lines, "## Rule"),
    }


def parse_task_context(task_id: str) -> dict[str, Any]:
    lines = read_text(TASKS_PATH).splitlines()
    heading_pattern = re.compile(r"^##\s+(TASK-[0-9]+\.[0-9]+)\s+—\s+(.+)$")

    sections: dict[str, list[str]] = {}
    current_task_id: str | None = None
    current_lines: list[str] = []

    for line in lines:
        match = heading_pattern.match(line)
        if match:
            if current_task_id is not None:
                sections[current_task_id] = current_lines[:]
            current_task_id = match.group(1)
            current_lines = [line]
            continue
        if current_task_id is not None:
            current_lines.append(line)

    if current_task_id is not None:
        sections[current_task_id] = current_lines[:]

    if task_id not in sections:
        raise MCPBridgeError(f"Task {task_id} was not found in {TASKS_PATH}")

    section_lines = sections[task_id]
    title_match = heading_pattern.match(section_lines[0])
    title = title_match.group(2).strip() if title_match else task_id

    status = None
    for line in section_lines:
        if line.startswith("Status:"):
            status = line.split(":", 1)[1].strip()
            break

    return {
        "task_id": task_id,
        "title": title,
        "status": status,
        "summary": extract_first_nonempty(section_lines, "### Summary"),
        "goal": extract_first_nonempty(section_lines, "### Goal"),
        "dependencies": extract_bullets(extract_heading_section(section_lines, "### Dependencies")),
        "allowed_files": extract_bullets(extract_heading_section(section_lines, "### Allowed Files")),
        "forbidden_files": extract_bullets(extract_heading_section(section_lines, "### Forbidden Files")),
        "acceptance_criteria": extract_bullets(extract_heading_section(section_lines, "### Acceptance Criteria")),
        "required_check_commands": extract_bullets(extract_heading_section(section_lines, "### Required Check Commands")),
        "route": extract_first_nonempty(section_lines, "### Route"),
    }


def get_state() -> dict[str, Any]:
    state = load_json(STATE_PATH)
    return {
        "phase": state.get("phase"),
        "current_wave": state.get("current_wave"),
        "current_task": state.get("current_task"),
        "role": state.get("role"),
        "wave_status": state.get("wave_status"),
        "task_status": state.get("task_status"),
        "iteration": state.get("iteration"),
        "last_result": state.get("last_result"),
        "last_outcome": state.get("last_outcome"),
        "next_role": state.get("next_role"),
        "next_action": state.get("next_action"),
        "active_wave": extract_simple_metadata(
            ACTIVE_WAVE_PATH, {"status", "wave_id", "wave_file", "next_action"}
        ),
        "current_wave_doc": parse_current_wave_doc(),
    }


def get_active_task() -> dict[str, Any]:
    state = load_json(STATE_PATH)
    task_id = str(state["current_task"])
    return parse_task_context(task_id)


def get_current_wave() -> dict[str, Any]:
    state = load_json(STATE_PATH)
    active_wave = extract_simple_metadata(
        ACTIVE_WAVE_PATH, {"status", "wave_id", "wave_file", "next_action"}
    )
    return {
        "state_wave": state.get("current_wave"),
        "state_task": state.get("current_task"),
        "active_wave": active_wave,
        "current_wave_doc": parse_current_wave_doc(),
    }


def read_build_report() -> dict[str, Any]:
    content = read_text(BUILD_REPORT_PATH)
    return {
        "path": str(BUILD_REPORT_PATH),
        "exists": True,
        "line_count": len(content.splitlines()),
        "content": content,
    }


def read_test_report() -> dict[str, Any]:
    content = read_text(TEST_REPORT_PATH)
    return {
        "path": str(TEST_REPORT_PATH),
        "exists": True,
        "line_count": len(content.splitlines()),
        "content": content,
    }


def read_wave_report() -> dict[str, Any]:
    content = read_text(WAVE_REPORT_PATH)
    return {
        "path": str(WAVE_REPORT_PATH),
        "exists": True,
        "line_count": len(content.splitlines()),
        "content": content,
    }


def create_server(host: str = "127.0.0.1", port: int = 8765) -> FastMCP:
    server = FastMCP(
        name="truba-gui-readonly",
        instructions=(
            "Read-only MCP bridge for TRUBA GUI workflow state. "
            "The server exposes local file inspection tools only and does not write files "
            "or execute shell commands."
        ),
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )
    server.add_tool(get_state, description="Read the current workflow state file")
    server.add_tool(get_active_task, description="Read the active task contract")
    server.add_tool(get_current_wave, description="Read the current wave metadata")
    server.add_tool(read_build_report, description="Read the latest build report")
    server.add_tool(read_test_report, description="Read the latest test report")
    server.add_tool(read_wave_report, description="Read the latest wave report")
    return server


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only MCP bridge for TRUBA GUI workflow state")
    parser.add_argument("--host", default=os.environ.get("TRUBA_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TRUBA_MCP_PORT", "8765")))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    server = create_server(host=args.host, port=args.port)
    server.run("streamable-http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
