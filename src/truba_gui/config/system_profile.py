from __future__ import annotations

from typing import Any


TRUBA_SYSTEM_DEFAULTS: dict[str, str] = {
    "name": "TRUBA",
    "scratch_dir": "/arf/scratch/{user}",
    "home_dir": "/arf/home/{user}",
    "squeue_command": "squeue -u {user}",
    "sbatch_command": "cd -- {script_dir_q} && sbatch -- {script_name_q}",
    "scancel_command": "scancel {job_id_q}",
    "sacct_command": (
        "sacct -u {user} "
        "--format=JobID,JobName,State,Elapsed,MaxRSS,AllocTRES"
    ),
    "scontrol_command": "scontrol show job {job_id_q}",
    "status_command": "lssrv",
    "active_job_ids_command": 'squeue -h -u {user} -o "%A"',
    "job_state_command": "sacct -n -X -j {job_id_q} -o State -P",
}


def normalize_system_settings(value: Any) -> dict[str, str]:
    settings = dict(TRUBA_SYSTEM_DEFAULTS)
    if isinstance(value, dict):
        for key in settings:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                settings[key] = candidate.strip()
    return settings


def format_remote_path(template: str, username: str) -> str:
    try:
        return template.format(user=username)
    except (KeyError, ValueError):
        return template
