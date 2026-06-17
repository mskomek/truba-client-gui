from __future__ import annotations

import posixpath
import shlex
from typing import Any

from .slurm_base import SlurmBackend
from truba_gui.config.system_profile import normalize_system_settings
from truba_gui.ssh.client import SSHClientWrapper


class SSHSlurmBackend(SlurmBackend):
    def __init__(
        self,
        ssh: SSHClientWrapper,
        system_settings: dict[str, Any] | None = None,
    ):
        self.ssh = ssh
        self.system_settings = normalize_system_settings(system_settings)

    def _command(self, key: str, **values: str) -> str:
        template = self.system_settings[key]
        quoted = {
            f"{name}_q": shlex.quote(str(value))
            for name, value in values.items()
        }
        return template.format(**values, **quoted)

    def squeue(self, user: str) -> str:
        cmd = self._command("squeue_command", user=user)
        code, out, err = self.ssh.run(cmd, log_output=False)
        return out if out.strip() else (err or f"[exit={code}]")

    def sbatch(self, script_path: str) -> str:
        script_dir = posixpath.dirname(script_path) or "."
        script_name = posixpath.basename(script_path)
        cmd = self._command(
            "sbatch_command",
            script_dir=script_dir,
            script_name=script_name,
        )
        code, out, err = self.ssh.run(cmd, log_output=False)
        return out if out.strip() else (err or f"[exit={code}]")

    def scancel(self, job_id: str) -> str:
        cmd = self._command("scancel_command", job_id=job_id)
        code, out, err = self.ssh.run(cmd, log_output=False)
        return out.strip() or (
            "OK" if code == 0 else (err or f"[exit={code}]")
        )

    def sacct(self, user: str) -> str:
        cmd = self._command("sacct_command", user=user)
        code, out, err = self.ssh.run(cmd, log_output=False)
        return out if out.strip() else (err or f"[exit={code}]")

    def scontrol_show_job(self, job_id: str) -> str:
        cmd = self._command("scontrol_command", job_id=job_id)
        code, out, err = self.ssh.run(cmd, log_output=False)
        return out if out.strip() else (err or f"[exit={code}]")

    def lssrv(self) -> str:
        code, out, err = self.ssh.run(
            self.system_settings["status_command"],
            log_output=False,
        )
        if code != 0:
            raise RuntimeError(
                err.strip() or out.strip() or f"lssrv failed [exit={code}]"
            )
        return out

    def active_job_ids(self, user: str) -> str:
        cmd = self._command("active_job_ids_command", user=user)
        code, out, err = self.ssh.run(cmd, log_output=False)
        return out if code == 0 else (err or out)

    def job_state(self, job_id: str) -> str:
        cmd = self._command("job_state_command", job_id=job_id)
        code, out, err = self.ssh.run(cmd, log_output=False)
        return out if code == 0 else (err or out)
