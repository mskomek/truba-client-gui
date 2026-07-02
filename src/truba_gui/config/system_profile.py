from __future__ import annotations

from typing import Any

from truba_gui.config.storage import load_settings, update_settings


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

SYSTEM_TEMPLATE_SETTINGS_KEY = "system_templates"


def truba_default_remote_paths() -> dict[str, str]:
    return {
        "scratch_dir": TRUBA_SYSTEM_DEFAULTS["scratch_dir"],
        "home_dir": TRUBA_SYSTEM_DEFAULTS["home_dir"],
    }


def builtin_system_template_groups() -> dict[str, list[dict[str, str]]]:
    return {
        "TRUBA": [dict(TRUBA_SYSTEM_DEFAULTS)],
    }


def normalize_system_settings(value: Any) -> dict[str, str]:
    settings = dict(TRUBA_SYSTEM_DEFAULTS)
    if isinstance(value, dict):
        for key in settings:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                settings[key] = candidate.strip()
    return settings


def load_user_system_templates() -> list[dict[str, str]]:
    templates = load_settings().get(SYSTEM_TEMPLATE_SETTINGS_KEY, [])
    if not isinstance(templates, list):
        return []
    result: list[dict[str, str]] = []
    for item in templates:
        if not isinstance(item, dict):
            continue
        normalized = normalize_system_settings(item)
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        normalized["name"] = name
        result.append(normalized)
    return result


def save_user_system_template(name: str, settings: Any) -> dict[str, str]:
    template = normalize_system_settings(settings)
    template["name"] = str(name or "").strip()
    if not template["name"]:
        raise ValueError("system template name is required")

    templates = load_user_system_templates()
    index = next(
        (
            idx
            for idx, existing in enumerate(templates)
            if existing.get("name", "").casefold() == template["name"].casefold()
        ),
        None,
    )
    if index is None:
        templates.append(template)
    else:
        templates[index] = template
    update_settings({SYSTEM_TEMPLATE_SETTINGS_KEY: templates})
    return template


def format_remote_path(template: str, username: str) -> str:
    try:
        return template.format(user=username)
    except (KeyError, ValueError):
        return template
