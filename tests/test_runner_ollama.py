from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from runner import runner
from runner import local_agent


class OllamaRunnerDiagnosticTests(unittest.TestCase):
    def test_validator_toolset_has_no_write_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tools = local_agent.WorkspaceTools(Path(temp_dir), "validator", [])
            names = {entry["function"]["name"] for entry in tools.schemas()}

        self.assertIn("read_file", names)
        self.assertIn("run_command", names)
        self.assertNotIn("write_file", names)
        self.assertNotIn("replace_text", names)

    def test_implementer_write_is_limited_to_allowed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tools = local_agent.WorkspaceTools(
                Path(temp_dir), "implementer", ["allowed.txt"]
            )
            self.assertIn("wrote allowed.txt", tools.write_file("allowed.txt", "ok"))
            with self.assertRaises(local_agent.LocalAgentError):
                tools.write_file("blocked.txt", "no")

    def test_native_agent_executes_tool_call_before_final_response(self) -> None:
        responses = [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "write_file",
                                "arguments": {"path": "sentinel.txt", "content": "ok"},
                            }
                        }
                    ],
                }
            },
            {"message": {"role": "assistant", "content": "DONE"}},
        ]
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            local_agent, "ollama_chat", side_effect=responses
        ):
            final, audit = local_agent.run_agent(
                role="implementer",
                model="qwen3.5:4b",
                prompt="write the marker",
                workspace=Path(temp_dir),
                allowed_files=["sentinel.txt"],
                timeout_seconds=30,
            )
            content = (Path(temp_dir) / "sentinel.txt").read_text(encoding="utf-8")

        self.assertEqual(final, "DONE")
        self.assertEqual(content, "ok")
        self.assertEqual(audit.calls[0]["tool"], "write_file")

    def test_validator_cannot_pass_after_a_rejected_tool_call(self) -> None:
        responses = [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "run_command",
                                "arguments": {"command": "Remove-Item important.txt"},
                            }
                        }
                    ],
                }
            },
            {"message": {"role": "assistant", "content": "PASS"}},
        ]
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            local_agent, "ollama_chat", side_effect=responses
        ):
            final, audit = local_agent.run_agent(
                role="validator",
                model="qwen3.5:9b",
                prompt="validate",
                workspace=Path(temp_dir),
                allowed_files=[],
                timeout_seconds=30,
            )

        self.assertTrue(final.endswith("BLOCKED"))
        self.assertFalse(audit.calls[0]["ok"])

    def test_agent_retries_an_empty_response_and_requires_a_tool(self) -> None:
        responses = [
            {"message": {"role": "assistant", "content": ""}},
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "read_file",
                                "arguments": {"path": "sentinel.txt"},
                            }
                        }
                    ],
                }
            },
            {"message": {"role": "assistant", "content": "DONE"}},
        ]
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            local_agent, "ollama_chat", side_effect=responses
        ):
            (Path(temp_dir) / "sentinel.txt").write_text("ok", encoding="utf-8")
            final, audit = local_agent.run_agent(
                role="validator",
                model="qwen3.5:9b",
                prompt="read marker",
                workspace=Path(temp_dir),
                allowed_files=[],
                timeout_seconds=30,
            )

        self.assertEqual(final, "DONE")
        self.assertEqual(audit.calls[0]["tool"], "read_file")

    def test_implementer_cli_rolls_back_files_when_agent_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "source.py"
            target.write_text("original\n", encoding="utf-8")

            def fail_after_edit(**_kwargs):
                target.write_text("broken\n", encoding="utf-8")
                raise local_agent.LocalAgentError("agent_max_turns_exceeded")

            with (
                patch.object(local_agent, "run_agent", side_effect=fail_after_edit),
                patch("sys.stdin", StringIO("edit source")),
            ):
                returncode = local_agent.main(
                    [
                        "--role", "implementer",
                        "--model", "qwen3.5:4b",
                        "--workspace", temp_dir,
                        "--allowed-file", "source.py",
                    ]
                )

            self.assertEqual(returncode, 2)
            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")

    def test_verify_local_runs_cli_server_and_selected_model_inference(self) -> None:
        calls: list[list[str]] = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            if command[-1] == "--version":
                return subprocess.CompletedProcess(command, 0, "ollama version 1.0\n", "")
            if command[-1] == "list":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    "NAME ID SIZE MODIFIED\nqwen3.5:9b abc 6GB now\nqwen3.5:4b def 3GB now\n",
                    "",
                )
            return subprocess.CompletedProcess(command, 0, "LOCAL_OLLAMA_OK\n", "")

        with (
            patch.object(runner, "resolve_ollama_command", return_value="C:/Ollama/ollama.exe"),
            patch.object(runner.subprocess, "run", side_effect=fake_run),
        ):
            evidence = runner.verify_local_ollama(
                "ollama",
                "qwen3.5:9b",
                30,
                role="implementer",
            )

        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["model"], "qwen3.5:9b")
        self.assertTrue(evidence["model_available"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[2][:4], ["C:/Ollama/ollama.exe", "run", "--think=false", "qwen3.5:9b"])
        self.assertEqual(
            evidence["checks"]["inference"]["command"][-1],
            "<fixed-verification-prompt>",
        )
        self.assertNotIn(runner.LOCAL_VERIFY_PROMPT, json.dumps(evidence))

    def test_verify_local_blocks_inference_when_model_is_not_installed(self) -> None:
        calls: list[list[str]] = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            stdout = "ollama version 1.0\n" if command[-1] == "--version" else "NAME ID SIZE MODIFIED\n"
            return subprocess.CompletedProcess(command, 0, stdout, "")

        with (
            patch.object(runner, "resolve_ollama_command", return_value="ollama"),
            patch.object(runner.subprocess, "run", side_effect=fake_run),
        ):
            evidence = runner.verify_local_ollama(
                "ollama",
                "qwen3.5:4b",
                30,
                role="validator",
            )

        self.assertEqual(evidence["status"], "BLOCKED")
        self.assertFalse(evidence["model_available"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(evidence["checks"]["inference"]["error"], "prerequisite_check_failed")

    def test_verify_local_reports_missing_cli_without_raising(self) -> None:
        with (
            patch.object(runner, "resolve_ollama_command", return_value="missing-ollama"),
            patch.object(runner.subprocess, "run", side_effect=FileNotFoundError),
        ):
            evidence = runner.verify_local_ollama(
                "missing-ollama",
                "qwen3.5:9b",
                30,
                role="implementer",
            )

        self.assertEqual(evidence["status"], "BLOCKED")
        self.assertEqual(evidence["checks"]["cli"]["error"], "ollama_cli_not_found")
        self.assertEqual(evidence["checks"]["server_and_models"]["error"], "ollama_cli_not_found")

    def test_verify_local_cuda_requires_full_gpu_and_telemetry(self) -> None:
        def fake_run(command, **_kwargs):
            if command[-1] == "--version":
                return subprocess.CompletedProcess(command, 0, "ollama version 1.0\n", "")
            if command[-1] == "list":
                return subprocess.CompletedProcess(command, 0, "NAME ID SIZE MODIFIED\nqwen3.5:4b abc 3GB now\n", "")
            if command[-1] == "ps":
                return subprocess.CompletedProcess(command, 0, "NAME ID SIZE PROCESSOR UNTIL\nqwen3.5:4b abc 3GB 100% GPU 4 minutes\n", "")
            if command[0] == "nvidia-smi":
                return subprocess.CompletedProcess(command, 0, "0, RTX 2060, 3800, 6144, 42\n", "")
            return subprocess.CompletedProcess(command, 0, "LOCAL_OLLAMA_OK\n", "")

        with (
            patch.object(runner, "resolve_ollama_command", return_value="ollama"),
            patch.object(runner.subprocess, "run", side_effect=fake_run),
        ):
            evidence = runner.verify_local_cuda("ollama", "qwen3.5:4b", 30, role="implementer")

        self.assertEqual(evidence["status"], "PASS")
        self.assertTrue(evidence["checks"]["ollama_ps"]["model_full_gpu"])
        self.assertTrue(evidence["checks"]["nvidia_smi"]["telemetry_available"])

    def test_verify_local_cuda_fails_when_selected_model_is_not_full_gpu(self) -> None:
        with patch.object(
            runner,
            "verify_local_ollama",
            return_value={
                "status": "PASS", "ollama_command": "ollama",
                "checks": {"cli": {"status": "PASS"}, "server_and_models": {"status": "PASS"}, "inference": {"status": "PASS"}},
            },
        ), patch.object(
            runner,
            "_run_ollama_diagnostic_command",
            side_effect=[
                ({"status": "PASS"}, "NAME ID SIZE PROCESSOR UNTIL\nqwen3.5:4b id 3GB 0% GPU 4 minutes\n"),
                ({"status": "PASS"}, "0, RTX 2060, 100, 6144, 1\n"),
            ],
        ):
            evidence = runner.verify_local_cuda("ollama", "qwen3.5:4b", 30, role="validator")

        self.assertEqual(evidence["status"], "FAIL")
        self.assertEqual(evidence["checks"]["ollama_ps"]["error"], "selected_model_not_100_percent_gpu")

    def test_help_does_not_invoke_ollama(self) -> None:
        with patch.object(runner.subprocess, "run") as run_mock:
            with self.assertRaises(SystemExit) as raised:
                runner.parse_args(["--help"])

        self.assertEqual(raised.exception.code, 0)
        run_mock.assert_not_called()

    def test_main_verify_local_selects_validator_model_and_prints_json(self) -> None:
        evidence = {"status": "PASS", "model": "qwen3.5:9b"}
        output = StringIO()
        with (
            patch.object(runner, "verify_local_ollama", return_value=evidence) as verify_mock,
            redirect_stdout(output),
        ):
            returncode = runner.main(["--verify-local", "--verify-role", "validator"])

        self.assertEqual(returncode, 0)
        self.assertEqual(json.loads(output.getvalue()), evidence)
        self.assertEqual(verify_mock.call_args.args[1], "qwen3.5:9b")


if __name__ == "__main__":
    unittest.main()
