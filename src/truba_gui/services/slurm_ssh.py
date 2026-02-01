from __future__ import annotations

from .slurm_base import SlurmBackend
from truba_gui.ssh.client import SSHClientWrapper


class SSHSlurmBackend(SlurmBackend):
    def __init__(self, ssh: SSHClientWrapper):
        self.ssh = ssh

    def squeue(self, user: str) -> str:
        cmd = f"squeue -u {user}"
        code, out, err = self.ssh.run(cmd)
        return out if out.strip() else (err or f"[exit={code}]")

    def sbatch(self, script_path: str) -> str:
        cmd = f"sbatch {script_path}"
        code, out, err = self.ssh.run(cmd)
        return out if out.strip() else (err or f"[exit={code}]")

    def scancel(self, job_id: str) -> str:
        cmd = f"scancel {job_id}"
        code, out, err = self.ssh.run(cmd)
        # scancel usually has no stdout
        return out.strip() or ( "OK" if code == 0 else (err or f"[exit={code}]") )
