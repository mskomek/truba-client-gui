"""Tool-capable local Ollama agent loop with repository scope enforcement."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_OLLAMA_CHAT_URL = os.environ.get(
    "TRUBA_OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat"
)
MAX_TOOL_OUTPUT = 20_000
FORBIDDEN_COMMAND_PATTERNS = (
    r"\bremove-item\b",
    r"\bdel(?:ete)?\b",
    r"\brm\b",
    r"\bmove-item\b",
    r"\bset-content\b",
    r"\badd-content\b",
    r"\bout-file\b",
    r"\bgit\s+(?:reset|checkout|clean|restore|commit|push)\b",
    r">",
)
ALLOWED_COMMAND_PREFIXES = (
    "python ",
    "python.exe ",
    "py ",
    "git diff",
    "git status",
    "git ls-files",
    "rg ",
    "get-content ",
    "get-childitem ",
    "get-location",
)


class LocalAgentError(RuntimeError):
    pass


def snapshot_allowed_files(
    workspace: Path, allowed_files: list[str]
) -> dict[Path, bytes | None]:
    """Capture write targets so a failed implementer run can be rolled back."""
    root = workspace.resolve()
    snapshots: dict[Path, bytes | None] = {}
    for entry in allowed_files:
        target = (root / entry.replace("\\", "/")).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise LocalAgentError(f"path_outside_workspace: {entry}") from exc
        snapshots[target] = target.read_bytes() if target.is_file() else None
    return snapshots


def restore_allowed_files(snapshots: dict[Path, bytes | None]) -> None:
    """Restore exactly the files captured before an implementer run."""
    for target, content in snapshots.items():
        if content is None:
            if target.exists() and target.is_file():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


@dataclass
class ToolAudit:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.calls.append({"tool": name, "ok": ok, "detail": detail[:500]})


class WorkspaceTools:
    def __init__(self, workspace: Path, role: str, allowed_files: list[str]) -> None:
        self.workspace = workspace.resolve()
        self.role = role
        self.allowed_files = {
            self._normalize_relative(entry) for entry in allowed_files if entry.strip()
        }
        self.audit = ToolAudit()

    @property
    def can_write(self) -> bool:
        return self.role == "implementer"

    def _normalize_relative(self, value: str) -> str:
        path = Path(value.replace("\\", "/"))
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(self.workspace)
            except ValueError as exc:
                raise LocalAgentError(f"path_outside_workspace: {value}") from exc
        normalized = path.as_posix().lstrip("./")
        if not normalized or normalized.startswith("../"):
            raise LocalAgentError(f"invalid_relative_path: {value}")
        return normalized

    def _resolve(self, value: str, *, write: bool = False) -> tuple[Path, str]:
        relative = self._normalize_relative(value)
        candidate = (self.workspace / relative).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise LocalAgentError(f"path_outside_workspace: {value}") from exc
        if write:
            if not self.can_write:
                raise LocalAgentError("validator_write_forbidden")
            if relative not in self.allowed_files:
                raise LocalAgentError(f"file_not_allowed: {relative}")
        return candidate, relative

    def read_file(self, path: str, start_line: int = 1, max_lines: int = 400) -> str:
        target, relative = self._resolve(path)
        lines = target.read_text(encoding="utf-8").splitlines()
        start = max(1, int(start_line)) - 1
        limit = max(1, min(int(max_lines), 1000))
        selected = lines[start : start + limit]
        result = "\n".join(f"{start + index + 1}: {line}" for index, line in enumerate(selected))
        self.audit.record("read_file", True, relative)
        return result or "<empty>"

    def search(self, pattern: str, paths: list[str] | None = None) -> str:
        command = ["rg", "-n", "--no-heading", "--color", "never", pattern]
        for entry in paths or ["."]:
            if entry == ".":
                command.append(".")
            else:
                _target, relative = self._resolve(entry)
                command.append(relative)
        completed = subprocess.run(
            command,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        output = (completed.stdout or completed.stderr or "<no matches>")[:MAX_TOOL_OUTPUT]
        self.audit.record("search", completed.returncode in {0, 1}, pattern)
        return output

    def replace_text(self, path: str, old: str, new: str) -> str:
        target, relative = self._resolve(path, write=True)
        original = target.read_text(encoding="utf-8") if target.exists() else ""
        occurrences = original.count(old)
        if occurrences != 1:
            raise LocalAgentError(f"replace_requires_one_match: found={occurrences}")
        target.write_text(original.replace(old, new, 1), encoding="utf-8", newline="")
        self.audit.record("replace_text", True, relative)
        return f"updated {relative}"

    def write_file(self, path: str, content: str) -> str:
        target, relative = self._resolve(path, write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        self.audit.record("write_file", True, relative)
        return f"wrote {relative} ({len(content)} chars)"

    def run_command(self, command: str, timeout_seconds: int = 120) -> str:
        normalized = str(command or "").strip()
        lowered = normalized.lower()
        if not any(lowered.startswith(prefix) for prefix in ALLOWED_COMMAND_PREFIXES):
            raise LocalAgentError("command_prefix_not_allowed")
        if any(re.search(pattern, lowered) for pattern in FORBIDDEN_COMMAND_PATTERNS):
            raise LocalAgentError("command_contains_forbidden_operation")
        timeout = max(1, min(int(timeout_seconds), 600))
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", normalized],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        result = (
            f"returncode={completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )[:MAX_TOOL_OUTPUT]
        self.audit.record("run_command", completed.returncode == 0, normalized)
        return result

    def schemas(self) -> list[dict[str, Any]]:
        tools = [
            _tool("read_file", "Read UTF-8 workspace file lines", {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "default": 1},
                "max_lines": {"type": "integer", "default": 400},
            }, ["path"]),
            _tool("search", "Search workspace text with ripgrep", {
                "pattern": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}},
            }, ["pattern"]),
            _tool("run_command", "Run an allowlisted read/check command", {
                "command": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 120},
            }, ["command"]),
        ]
        if self.can_write:
            tools.extend([
                _tool("replace_text", "Replace exactly one matching text block in an allowed file", {
                    "path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
                }, ["path", "old", "new"]),
                _tool("write_file", "Write complete UTF-8 content to an allowed file", {
                    "path": {"type": "string"}, "content": {"type": "string"},
                }, ["path", "content"]),
            ])
        return tools

    def invoke(self, name: str, arguments: dict[str, Any]) -> str:
        method = getattr(self, name, None)
        if name.startswith("_") or not callable(method) or name not in {tool["function"]["name"] for tool in self.schemas()}:
            raise LocalAgentError(f"unknown_tool: {name}")
        try:
            return str(method(**arguments))
        except Exception as exc:
            self.audit.record(name, False, f"arguments={arguments!r}; error={exc}")
            return f"ERROR: {type(exc).__name__}: {exc}"


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def ollama_chat(url: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise LocalAgentError(f"ollama_chat_failed: {exc}") from exc


def run_agent(
    *,
    role: str,
    model: str,
    prompt: str,
    workspace: Path,
    allowed_files: list[str],
    url: str = DEFAULT_OLLAMA_CHAT_URL,
    timeout_seconds: int = 300,
    max_turns: int = 40,
    think: bool = False,
) -> tuple[str, ToolAudit]:
    tools = WorkspaceTools(workspace, role, allowed_files)
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                f"You are {role}_local in a Windows repository. Use tools to do the work; do not merely describe it. "
                "Never invent tool results. Finish only after required checks."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    deadline = time.monotonic() + timeout_seconds
    empty_retries = 0
    for _turn in range(max_turns):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            raise LocalAgentError("agent_timeout")
        response = ollama_chat(
            url,
            {
                "model": model,
                "stream": False,
                "think": bool(think),
                "messages": messages,
                "tools": tools.schemas(),
                "options": {
                    "num_ctx": 32768,
                    "num_predict": 2048,
                    "temperature": 0.1,
                },
            },
            remaining,
        )
        message = response.get("message") or {}
        tool_calls = message.get("tool_calls") or []
        messages.append(message)
        if not tool_calls:
            content = str(message.get("content") or "").strip()
            if not content:
                if empty_retries < 2:
                    empty_retries += 1
                    messages.append(
                        {
                            "role": "user",
                            "content": "Your response was empty. Use the available tools now and continue the assigned work.",
                        }
                    )
                    continue
                raise LocalAgentError("agent_returned_empty_response")
            if not tools.audit.calls and empty_retries < 2:
                empty_retries += 1
                messages.append(
                    {
                        "role": "user",
                        "content": "Do not stop with a plan or explanation. Call the available tools and perform the work now.",
                    }
                )
                continue
            if role == "validator" and any(not entry["ok"] for entry in tools.audit.calls):
                content = (
                    "Validator encountered at least one rejected or failed tool call; "
                    "a PASS verdict is unsafe.\nBLOCKED"
                )
            return content, tools.audit
        for call in tool_calls:
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            result = tools.invoke(name, arguments)
            messages.append({"role": "tool", "tool_name": name, "content": result})
    raise LocalAgentError("agent_max_turns_exceeded")


def verify_tool_health(
    role: str,
    model: str,
    *,
    url: str = DEFAULT_OLLAMA_CHAT_URL,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    marker = "TRUBA_LOCAL_AGENT_TOOL_OK"
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"truba_{role}_health_") as temp_dir:
        workspace = Path(temp_dir)
        sentinel = workspace / "sentinel.txt"
        if role == "validator":
            sentinel.write_text(marker, encoding="utf-8")
            prompt = (
                "Use read_file on sentinel.txt, then use run_command with "
                "Get-Content sentinel.txt. If both show the exact marker, finish with "
                "exactly VALIDATOR_TOOL_HEALTH_PASS."
            )
            allowed_files: list[str] = []
        else:
            prompt = (
                f"Use write_file to create sentinel.txt containing exactly {marker}. "
                "Then use read_file to verify it and finish with exactly "
                "IMPLEMENTER_TOOL_HEALTH_PASS."
            )
            allowed_files = ["sentinel.txt"]
        final, audit = run_agent(
            role=role,
            model=model,
            prompt=prompt,
            workspace=workspace,
            allowed_files=allowed_files,
            url=url,
            timeout_seconds=timeout_seconds,
            max_turns=12,
            think=False,
        )
        names = [entry["tool"] for entry in audit.calls if entry["ok"]]
        if role == "implementer":
            file_ok = sentinel.is_file() and sentinel.read_text(encoding="utf-8") == marker
            required = {"write_file", "read_file"}
            final_ok = "IMPLEMENTER_TOOL_HEALTH_PASS" in final
            validator_write_exposed = False
        else:
            file_ok = sentinel.read_text(encoding="utf-8") == marker
            required = {"read_file", "run_command"}
            final_ok = "VALIDATOR_TOOL_HEALTH_PASS" in final
            validator_write_exposed = any(
                tool["function"]["name"] in {"write_file", "replace_text"}
                for tool in WorkspaceTools(workspace, role, []).schemas()
            )
        missing = sorted(required.difference(names))
        status = "PASS" if file_ok and final_ok and not missing and not validator_write_exposed else "FAIL"
        return {
            "schema_version": 1,
            "status": status,
            "role": role,
            "model": model,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "file_verified": file_ok,
            "final_verified": final_ok,
            "required_tools": sorted(required),
            "observed_tools": names,
            "missing_tools": missing,
            "validator_write_tools_exposed": validator_write_exposed,
            "temporary_cleanup_by_context": True,
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tool-capable local Ollama agent")
    parser.add_argument("--role", choices=("implementer", "validator"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--allowed-file", action="append", default=[])
    parser.add_argument("--url", default=DEFAULT_OLLAMA_CHAT_URL)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument("--think", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--evidence-file")
    parser.add_argument("--result-file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.health:
        try:
            evidence = verify_tool_health(
                args.role,
                args.model,
                url=args.url,
                timeout_seconds=args.timeout,
            )
        except Exception as exc:
            evidence = {
                "schema_version": 1,
                "status": "BLOCKED",
                "role": args.role,
                "model": args.model,
                "error": str(exc),
            }
        if args.evidence_file:
            Path(args.evidence_file).write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 0 if evidence["status"] == "PASS" else 2
    prompt = sys.stdin.read()
    workspace = Path(args.workspace).resolve()
    snapshots = (
        snapshot_allowed_files(workspace, args.allowed_file)
        if args.role == "implementer"
        else {}
    )
    try:
        final, audit = run_agent(
            role=args.role,
            model=args.model,
            prompt=prompt,
            workspace=workspace,
            allowed_files=args.allowed_file,
            url=args.url,
            timeout_seconds=args.timeout,
            max_turns=args.max_turns,
            think=args.think,
        )
    except Exception as exc:
        restore_allowed_files(snapshots)
        blocked = {
            "status": "BLOCKED",
            "error": str(exc),
            "changes_rolled_back": bool(snapshots),
        }
        if args.result_file:
            Path(args.result_file).write_text(
                json.dumps(blocked, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(blocked), file=sys.stderr)
        return 2
    unsafe_verdict = bool(re.search(r"\b(?:BLOCKED|FAIL)\b", final, re.IGNORECASE))
    failed_tools = [entry for entry in audit.calls if not entry["ok"]]
    if unsafe_verdict or failed_tools:
        restore_allowed_files(snapshots)
        blocked = {
            "status": "BLOCKED",
            "error": "unsafe_agent_result",
            "final": final,
            "tool_audit": audit.calls,
            "changes_rolled_back": bool(snapshots),
        }
        if args.result_file:
            Path(args.result_file).write_text(
                json.dumps(blocked, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(blocked, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.result_file:
        Path(args.result_file).write_text(
            json.dumps(
                {"status": "PASS", "final": final, "tool_audit": audit.calls},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    print(final)
    print(json.dumps({"tool_audit": audit.calls}, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
