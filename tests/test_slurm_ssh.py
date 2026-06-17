from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from truba_gui.services.slurm_ssh import SSHSlurmBackend


class _FakeSSH:
    def __init__(self, result):
        self.result = result
        self.commands = []

    def run(self, command: str, **_kwargs):
        self.commands.append(command)
        return self.result


class SSHSlurmBackendTests(unittest.TestCase):
    def test_sbatch_runs_from_script_parent_directory(self):
        ssh = _FakeSSH((0, "Submitted batch job 123\n", ""))

        result = SSHSlurmBackend(ssh).sbatch(
            "/arf/scratch/mkomek/kare/job.slurm"
        )

        self.assertEqual(
            ssh.commands,
            ["cd -- /arf/scratch/mkomek/kare && sbatch -- job.slurm"],
        )
        self.assertEqual(result, "Submitted batch job 123\n")

    def test_sbatch_quotes_directory_and_basename(self):
        ssh = _FakeSSH((0, "Submitted batch job 124", ""))

        SSHSlurmBackend(ssh).sbatch(
            "/arf/scratch/mko'mek/kare iş/job'ın.slurm"
        )

        self.assertEqual(
            ssh.commands,
            [
                "cd -- '/arf/scratch/mko'\"'\"'mek/kare iş'"
                " && sbatch -- 'job'\"'\"'ın.slurm'"
            ],
        )

    def test_sbatch_preserves_stderr_fallback(self):
        ssh = _FakeSSH((1, "", "submission failed"))

        result = SSHSlurmBackend(ssh).sbatch("/tmp/job.sbatch")

        self.assertEqual(result, "submission failed")

    def test_sbatch_preserves_exit_code_fallback(self):
        ssh = _FakeSSH((2, "", ""))

        result = SSHSlurmBackend(ssh).sbatch("/tmp/job.sbatch")

        self.assertEqual(result, "[exit=2]")

    def test_custom_system_commands_are_used(self):
        ssh = _FakeSSH((0, "ok", ""))
        backend = SSHSlurmBackend(
            ssh,
            {
                "squeue_command": "queue --owner {user}",
                "status_command": "cluster-status",
                "active_job_ids_command": "queue-ids {user}",
                "job_state_command": "job-state {job_id_q}",
            },
        )

        backend.squeue("alice")
        backend.lssrv()
        backend.active_job_ids("alice")
        backend.job_state("12 34")

        self.assertEqual(
            ssh.commands,
            [
                "queue --owner alice",
                "cluster-status",
                "queue-ids alice",
                "job-state '12 34'",
            ],
        )


if __name__ == "__main__":
    unittest.main()
