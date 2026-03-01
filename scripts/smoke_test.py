from __future__ import annotations

from truba_gui.services.slurm_script_parser import parse_output_error, resolve_path
from truba_gui.services.command_history_store import is_sensitive_command
from truba_gui.core.diagnostics import create_diagnostic_bundle
from tempfile import TemporaryDirectory


def main() -> int:
    script = """#!/bin/bash
#SBATCH --output=logs/out_%j.txt
#SBATCH --error=logs/err_%j.txt
echo hello
"""
    out, err = parse_output_error(script)
    assert out == "logs/out_%j.txt"
    assert err == "logs/err_%j.txt"
    assert resolve_path("/arf/home/u/job.sbatch", out, job_id="1234").endswith("/logs/out_1234.txt")
    assert is_sensitive_command("curl -H 'Authorization: Bearer abc'")
    with TemporaryDirectory() as td:
        _ = create_diagnostic_bundle(td)
    print("smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
