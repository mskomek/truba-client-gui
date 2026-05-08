from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shlex
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = ROOT / "agent_state.json"
DEFAULT_ACTIVE_WAVE_PATH = ROOT / "ACTIVE_WAVE.md"
DEFAULT_TASKS_PATH = ROOT / "TASKS.md"
DEFAULT_LOG_DIR = ROOT / "runner" / "logs"
DEFAULT_MASTER_CONTEXT_PATH = ROOT / "MASTER_CONTEXT_ACTIVE.md"
DEFAULT_RULES_PATH = ROOT / "rules.md"
DEFAULT_SESSION_RULES_PATH = ROOT / "SESSION_RULES.md"
DEFAULT_BUILDER_PROMPT_PATH = ROOT / "runner" / "prompts" / "builder.md"
DEFAULT_TESTER_PROMPT_PATH = ROOT / "runner" / "prompts" / "tester.md"
DEFAULT_BUILD_REPORT_PATH = ROOT / "reports" / "BUILD_REPORT.md"
DEFAULT_TEST_REPORT_PATH = ROOT / "reports" / "TEST_REPORT.md"
DEFAULT_OLLAMA_COMMAND = os.environ.get("TRUBA_OLLAMA_COMMAND", "ollama")
DEFAULT_BUILDER_MODEL = os.environ.get("TRUBA_BUILDER_MODEL", "qwen3.5:9b")
DEFAULT_TESTER_MODEL = os.environ.get("TRUBA_TESTER_MODEL", "qwen3.5:4b")
DEFAULT_OLLAMA_THINK = os.environ.get("TRUBA_OLLAMA_THINK", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

VALID_ROLES = {"ARCHITECT", "BUILDER", "TESTER"}
TERMINAL_RESULTS = {"PASS", "FAIL", "BLOCKED"}


class RunnerError(RuntimeError):
    """Raised when the workflow state is missing or invalid."""


@dataclass(frozen=True)
class ActiveWave:
    wave_id: str
    wave_file: Path
    status: str
    next_action: str | None


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    title: str
    status: str | None
    allowed_files: list[str]
    forbidden_files: list[str]
    acceptance_criteria: list[str]
    required_check_commands: list[str]
    route: str | None


@dataclass(frozen=True)
class BuilderRunResult:
    model: str
    command: list[str]
    prompt_hash: str
    prompt_length: int
    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool
    status: str
    duration_seconds: float
    started_at: str
    finished_at: str
    error: str | None = None


@dataclass(frozen=True)
class ScopeCheckResult:
    baseline_file_count: int
    current_file_count: int
    changed_files: list[str]
    violations: list[str]
    status: str


@dataclass(frozen=True)
class ValidationCommandResult:
    command_text: str
    command: list[str]
    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool
    status: str
    duration_seconds: float
    started_at: str
    finished_at: str
    error: str | None = None


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RunnerError(f"Missing required file: {path}") from exc
    except OSError as exc:
        raise RunnerError(f"Failed to read {path}: {exc}") from exc


def read_optional_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RunnerError(f"Failed to read {path}: {exc}") from exc


def load_json(path: Path) -> dict[str, Any]:
    raw = read_text(path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RunnerError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RunnerError(f"Expected an object in {path}, got {type(data).__name__}")
    return data


def normalize_token(value: Any) -> str:
    if not isinstance(value, str):
        raise RunnerError(f"Expected string value, got {type(value).__name__}")
    token = value.strip()
    if not token:
        raise RunnerError("String value cannot be empty")
    return token


def normalize_role(value: Any) -> str:
    role = normalize_token(value).upper()
    if role not in VALID_ROLES:
        raise RunnerError(
            f"Invalid role '{role}'. Expected one of: {', '.join(sorted(VALID_ROLES))}"
        )
    return role


def normalize_iteration(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunnerError("iteration must be an integer")
    if value < 0:
        raise RunnerError("iteration must not be negative")
    return value


def normalize_timeout(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunnerError("timeout must be an integer")
    if value <= 0:
        raise RunnerError("timeout must be positive")
    return value


def load_state(path: Path) -> dict[str, Any]:
    state = load_json(path)
    required = ["current_wave", "current_task", "role", "iteration", "last_result"]
    missing = [key for key in required if key not in state]
    if missing:
        raise RunnerError(f"agent_state.json is missing required keys: {', '.join(missing)}")

    current_wave = normalize_token(state["current_wave"])
    current_task = normalize_token(state["current_task"])
    role = normalize_role(state["role"])
    iteration = normalize_iteration(state["iteration"])
    last_result = normalize_token(state["last_result"])

    normalized = dict(state)
    normalized["current_wave"] = current_wave
    normalized["current_task"] = current_task
    normalized["role"] = role
    normalized["iteration"] = iteration
    normalized["last_result"] = last_result
    return normalized


def load_active_wave(path: Path) -> ActiveWave:
    raw = read_text(path)
    wave_id = None
    status = None
    wave_file = None
    next_action = None

    for line in raw.splitlines():
        if line.startswith("wave_id:"):
            wave_id = line.split(":", 1)[1].strip()
        elif line.startswith("status:"):
            status = line.split(":", 1)[1].strip()
        elif line.startswith("wave_file:"):
            wave_file = line.split(":", 1)[1].strip()
        elif line.startswith("next_action:"):
            next_action = line.split(":", 1)[1].strip()

    if not wave_id or not status or not wave_file:
        raise RunnerError(
            f"{path} is missing required fields. Expected wave_id, status, and wave_file."
        )

    resolved_wave_file = (ROOT / wave_file).resolve()
    if not resolved_wave_file.exists():
        raise RunnerError(f"Active wave file does not exist: {resolved_wave_file}")

    return ActiveWave(
        wave_id=wave_id,
        wave_file=resolved_wave_file,
        status=status.lower(),
        next_action=next_action,
    )


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


def parse_task_context(path: Path, task_id: str) -> TaskContext:
    lines = read_text(path).splitlines()
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
        raise RunnerError(f"Task {task_id} was not found in {path}")

    section_lines = sections[task_id]
    title_match = heading_pattern.match(section_lines[0])
    title = title_match.group(2).strip() if title_match else task_id

    status = None
    for line in section_lines:
        if line.startswith("Status:"):
            status = line.split(":", 1)[1].strip()
            break

    allowed = extract_bullets(extract_heading_section(section_lines, "### Allowed Files"))
    forbidden = extract_bullets(extract_heading_section(section_lines, "### Forbidden Files"))
    acceptance = extract_bullets(extract_heading_section(section_lines, "### Acceptance Criteria"))
    checks = extract_bullets(extract_heading_section(section_lines, "### Required Check Commands"))

    route = None
    route_section = extract_heading_section(section_lines, "### Route")
    if route_section:
        for line in route_section:
            stripped = line.strip()
            if stripped and not stripped.startswith("-"):
                route = stripped
                break

    return TaskContext(
        task_id=task_id,
        title=title,
        status=status,
        allowed_files=allowed,
        forbidden_files=forbidden,
        acceptance_criteria=acceptance,
        required_check_commands=checks,
        route=route,
    )


def extract_task_section_text(path: Path, task_id: str) -> str:
    lines = read_text(path).splitlines()
    heading_pattern = re.compile(r"^##\s+(TASK-[0-9]+\.[0-9]+)\s+—\s+(.+)$")

    current_task_id: str | None = None
    current_lines: list[str] = []

    for line in lines:
        match = heading_pattern.match(line)
        if match:
            if current_task_id == task_id and current_lines:
                break
            current_task_id = match.group(1)
            current_lines = [line]
            continue
        if current_task_id is not None:
            current_lines.append(line)

    if current_task_id != task_id or not current_lines:
        raise RunnerError(f"Task {task_id} was not found in {path}")

    return "\n".join(current_lines).strip()


def determine_next_role(role: str, last_result: str) -> str:
    result = last_result.upper()
    if role == "ARCHITECT":
        return "BUILDER"
    if role == "BUILDER":
        if result == "PASS":
            return "TESTER"
        if result in {"FAIL", "BLOCKED"}:
            return "ARCHITECT"
        return "BUILDER"
    if role == "TESTER":
        if result == "PASS":
            return "ARCHITECT"
        if result == "FAIL":
            return "BUILDER"
        if result == "BLOCKED":
            return "ARCHITECT"
        return "TESTER"
    raise RunnerError(f"Unsupported role: {role}")


def determine_next_action(role: str, last_result: str, task: TaskContext) -> str:
    result = last_result.upper()
    if role == "ARCHITECT":
        return f"prepare Builder handoff for {task.task_id}"
    if role == "BUILDER":
        if result == "PASS":
            return f"hand off {task.task_id} to Tester"
        if result == "FAIL":
            return f"fix {task.task_id} within Builder scope"
        if result == "BLOCKED":
            return f"escalate {task.task_id} back to Architect"
        return f"continue Builder work on {task.task_id}"
    if role == "TESTER":
        if result == "PASS":
            return f"return {task.task_id} to Architect for the next task"
        if result == "FAIL":
            return f"return {task.task_id} to Builder for correction"
        if result == "BLOCKED":
            return f"return {task.task_id} to Architect for replanning"
        return f"continue Tester review for {task.task_id}"
    raise RunnerError(f"Unsupported role: {role}")


def safe_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise RunnerError(f"Environment variable {name} must be an integer") from exc
    if value <= 0:
        raise RunnerError(f"Environment variable {name} must be positive")
    return value


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").strip()


def capture_repo_snapshot(root: Path) -> dict[str, str]:
    command = ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=False,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RunnerError("git is required to inspect repository file changes") from exc
    except subprocess.TimeoutExpired as exc:
        raise RunnerError("git file snapshot timed out") from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise RunnerError(f"git ls-files failed while capturing repository state: {stderr or 'unknown error'}")

    snapshot: dict[str, str] = {}
    for raw_path in (completed.stdout or b"").split(b"\0"):
        if not raw_path:
            continue
        rel_path = raw_path.decode("utf-8", "replace")
        normalized = normalize_repo_path(rel_path)
        abs_path = root / Path(normalized)
        if abs_path.is_file():
            snapshot[normalized] = hash_file(abs_path)
        else:
            snapshot[normalized] = "<missing>"
    return snapshot


def matches_scope_rule(path: str, rule: str) -> bool:
    normalized_path = normalize_repo_path(path)
    normalized_rule = normalize_repo_path(rule)
    return fnmatch.fnmatchcase(normalized_path, normalized_rule)


def evaluate_scope_changes(
    baseline_snapshot: dict[str, str],
    current_snapshot: dict[str, str],
    task: TaskContext,
) -> ScopeCheckResult:
    changed_files = sorted(
        path
        for path in set(baseline_snapshot) | set(current_snapshot)
        if baseline_snapshot.get(path) != current_snapshot.get(path)
    )
    violations: list[str] = []
    for path in changed_files:
        allowed = any(matches_scope_rule(path, rule) for rule in task.allowed_files)
        forbidden = any(matches_scope_rule(path, rule) for rule in task.forbidden_files)
        if forbidden:
            violations.append(f"forbidden:{path}")
        if not allowed:
            violations.append(f"outside_allowed:{path}")
    return ScopeCheckResult(
        baseline_file_count=len(baseline_snapshot),
        current_file_count=len(current_snapshot),
        changed_files=changed_files,
        violations=violations,
        status="PASS" if not violations else "BLOCKED",
    )


def truncate_text(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n...[truncated]..."


def format_repo_context_section(title: str, content: str) -> str:
    return f"## {title}\n\n{content.strip()}"


def parse_terminal_result(text: str) -> str:
    for line in reversed(text.splitlines()):
        stripped = line.strip().upper()
        if not stripped:
            continue
        if stripped in TERMINAL_RESULTS:
            return stripped
        if stripped.startswith("RESULT:"):
            candidate = stripped.split(":", 1)[1].strip()
            if candidate in TERMINAL_RESULTS:
                return candidate
    matches = re.findall(r"\b(PASS|FAIL|BLOCKED)\b", text.upper())
    if matches:
        return matches[-1]
    raise RunnerError("Tester output did not include a terminal PASS, FAIL, or BLOCKED token")


def split_validation_command(command_text: str) -> list[str]:
    normalized_text = normalize_token(command_text)
    try:
        parts = shlex.split(normalized_text, posix=os.name != "nt")
    except ValueError as exc:
        raise RunnerError(f"Invalid validation command '{normalized_text}': {exc}") from exc
    if not parts:
        raise RunnerError(f"Validation command '{normalized_text}' did not produce any argv tokens")
    return parts


def is_recursive_runner_command(command: list[str]) -> bool:
    normalized = [normalize_repo_path(token).lower() for token in command]
    if len(normalized) >= 3 and normalized[1] == "-m" and normalized[2] == "py_compile":
        return False
    if not normalized:
        return False
    if normalized[0].endswith("runner/runner.py") or normalized[0].endswith("runner.py"):
        return True
    if normalized[0] in {"python", "python.exe", "python3", "py", "py.exe"}:
        for token in normalized[1:]:
            if token.endswith("runner/runner.py") or token.endswith("/runner.py"):
                return True
    return False


def run_validation_command(
    command_text: str,
    cwd: Path,
    timeout_seconds: int,
) -> ValidationCommandResult:
    command = split_validation_command(command_text)
    started = datetime.now(timezone.utc)
    started_at = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_monotonic = time.monotonic()

    if is_recursive_runner_command(command):
        finished = datetime.now(timezone.utc)
        return ValidationCommandResult(
            command_text=command_text,
            command=command,
            stdout="",
            stderr="",
            returncode=None,
            timed_out=False,
            status="BLOCKED",
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=f"Validation command would recursively invoke runner: {command_text}",
        )

    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        finished = datetime.now(timezone.utc)
        return ValidationCommandResult(
            command_text=command_text,
            command=command,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
            timed_out=False,
            status="SUCCESS" if completed.returncode == 0 else "FAILED",
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except FileNotFoundError as exc:
        finished = datetime.now(timezone.utc)
        return ValidationCommandResult(
            command_text=command_text,
            command=command,
            stdout="",
            stderr="",
            returncode=None,
            timed_out=False,
            status="BLOCKED",
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=f"Validation command not found: {command[0]}",
        )
    except subprocess.TimeoutExpired as exc:
        finished = datetime.now(timezone.utc)
        stdout = exc.output if isinstance(exc.output, str) else (exc.output or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        return ValidationCommandResult(
            command_text=command_text,
            command=command,
            stdout=stdout,
            stderr=stderr,
            returncode=None,
            timed_out=True,
            status="TIMEOUT",
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=f"Validation command timed out after {timeout_seconds} seconds",
        )
    except OSError as exc:
        finished = datetime.now(timezone.utc)
        return ValidationCommandResult(
            command_text=command_text,
            command=command,
            stdout="",
            stderr="",
            returncode=None,
            timed_out=False,
            status="BLOCKED",
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=f"Validation command failed to start: {exc}",
        )


def run_validation_commands(
    commands: list[str],
    cwd: Path,
    timeout_seconds: int,
) -> list[ValidationCommandResult]:
    return [run_validation_command(command_text, cwd, timeout_seconds) for command_text in commands]


def summarize_validation_results(
    phase: str,
    model_status: str,
    results: list[ValidationCommandResult],
) -> tuple[str, str | None]:
    if model_status.upper() != "SUCCESS":
        return "SKIPPED", f"{phase} validation skipped because model status was {model_status}"
    if not results:
        return "BLOCKED", "No required check commands were defined for the active task"

    for result in results:
        if result.status == "SUCCESS":
            continue
        if result.status == "FAILED":
            if phase.upper() == "TESTER":
                return "FAIL", result.error or f"Validation command failed: {result.command_text}"
            return "BLOCKED", result.error or f"Validation command failed: {result.command_text}"
        return "BLOCKED", result.error or f"Validation command was blocked: {result.command_text}"
    return "PASS", None


def map_builder_terminal_result(result: BuilderRunResult) -> str:
    if result.status == "SUCCESS":
        return "PASS"
    if result.status in {"FAILED", "BLOCKED", "TIMEOUT"}:
        return "BLOCKED"
    raise RunnerError(f"Unsupported builder status: {result.status}")


def build_transition_state(
    state: dict[str, Any],
    task: TaskContext,
    completed_role: str,
    raw_outcome: str,
    terminal_result: str,
) -> dict[str, Any]:
    updated = dict(state)
    updated["iteration"] = normalize_iteration(state["iteration"]) + 1
    updated["role"] = completed_role
    updated["last_outcome"] = raw_outcome
    updated["last_result"] = terminal_result
    updated["next_role"] = determine_next_role(completed_role, terminal_result)
    updated["next_action"] = determine_next_action(completed_role, terminal_result, task)
    return updated


def compose_builder_prompt(
    builder_template: str,
    state: dict[str, Any],
    active_wave: ActiveWave,
    task: TaskContext,
    active_wave_path: Path,
    tasks_path: Path,
    master_context_path: Path,
    rules_path: Path,
    session_rules_path: Path,
) -> str:
    active_wave_text = read_text(active_wave.wave_file)
    active_wave_md = read_text(active_wave_path)
    task_section = extract_task_section_text(tasks_path, task.task_id)

    sections = [
        builder_template.strip(),
        "## Runtime Context",
        f"- Timestamp UTC: {utc_timestamp()}",
        f"- Current wave: {state['current_wave']}",
        f"- Current task: {state['current_task']}",
        f"- Current role: {state['role']}",
        f"- Iteration: {state['iteration']}",
        f"- Last result: {state['last_result']}",
        f"- Active wave file: {active_wave.wave_file}",
        f"- Active wave status: {active_wave.status}",
        "",
        "## Required Task Context",
        f"- Task ID: {task.task_id}",
        f"- Task title: {task.title}",
        f"- Task status: {task.status or 'unknown'}",
        f"- Route: {task.route or 'unknown'}",
        "### Allowed Files",
        *[f"- {entry}" for entry in task.allowed_files],
        "### Forbidden Files",
        *[f"- {entry}" for entry in task.forbidden_files],
        "### Acceptance Criteria",
        *[f"- {entry}" for entry in task.acceptance_criteria],
        "### Required Check Commands",
        *[f"- {entry}" for entry in task.required_check_commands],
        "",
        format_repo_context_section("MASTER_CONTEXT_ACTIVE.md", read_text(master_context_path)),
        format_repo_context_section("rules.md", read_text(rules_path)),
        format_repo_context_section("SESSION_RULES.md", read_text(session_rules_path)),
        format_repo_context_section("ACTIVE_WAVE.md", active_wave_md),
        format_repo_context_section(active_wave.wave_file.name, active_wave_text),
        format_repo_context_section("TASKS.md active task section", task_section),
    ]

    return "\n".join(section.rstrip() for section in sections if section.strip())


def compose_tester_prompt(
    tester_template: str,
    state: dict[str, Any],
    active_wave: ActiveWave,
    task: TaskContext,
    active_wave_path: Path,
    tasks_path: Path,
    master_context_path: Path,
    rules_path: Path,
    session_rules_path: Path,
    build_report_path: Path,
) -> str:
    active_wave_text = read_text(active_wave.wave_file)
    active_wave_md = read_text(active_wave_path)
    task_section = extract_task_section_text(tasks_path, task.task_id)
    build_report_text = read_optional_text(build_report_path)

    build_report_context = (
        truncate_text(build_report_text.strip(), 8000)
        if build_report_text is not None
        else f"MISSING: {build_report_path.relative_to(ROOT)} is not available yet."
    )

    sections = [
        tester_template.strip(),
        "## Verification Mode",
        "- The runner has already executed the active task's required validation commands and recorded their evidence in reports/BUILD_REPORT.md and agent_state.json.",
        "- Do not try to rerun the validation commands yourself; inspect the recorded evidence instead.",
        "- Base your decision on the active task contract, the wave state, and the recorded validation results.",
        "- Return PASS only when the active task criteria are satisfied and the recorded evidence supports that conclusion.",
        "## Runtime Context",
        f"- Timestamp UTC: {utc_timestamp()}",
        f"- Current wave: {state['current_wave']}",
        f"- Current task: {state['current_task']}",
        f"- Current role: {state['role']}",
        f"- Iteration: {state['iteration']}",
        f"- Last result: {state['last_result']}",
        f"- Active wave file: {active_wave.wave_file}",
        f"- Active wave status: {active_wave.status}",
        "",
        "## Required Task Context",
        f"- Task ID: {task.task_id}",
        f"- Task title: {task.title}",
        f"- Task status: {task.status or 'unknown'}",
        f"- Route: {task.route or 'unknown'}",
        "### Allowed Files",
        *[f"- {entry}" for entry in task.allowed_files],
        "### Forbidden Files",
        *[f"- {entry}" for entry in task.forbidden_files],
        "### Acceptance Criteria",
        *[f"- {entry}" for entry in task.acceptance_criteria],
        "### Required Check Commands",
        *[f"- {entry}" for entry in task.required_check_commands],
        "",
        format_repo_context_section("MASTER_CONTEXT_ACTIVE.md", read_text(master_context_path)),
        format_repo_context_section("rules.md", read_text(rules_path)),
        format_repo_context_section("SESSION_RULES.md", read_text(session_rules_path)),
        format_repo_context_section("ACTIVE_WAVE.md", active_wave_md),
        format_repo_context_section(active_wave.wave_file.name, active_wave_text),
        format_repo_context_section("TASKS.md active task section", task_section),
        format_repo_context_section("reports/BUILD_REPORT.md", build_report_context),
        "## Final Response Contract",
        "- Give a brief verification summary, then end with exactly one final line containing only PASS, FAIL, or BLOCKED.",
        "- Do not add any text after that final line.",
    ]

    return "\n".join(section.rstrip() for section in sections if section.strip())


def build_ollama_command(
    ollama_command: str,
    model: str,
    prompt_text: str,
    think_enabled: bool = DEFAULT_OLLAMA_THINK,
) -> list[str]:
    think_value = "true" if think_enabled else "false"
    return [resolve_ollama_command(ollama_command), "run", "--think=" + think_value, model, prompt_text]


def resolve_ollama_command(ollama_command: str) -> str:
    candidate = normalize_token(ollama_command)

    candidate_path = Path(candidate)
    if candidate_path.is_file():
        return str(candidate_path)

    resolved = shutil.which(candidate)
    if resolved:
        return resolved

    if os.name == "nt":
        executable_name = candidate if candidate.lower().endswith(".exe") else f"{candidate}.exe"
        for env_name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            root = os.environ.get(env_name)
            if not root:
                continue
            for subdir in (
                Path(root) / "Programs" / "Ollama" / executable_name,
                Path(root) / "Ollama" / executable_name,
            ):
                if subdir.is_file():
                    return str(subdir)

        escaped_name = candidate.replace("'", "''")
        ps_script = (
            "$cmd = Get-Command -Name '{name}' -ErrorAction SilentlyContinue; "
            "if ($cmd) {{ if ($cmd.Source) {{ $cmd.Source }} else {{ $cmd.Definition }} }}"
        ).format(name=escaped_name)
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except OSError:
            completed = None
        if completed is not None and completed.returncode == 0:
            for line in completed.stdout.splitlines():
                resolved_line = line.strip()
                if resolved_line and Path(resolved_line).exists():
                    return resolved_line

    return candidate


def validate_consistency(
    state: dict[str, Any],
    active_wave: ActiveWave,
    task: TaskContext,
) -> None:
    if state["current_wave"] != active_wave.wave_id:
        raise RunnerError(
            f"State current_wave '{state['current_wave']}' does not match ACTIVE_WAVE '{active_wave.wave_id}'"
        )
    if active_wave.status != "active":
        raise RunnerError(f"ACTIVE_WAVE status must be active, got '{active_wave.status}'")
    if state["current_task"] != task.task_id:
        raise RunnerError(
            f"State current_task '{state['current_task']}' does not match TASKS entry '{task.task_id}'"
        )
    if task.status is not None and state.get("task_status") is not None:
        if task.status.strip().upper() != normalize_token(state["task_status"]).upper():
            raise RunnerError(
                "State task_status does not match TASKS.md status for the active task"
            )
    if state.get("wave_status") is not None:
        if normalize_token(state["wave_status"]).lower() != active_wave.status:
            raise RunnerError("State wave_status does not match ACTIVE_WAVE status")


def run_builder_subprocess(
    ollama_command: str,
    model: str,
    prompt_text: str,
    timeout_seconds: int,
    think_enabled: bool = DEFAULT_OLLAMA_THINK,
) -> BuilderRunResult:
    command = build_ollama_command(ollama_command, model, prompt_text, think_enabled=think_enabled)
    started = datetime.now(timezone.utc)
    started_at = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_monotonic = time.monotonic()
    prompt_hash = hash_text(prompt_text)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        finished = datetime.now(timezone.utc)
        return BuilderRunResult(
            model=model,
            command=command,
            prompt_hash=prompt_hash,
            prompt_length=len(prompt_text),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
            timed_out=False,
            status="SUCCESS" if completed.returncode == 0 else "FAILED",
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except FileNotFoundError as exc:
        finished = datetime.now(timezone.utc)
        return BuilderRunResult(
            model=model,
            command=command,
            prompt_hash=prompt_hash,
            prompt_length=len(prompt_text),
            stdout="",
            stderr="",
            returncode=None,
            timed_out=False,
            status="BLOCKED",
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=f"Builder command not found: {ollama_command}",
        )
    except subprocess.TimeoutExpired as exc:
        finished = datetime.now(timezone.utc)
        stdout = exc.output if isinstance(exc.output, str) else (exc.output or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        return BuilderRunResult(
            model=model,
            command=command,
            prompt_hash=prompt_hash,
            prompt_length=len(prompt_text),
            stdout=stdout,
            stderr=stderr,
            returncode=None,
            timed_out=True,
            status="TIMEOUT",
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=f"Builder timed out after {timeout_seconds} seconds",
        )


def run_tester_subprocess(
    ollama_command: str,
    model: str,
    prompt_text: str,
    timeout_seconds: int,
    think_enabled: bool = DEFAULT_OLLAMA_THINK,
) -> BuilderRunResult:
    command = build_ollama_command(ollama_command, model, prompt_text, think_enabled=think_enabled)
    started = datetime.now(timezone.utc)
    started_at = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_monotonic = time.monotonic()
    prompt_hash = hash_text(prompt_text)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        finished = datetime.now(timezone.utc)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        parsed_result: str | None = None
        parse_error: str | None = None
        try:
            parsed_result = parse_terminal_result(stdout)
        except RunnerError as exc:
            parse_error = str(exc)
        if parse_error is not None:
            status = "BLOCKED"
            error = parse_error
        else:
            status = parsed_result or "BLOCKED"
            error = None
            if completed.returncode != 0:
                error = (
                    f"Tester process exited with return code {completed.returncode} "
                    f"but emitted terminal result {status}"
                )
        if completed.returncode != 0 and not stdout.strip():
            status = "BLOCKED"
            error = f"Tester process exited with return code {completed.returncode} before emitting a terminal result"
        return BuilderRunResult(
            model=model,
            command=command,
            prompt_hash=prompt_hash,
            prompt_length=len(prompt_text),
            stdout=stdout,
            stderr=stderr,
            returncode=completed.returncode,
            timed_out=False,
            status=status,
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=error,
        )
    except FileNotFoundError as exc:
        finished = datetime.now(timezone.utc)
        return BuilderRunResult(
            model=model,
            command=command,
            prompt_hash=prompt_hash,
            prompt_length=len(prompt_text),
            stdout="",
            stderr="",
            returncode=None,
            timed_out=False,
            status="BLOCKED",
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=f"Tester command not found: {ollama_command}",
        )
    except subprocess.TimeoutExpired as exc:
        finished = datetime.now(timezone.utc)
        stdout = exc.output if isinstance(exc.output, str) else (exc.output or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        return BuilderRunResult(
            model=model,
            command=command,
            prompt_hash=prompt_hash,
            prompt_length=len(prompt_text),
            stdout=stdout,
            stderr=stderr,
            returncode=None,
            timed_out=True,
            status="BLOCKED",
            duration_seconds=max(0.0, time.monotonic() - start_monotonic),
            started_at=started_at,
            finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=f"Tester timed out after {timeout_seconds} seconds",
        )


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temp_path.replace(path)


def update_state_with_builder_result(
    state_path: Path,
    state: dict[str, Any],
    task: TaskContext,
    result: BuilderRunResult,
    scope_check: ScopeCheckResult,
    validation_results: list[ValidationCommandResult],
    validation_status: str,
    validation_error: str | None,
    validation_timeout_seconds: int,
    terminal_result: str,
    raw_outcome: str,
) -> dict[str, Any]:
    updated = build_transition_state(state, task, "BUILDER", raw_outcome, terminal_result)
    updated["builder_run"] = {
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "model": result.model,
        "command": result.command,
        "prompt_hash": result.prompt_hash,
        "prompt_length": result.prompt_length,
        "process_status": result.status,
        "status": result.status,
        "terminal_result": terminal_result,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "report_path": str(DEFAULT_BUILD_REPORT_PATH.relative_to(ROOT)),
        "next_role": updated["next_role"],
        "next_action": updated["next_action"],
        "scope_check": {
            "baseline_file_count": scope_check.baseline_file_count,
            "current_file_count": scope_check.current_file_count,
            "changed_files": scope_check.changed_files,
            "violations": scope_check.violations,
            "status": scope_check.status,
        },
        "validation": {
            "status": validation_status,
            "error": validation_error,
            "timeout_seconds": validation_timeout_seconds,
            "command_count": len(validation_results),
            "results": [validation_result_to_dict(entry) for entry in validation_results],
        },
    }
    if result.error is not None:
        updated["builder_run"]["error"] = result.error
    if scope_check.violations:
        updated["builder_run"]["error"] = (
            "Builder file-scope violation: " + "; ".join(scope_check.violations)
        )
    if validation_error is not None:
        updated["builder_run"]["validation"]["error"] = validation_error
    write_json_atomic(state_path, updated)
    return updated


def update_state_with_tester_result(
    state_path: Path,
    state: dict[str, Any],
    task: TaskContext,
    result: BuilderRunResult,
    validation_results: list[ValidationCommandResult],
    validation_status: str,
    validation_error: str | None,
    validation_timeout_seconds: int,
) -> dict[str, Any]:
    updated = build_transition_state(state, task, "TESTER", result.status, result.status)
    updated["tester_run"] = {
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "model": result.model,
        "command": result.command,
        "prompt_hash": result.prompt_hash,
        "prompt_length": result.prompt_length,
        "status": result.status,
        "terminal_result": result.status,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "report_path": str(DEFAULT_TEST_REPORT_PATH.relative_to(ROOT)),
        "next_role": updated["next_role"],
        "next_action": updated["next_action"],
        "validation": {
            "status": validation_status,
            "error": validation_error,
            "timeout_seconds": validation_timeout_seconds,
            "command_count": len(validation_results),
            "results": [validation_result_to_dict(entry) for entry in validation_results],
        },
    }
    if result.error is not None:
        updated["tester_run"]["error"] = result.error
    if validation_error is not None:
        updated["tester_run"]["validation"]["error"] = validation_error
    write_json_atomic(state_path, updated)
    return updated


def safe_code_block(text: str) -> str:
    return text.replace("```", "\\`\\`\\`")


def validation_result_to_dict(result: ValidationCommandResult) -> dict[str, Any]:
    data: dict[str, Any] = {
        "command_text": result.command_text,
        "command": result.command,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "status": result.status,
        "duration_seconds": result.duration_seconds,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
    }
    if result.error is not None:
        data["error"] = result.error
    return data


def append_validation_report_section(
    report_lines: list[str],
    validation_results: list[ValidationCommandResult],
    validation_status: str,
    validation_error: str | None,
    validation_timeout_seconds: int,
) -> None:
    report_lines.extend(
        [
            "",
            "## Validation Commands",
            "",
            f"- Validation status: {validation_status}",
            f"- Validation timeout seconds: {validation_timeout_seconds}",
            f"- Validation command count: {len(validation_results)}",
        ]
    )
    if validation_error is not None:
        report_lines.extend(["- Validation error:", f"  - {validation_error}"])
    if not validation_results:
        report_lines.extend(["- Validation results: none"])
        return

    report_lines.append("- Validation results:")
    for index, validation_result in enumerate(validation_results, start=1):
        report_lines.extend(
            [
                f"  - Command {index}: {validation_result.command_text}",
                f"    - Command argv: {json.dumps(validation_result.command, ensure_ascii=False)}",
                f"    - Status: {validation_result.status}",
                f"    - Return code: {validation_result.returncode if validation_result.returncode is not None else 'n/a'}",
                f"    - Timed out: {'yes' if validation_result.timed_out else 'no'}",
                f"    - Started at: {validation_result.started_at}",
                f"    - Finished at: {validation_result.finished_at}",
                f"    - Duration seconds: {validation_result.duration_seconds:.2f}",
                "    - Stdout:",
                "~~~text",
                safe_code_block(truncate_text(validation_result.stdout)),
                "~~~",
                "    - Stderr:",
                "~~~text",
                safe_code_block(truncate_text(validation_result.stderr)),
                "~~~",
            ]
        )
        if validation_result.error is not None:
            report_lines.extend([f"    - Error: {validation_result.error}"])


def write_build_report(
    report_path: Path,
    state: dict[str, Any],
    task: TaskContext,
    active_wave: ActiveWave,
    result: BuilderRunResult,
    scope_check: ScopeCheckResult,
    validation_results: list[ValidationCommandResult],
    validation_status: str,
    validation_error: str | None,
    validation_timeout_seconds: int,
    terminal_result: str,
    prompt_sources: list[str],
) -> None:
    report_lines = [
        "# BUILD_REPORT.md",
        "",
        "ROLE: BUILDER",
        f"TASK_ID: {task.task_id}",
        f"WAVE_ID: {state['current_wave']}",
        f"STATUS: {terminal_result}",
        "",
        "## Command",
        "",
        f"- Ollama command: {json.dumps(result.command, ensure_ascii=False)}",
        f"- Model: {result.model}",
        f"- Process status: {result.status}",
        f"- Timed out: {'yes' if result.timed_out else 'no'}",
        f"- Return code: {result.returncode if result.returncode is not None else 'n/a'}",
        f"- Started at: {result.started_at}",
        f"- Finished at: {result.finished_at}",
        f"- Duration seconds: {result.duration_seconds:.2f}",
        f"- Prompt hash: `{result.prompt_hash}`",
        f"- Prompt length: {result.prompt_length}",
        "",
        "## Prompt Sources",
        "",
        *[f"- {source}" for source in prompt_sources],
        "",
        "## Builder Stdout",
        "",
        "~~~text",
        safe_code_block(truncate_text(result.stdout)),
        "~~~",
        "",
        "## Builder Stderr",
        "",
        "~~~text",
        safe_code_block(truncate_text(result.stderr)),
        "~~~",
        "",
        "## Notes",
        "",
        f"- Active wave: {active_wave.wave_id}",
        f"- Active wave file: {active_wave.wave_file}",
        "- Report captured from deterministic runner execution.",
        "",
        "## Routing",
        "",
        f"- Completed role: {state.get('role', 'unknown')}",
        f"- Last outcome: {state.get('last_outcome', 'unknown')}",
        f"- Last result: {state.get('last_result', 'unknown')}",
        f"- Next role: {state.get('next_role', 'unknown')}",
        f"- Next action: {state.get('next_action', 'unknown')}",
    ]
    report_lines.extend(
        [
            "",
            "## Scope Check",
            "",
            f"- Baseline files: {scope_check.baseline_file_count}",
            f"- Current files: {scope_check.current_file_count}",
            f"- Changed files: {len(scope_check.changed_files)}",
            f"- Scope status: {scope_check.status}",
            "- Changed file list:",
            *[f"  - {path}" for path in scope_check.changed_files],
            "- Violations:",
            *[
                f"  - {violation}"
                for violation in (scope_check.violations or ["none"])
            ],
        ]
    )
    append_validation_report_section(
        report_lines,
        validation_results=validation_results,
        validation_status=validation_status,
        validation_error=validation_error,
        validation_timeout_seconds=validation_timeout_seconds,
    )
    error_text = result.error
    if error_text is None and scope_check.violations:
        error_text = "Builder file-scope violation: " + "; ".join(scope_check.violations)
    if error_text is None and validation_error is not None:
        error_text = validation_error
    if error_text is not None:
        report_lines.extend(["", "## Error", "", error_text])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8", newline="\n")


def write_test_report(
    report_path: Path,
    state: dict[str, Any],
    task: TaskContext,
    active_wave: ActiveWave,
    result: BuilderRunResult,
    validation_results: list[ValidationCommandResult],
    validation_status: str,
    validation_error: str | None,
    validation_timeout_seconds: int,
    prompt_sources: list[str],
) -> None:
    report_lines = [
        "# TEST_REPORT.md",
        "",
        "ROLE: TESTER",
        f"TASK_ID: {task.task_id}",
        f"WAVE_ID: {state['current_wave']}",
        f"RESULT: {result.status}",
        "",
        "## Command",
        "",
        f"- Ollama command: {json.dumps(result.command, ensure_ascii=False)}",
        f"- Model: {result.model}",
        f"- Timed out: {'yes' if result.timed_out else 'no'}",
        f"- Return code: {result.returncode if result.returncode is not None else 'n/a'}",
        f"- Started at: {result.started_at}",
        f"- Finished at: {result.finished_at}",
        f"- Duration seconds: {result.duration_seconds:.2f}",
        f"- Prompt hash: `{result.prompt_hash}`",
        f"- Prompt length: {result.prompt_length}",
        "",
        "## Prompt Sources",
        "",
        *[f"- {source}" for source in prompt_sources],
        "",
        "## Tester Stdout",
        "",
        "~~~text",
        safe_code_block(truncate_text(result.stdout)),
        "~~~",
        "",
        "## Tester Stderr",
        "",
        "~~~text",
        safe_code_block(truncate_text(result.stderr)),
        "~~~",
        "",
        "## Notes",
        "",
        f"- Active wave: {active_wave.wave_id}",
        f"- Active wave file: {active_wave.wave_file}",
        "- Report captured from deterministic runner execution.",
        "",
        "## Routing",
        "",
        f"- Completed role: {state.get('role', 'unknown')}",
        f"- Last outcome: {state.get('last_outcome', 'unknown')}",
        f"- Last result: {state.get('last_result', 'unknown')}",
        f"- Next role: {state.get('next_role', 'unknown')}",
        f"- Next action: {state.get('next_action', 'unknown')}",
    ]
    append_validation_report_section(
        report_lines,
        validation_results=validation_results,
        validation_status=validation_status,
        validation_error=validation_error,
        validation_timeout_seconds=validation_timeout_seconds,
    )
    if result.error is not None:
        report_lines.extend(["", "## Error", "", result.error])
    elif validation_error is not None:
        report_lines.extend(["", "## Error", "", validation_error])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8", newline="\n")


def execute_builder_attempt(
    state_path: Path,
    state: dict[str, Any],
    active_wave_path: Path,
    active_wave: ActiveWave,
    task: TaskContext,
    tasks_path: Path,
    report_path: Path,
    master_context_path: Path,
    rules_path: Path,
    session_rules_path: Path,
    builder_prompt_path: Path,
    ollama_command: str,
    builder_model: str,
    timeout_seconds: int,
    validation_timeout_seconds: int,
    think_enabled: bool,
) -> tuple[BuilderRunResult, dict[str, Any]]:
    builder_template = read_text(builder_prompt_path)
    baseline_snapshot = capture_repo_snapshot(ROOT)
    prompt_text = compose_builder_prompt(
        builder_template=builder_template,
        state=state,
        active_wave=active_wave,
        task=task,
        active_wave_path=active_wave_path,
        tasks_path=tasks_path,
        master_context_path=master_context_path,
        rules_path=rules_path,
        session_rules_path=session_rules_path,
    )
    result = run_builder_subprocess(
        ollama_command=ollama_command,
        model=builder_model,
        prompt_text=prompt_text,
        timeout_seconds=timeout_seconds,
        think_enabled=think_enabled,
    )
    current_snapshot = capture_repo_snapshot(ROOT)
    scope_check = evaluate_scope_changes(baseline_snapshot, current_snapshot, task)
    terminal_result = map_builder_terminal_result(result)
    raw_outcome = result.status
    validation_results: list[ValidationCommandResult] = []
    validation_status = "SKIPPED"
    validation_error: str | None = None
    if result.status == "SUCCESS":
        validation_results = run_validation_commands(
            task.required_check_commands,
            cwd=ROOT,
            timeout_seconds=validation_timeout_seconds,
        )
        validation_status, validation_error = summarize_validation_results(
            "BUILDER",
            result.status,
            validation_results,
        )
        if validation_status != "PASS":
            terminal_result = validation_status
            raw_outcome = f"VALIDATION_{validation_status}"
        else:
            raw_outcome = "VALIDATION_PASS"
    if scope_check.violations:
        terminal_result = "BLOCKED"
        raw_outcome = "SCOPE_VIOLATION"
    prompt_sources = [
        str(builder_prompt_path.relative_to(ROOT)),
        str(DEFAULT_MASTER_CONTEXT_PATH.relative_to(ROOT)),
        str(DEFAULT_RULES_PATH.relative_to(ROOT)),
        str(DEFAULT_SESSION_RULES_PATH.relative_to(ROOT)),
        str(active_wave_path.relative_to(ROOT)),
        str(active_wave.wave_file.relative_to(ROOT)),
        str(tasks_path.relative_to(ROOT)),
    ]
    updated_state = update_state_with_builder_result(
        state_path=state_path,
        state=state,
        task=task,
        result=result,
        scope_check=scope_check,
        validation_results=validation_results,
        validation_status=validation_status,
        validation_error=validation_error,
        validation_timeout_seconds=validation_timeout_seconds,
        terminal_result=terminal_result,
        raw_outcome=raw_outcome,
    )
    write_build_report(
        report_path=report_path,
        state=updated_state,
        task=task,
        active_wave=active_wave,
        result=result,
        scope_check=scope_check,
        validation_results=validation_results,
        validation_status=validation_status,
        validation_error=validation_error,
        validation_timeout_seconds=validation_timeout_seconds,
        terminal_result=terminal_result,
        prompt_sources=prompt_sources,
    )
    return result, updated_state


def execute_tester_attempt(
    state_path: Path,
    state: dict[str, Any],
    active_wave_path: Path,
    active_wave: ActiveWave,
    task: TaskContext,
    tasks_path: Path,
    report_path: Path,
    master_context_path: Path,
    rules_path: Path,
    session_rules_path: Path,
    tester_prompt_path: Path,
    build_report_path: Path,
    ollama_command: str,
    tester_model: str,
    timeout_seconds: int,
    validation_timeout_seconds: int,
    think_enabled: bool,
) -> tuple[BuilderRunResult, dict[str, Any]]:
    tester_template = read_text(tester_prompt_path)
    prompt_text = compose_tester_prompt(
        tester_template=tester_template,
        state=state,
        active_wave=active_wave,
        task=task,
        active_wave_path=active_wave_path,
        tasks_path=tasks_path,
        master_context_path=master_context_path,
        rules_path=rules_path,
        session_rules_path=session_rules_path,
        build_report_path=build_report_path,
    )
    result = run_tester_subprocess(
        ollama_command=ollama_command,
        model=tester_model,
        prompt_text=prompt_text,
        timeout_seconds=timeout_seconds,
        think_enabled=think_enabled,
    )
    validation_results: list[ValidationCommandResult] = []
    validation_status = "SKIPPED"
    validation_error: str | None = None
    validation_results = run_validation_commands(
        task.required_check_commands,
        cwd=ROOT,
        timeout_seconds=validation_timeout_seconds,
    )
    validation_status, validation_error = summarize_validation_results(
        "TESTER",
        "SUCCESS",
        validation_results,
    )
    if result.status == "PASS" and validation_status != "PASS":
        result = BuilderRunResult(
            model=result.model,
            command=result.command,
            prompt_hash=result.prompt_hash,
            prompt_length=result.prompt_length,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            timed_out=result.timed_out,
            status=validation_status,
            duration_seconds=result.duration_seconds,
            started_at=result.started_at,
            finished_at=result.finished_at,
            error=validation_error,
        )
    prompt_sources = [
        str(tester_prompt_path.relative_to(ROOT)),
        str(build_report_path.relative_to(ROOT)),
        str(DEFAULT_MASTER_CONTEXT_PATH.relative_to(ROOT)),
        str(DEFAULT_RULES_PATH.relative_to(ROOT)),
        str(DEFAULT_SESSION_RULES_PATH.relative_to(ROOT)),
        str(active_wave_path.relative_to(ROOT)),
        str(active_wave.wave_file.relative_to(ROOT)),
        str(tasks_path.relative_to(ROOT)),
    ]
    updated_state = update_state_with_tester_result(
        state_path=state_path,
        state=state,
        task=task,
        result=result,
        validation_results=validation_results,
        validation_status=validation_status,
        validation_error=validation_error,
        validation_timeout_seconds=validation_timeout_seconds,
    )
    write_test_report(
        report_path=report_path,
        state=updated_state,
        task=task,
        active_wave=active_wave,
        result=result,
        validation_results=validation_results,
        validation_status=validation_status,
        validation_error=validation_error,
        validation_timeout_seconds=validation_timeout_seconds,
        prompt_sources=prompt_sources,
    )
    return result, updated_state


def write_log(log_dir: Path, message_lines: list[str]) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"runner_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{os.getpid()}.log"
    with log_path.open("w", encoding="utf-8", newline="\n") as handle:
        for line in message_lines:
            handle.write(line.rstrip("\n") + "\n")
    return log_path


def run(
    state_path: Path,
    active_wave_path: Path,
    tasks_path: Path,
    log_dir: Path,
    master_context_path: Path,
    rules_path: Path,
    session_rules_path: Path,
    builder_prompt_path: Path,
    tester_prompt_path: Path,
    report_path: Path,
    test_report_path: Path,
    ollama_command: str,
    builder_model: str,
    tester_model: str,
    builder_timeout_seconds: int,
    tester_timeout_seconds: int,
    validation_timeout_seconds: int,
    think_enabled: bool,
) -> int:
    log_lines = [f"{utc_timestamp()} | runner_start | state={state_path}"]
    try:
        state = load_state(state_path)
        active_wave = load_active_wave(active_wave_path)
        task = parse_task_context(tasks_path, state["current_task"])
        validate_consistency(state, active_wave, task)

        next_role = determine_next_role(state["role"], state["last_result"])
        next_action = determine_next_action(state["role"], state["last_result"], task)

        log_lines.extend(
            [
                f"{utc_timestamp()} | state_loaded | wave={state['current_wave']} task={state['current_task']} role={state['role']} iteration={state['iteration']} last_result={state['last_result']}",
                f"{utc_timestamp()} | active_wave | wave_id={active_wave.wave_id} status={active_wave.status} file={active_wave.wave_file}",
                f"{utc_timestamp()} | task_context | title={task.title} status={task.status or 'unknown'} route={task.route or 'unknown'}",
                f"{utc_timestamp()} | decision | next_role={next_role} next_action={next_action}",
            ]
        )

        builder_result: BuilderRunResult | None = None
        tester_result: BuilderRunResult | None = None
        if next_role == "BUILDER":
            log_lines.append(
                f"{utc_timestamp()} | builder_start | model={builder_model} timeout_seconds={builder_timeout_seconds} command={ollama_command}"
            )
            builder_result, state = execute_builder_attempt(
                state_path=state_path,
                state=state,
                active_wave_path=active_wave_path,
                active_wave=active_wave,
                task=task,
                tasks_path=tasks_path,
                report_path=report_path,
                master_context_path=master_context_path,
                rules_path=rules_path,
                session_rules_path=session_rules_path,
                builder_prompt_path=builder_prompt_path,
                ollama_command=ollama_command,
                builder_model=builder_model,
                timeout_seconds=builder_timeout_seconds,
                validation_timeout_seconds=validation_timeout_seconds,
                think_enabled=think_enabled,
            )
            log_lines.extend(
                [
                    f"{utc_timestamp()} | builder_result | status={builder_result.status} returncode={builder_result.returncode if builder_result.returncode is not None else 'n/a'} timed_out={builder_result.timed_out}",
                    f"{utc_timestamp()} | builder_validation | status={state.get('builder_run', {}).get('validation', {}).get('status', 'unknown')} error={state.get('builder_run', {}).get('validation', {}).get('error', 'none')}",
                    f"{utc_timestamp()} | builder_report | path={report_path}",
                    f"{utc_timestamp()} | state_transition | role={state.get('role')} last_outcome={state.get('last_outcome')} last_result={state.get('last_result')} next_role={state.get('next_role')} next_action={state.get('next_action')}",
                ]
            )
        elif next_role == "TESTER":
            log_lines.append(
                f"{utc_timestamp()} | tester_start | model={tester_model} timeout_seconds={tester_timeout_seconds} command={ollama_command}"
            )
            tester_result, state = execute_tester_attempt(
                state_path=state_path,
                state=state,
                active_wave_path=active_wave_path,
                active_wave=active_wave,
                task=task,
                tasks_path=tasks_path,
                report_path=test_report_path,
                master_context_path=master_context_path,
                rules_path=rules_path,
                session_rules_path=session_rules_path,
                tester_prompt_path=tester_prompt_path,
                build_report_path=report_path,
                ollama_command=ollama_command,
                tester_model=tester_model,
                timeout_seconds=tester_timeout_seconds,
                validation_timeout_seconds=validation_timeout_seconds,
                think_enabled=think_enabled,
            )
            log_lines.extend(
                [
                    f"{utc_timestamp()} | tester_result | status={tester_result.status} returncode={tester_result.returncode if tester_result.returncode is not None else 'n/a'} timed_out={tester_result.timed_out}",
                    f"{utc_timestamp()} | tester_validation | status={state.get('tester_run', {}).get('validation', {}).get('status', 'unknown')} error={state.get('tester_run', {}).get('validation', {}).get('error', 'none')}",
                    f"{utc_timestamp()} | tester_report | path={test_report_path}",
                    f"{utc_timestamp()} | state_transition | role={state.get('role')} last_outcome={state.get('last_outcome')} last_result={state.get('last_result')} next_role={state.get('next_role')} next_action={state.get('next_action')}",
                ]
            )

        log_path = write_log(log_dir, log_lines)

        print("RUNNER OK")
        print(f"current_wave={state['current_wave']}")
        print(f"current_task={state['current_task']}")
        print(f"current_role={state['role']}")
        print(f"last_outcome={state.get('last_outcome', 'unknown')}")
        print(f"last_result={state.get('last_result', 'unknown')}")
        print(f"next_role={state.get('next_role', next_role)}")
        print(f"next_action={state.get('next_action', next_action)}")
        if builder_result is not None:
            print(f"builder_status={builder_result.status}")
            print(f"builder_returncode={builder_result.returncode if builder_result.returncode is not None else 'n/a'}")
            print(f"builder_timed_out={'yes' if builder_result.timed_out else 'no'}")
            print(f"builder_report={report_path}")
        if tester_result is not None:
            print(f"tester_status={tester_result.status}")
            print(f"tester_returncode={tester_result.returncode if tester_result.returncode is not None else 'n/a'}")
            print(f"tester_timed_out={'yes' if tester_result.timed_out else 'no'}")
            print(f"tester_report={test_report_path}")
        print(f"log_file={log_path}")
        return 0
    except RunnerError as exc:
        log_lines.append(f"{utc_timestamp()} | error | {exc}")
        log_path = write_log(log_dir, log_lines)
        print(f"RUNNER ERROR: {exc}", file=sys.stderr)
        print(f"log_file={log_path}", file=sys.stderr)
        return 2


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic TRUBA workflow runner")
    parser.add_argument("--state", dest="state_path", default=DEFAULT_STATE_PATH)
    parser.add_argument("--active-wave", dest="active_wave_path", default=DEFAULT_ACTIVE_WAVE_PATH)
    parser.add_argument("--tasks", dest="tasks_path", default=DEFAULT_TASKS_PATH)
    parser.add_argument("--log-dir", dest="log_dir", default=DEFAULT_LOG_DIR)
    parser.add_argument("--master-context", dest="master_context_path", default=DEFAULT_MASTER_CONTEXT_PATH)
    parser.add_argument("--rules", dest="rules_path", default=DEFAULT_RULES_PATH)
    parser.add_argument("--session-rules", dest="session_rules_path", default=DEFAULT_SESSION_RULES_PATH)
    parser.add_argument("--builder-prompt", dest="builder_prompt_path", default=DEFAULT_BUILDER_PROMPT_PATH)
    parser.add_argument("--tester-prompt", dest="tester_prompt_path", default=DEFAULT_TESTER_PROMPT_PATH)
    parser.add_argument("--build-report", dest="report_path", default=DEFAULT_BUILD_REPORT_PATH)
    parser.add_argument("--test-report", dest="test_report_path", default=DEFAULT_TEST_REPORT_PATH)
    parser.add_argument("--ollama-command", dest="ollama_command", default=DEFAULT_OLLAMA_COMMAND)
    parser.add_argument("--builder-model", dest="builder_model", default=DEFAULT_BUILDER_MODEL)
    parser.add_argument("--tester-model", dest="tester_model", default=DEFAULT_TESTER_MODEL)
    think_group = parser.add_mutually_exclusive_group()
    think_group.add_argument(
        "--think",
        dest="think_enabled",
        action="store_true",
        default=DEFAULT_OLLAMA_THINK,
        help="Enable Ollama thinking mode.",
    )
    think_group.add_argument(
        "--no-think",
        dest="think_enabled",
        action="store_false",
        help="Disable Ollama thinking mode.",
    )
    parser.add_argument(
        "--validation-timeout",
        dest="validation_timeout_seconds",
        type=lambda value: normalize_timeout(int(value)),
        default=safe_env_int("TRUBA_VALIDATION_TIMEOUT_SECONDS", 300),
    )
    parser.add_argument(
        "--builder-timeout",
        dest="builder_timeout_seconds",
        type=lambda value: normalize_timeout(int(value)),
        default=safe_env_int("TRUBA_BUILDER_TIMEOUT_SECONDS", 180),
    )
    parser.add_argument(
        "--tester-timeout",
        dest="tester_timeout_seconds",
        type=lambda value: normalize_timeout(int(value)),
        default=safe_env_int("TRUBA_TESTER_TIMEOUT_SECONDS", 180),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return run(
        Path(args.state_path),
        Path(args.active_wave_path),
        Path(args.tasks_path),
        Path(args.log_dir),
        Path(args.master_context_path),
        Path(args.rules_path),
        Path(args.session_rules_path),
        Path(args.builder_prompt_path),
        Path(args.tester_prompt_path),
        Path(args.report_path),
        Path(args.test_report_path),
        args.ollama_command,
        args.builder_model,
        args.tester_model,
        args.builder_timeout_seconds,
        args.tester_timeout_seconds,
        args.validation_timeout_seconds,
        args.think_enabled,
    )


if __name__ == "__main__":
    raise SystemExit(main())
