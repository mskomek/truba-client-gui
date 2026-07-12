from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _config_dir() -> Path:
    d = Path.home() / ".truba_slurm_gui"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _config_path() -> Path:
    return _config_dir() / "config.json"


def load_config() -> Dict[str, Any]:
    p = _config_path()
    if not p.exists():
        return {"profiles": [], "settings": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # corrupted config; keep a backup and start fresh
        try:
            p.rename(p.with_suffix(".json.bak"))
        except Exception:
            pass
        return {"profiles": [], "settings": {}}


def load_settings() -> Dict[str, Any]:
    """Load application-wide settings stored in config.json.

    Settings are kept separate from profiles.
    """
    cfg = load_config()
    st = cfg.get("settings", {})
    return st if isinstance(st, dict) else {}


def update_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge patch into settings and persist."""
    cfg = load_config()
    st = cfg.get("settings")
    if not isinstance(st, dict):
        st = {}
    for k, v in (patch or {}).items():
        st[k] = v
    cfg["settings"] = st
    save_config(cfg)
    return st


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        coerced = int(value)
    except Exception:
        return default
    return coerced if coerced > 0 else default


def _coerce_int_in_range(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        coerced = int(value)
    except Exception:
        return default
    if coerced < minimum:
        return minimum
    if coerced > maximum:
        return maximum
    return coerced


def get_jobs_outputs_refresh_interval_seconds(default: int = 15) -> int:
    """Return the live Jobs & Outputs polling interval in seconds."""
    st = load_settings()
    return _coerce_positive_int(st.get("jobs_outputs_refresh_interval_seconds", default), default)


def set_jobs_outputs_refresh_interval_seconds(seconds: int) -> int:
    """Persist the live Jobs & Outputs polling interval in seconds."""
    value = _coerce_positive_int(seconds, 15)
    update_settings({"jobs_outputs_refresh_interval_seconds": value})
    return value


def get_sbatch_auto_open_outputs_enabled(default: bool = True) -> bool:
    """Return whether sbatch submissions should switch to Jobs & Outputs."""
    value = load_settings().get("sbatch_auto_open_outputs", default)
    return value if isinstance(value, bool) else default


def set_sbatch_auto_open_outputs_enabled(enabled: bool) -> bool:
    """Persist whether sbatch submissions should switch to Jobs & Outputs."""
    value = bool(enabled)
    update_settings({"sbatch_auto_open_outputs": value})
    return value


SBATCH_FOLLOW_MODE_OUTPUTS_TAB = "outputs_tab"
SBATCH_FOLLOW_MODE_NEW_WINDOW_COMBINED = "new_window_combined"
SBATCH_FOLLOW_MODE_NEW_WINDOWS_SPLIT = "new_windows_split"
SBATCH_FOLLOW_MODE_NEW_TABS_SPLIT = "new_tabs_split"
SBATCH_FOLLOW_MODES = {
    SBATCH_FOLLOW_MODE_OUTPUTS_TAB,
    SBATCH_FOLLOW_MODE_NEW_WINDOW_COMBINED,
    SBATCH_FOLLOW_MODE_NEW_WINDOWS_SPLIT,
    SBATCH_FOLLOW_MODE_NEW_TABS_SPLIT,
}


def get_sbatch_follow_mode(default: str = SBATCH_FOLLOW_MODE_NEW_TABS_SPLIT) -> str:
    """Return where parsed sbatch output/error files should be followed."""
    value = str(load_settings().get("sbatch_follow_mode", default)).strip()
    return value if value in SBATCH_FOLLOW_MODES else default


def set_sbatch_follow_mode(mode: str) -> str:
    """Persist where parsed sbatch output/error files should be followed."""
    value = str(mode or "").strip()
    if value not in SBATCH_FOLLOW_MODES:
        value = SBATCH_FOLLOW_MODE_NEW_TABS_SPLIT
    update_settings({"sbatch_follow_mode": value})
    return value


def get_lssrv_auto_refresh_enabled(default: bool = False) -> bool:
    """Return whether lssrv should refresh with the Jobs polling timer."""
    value = load_settings().get("lssrv_auto_refresh_enabled", default)
    return value if isinstance(value, bool) else default


def set_lssrv_auto_refresh_enabled(enabled: bool) -> bool:
    """Persist whether lssrv should refresh with the Jobs polling timer."""
    value = bool(enabled)
    update_settings({"lssrv_auto_refresh_enabled": value})
    return value


def get_transfer_parallelism(default: int = 1) -> int:
    """Return the configured transfer queue parallelism, capped at 10."""
    st = load_settings()
    return _coerce_int_in_range(st.get("transfer_parallelism", default), default, 1, 10)


def set_transfer_parallelism(count: int) -> int:
    """Persist the transfer queue parallelism, capped at 10."""
    value = _coerce_int_in_range(count, 1, 1, 10)
    update_settings({"transfer_parallelism": value})
    return value


def get_transfer_auto_refresh_enabled(default: bool = True) -> bool:
    """Return whether transfer/mutation completion should refresh affected panes."""
    value = load_settings().get("transfer_auto_refresh_enabled", default)
    return value if isinstance(value, bool) else default


def set_transfer_auto_refresh_enabled(enabled: bool) -> bool:
    """Persist whether transfer/mutation completion should refresh affected panes."""
    value = bool(enabled)
    update_settings({"transfer_auto_refresh_enabled": value})
    return value


def get_last_seen_changelog_version(default: str = "") -> str:
    """Return the app version whose startup changelog was last acknowledged."""
    value = load_settings().get("last_seen_changelog_version", default)
    return str(value or "").strip()


def set_last_seen_changelog_version(version: str) -> str:
    """Persist that the startup changelog has been shown for a version."""
    value = str(version or "").strip()
    update_settings({"last_seen_changelog_version": value})
    return value


def get_ftp_transfer_type(default: str = "auto") -> str:
    value = str(load_settings().get("ftp_transfer_type", default)).strip().lower()
    return value if value in {"auto", "binary", "ascii"} else default


def set_ftp_transfer_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"auto", "binary", "ascii"}:
        normalized = "auto"
    update_settings({"ftp_transfer_type": normalized})
    return normalized


def _normalize_file_extension(extension: str) -> str:
    value = str(extension or "").strip().lower()
    if not value:
        return ""
    return value if value.startswith(".") else f".{value}"


def get_file_associations() -> Dict[str, str]:
    value = load_settings().get("file_associations", {})
    if not isinstance(value, dict):
        return {}
    associations: Dict[str, str] = {}
    for extension, program in value.items():
        normalized = _normalize_file_extension(str(extension))
        program_path = str(program or "").strip()
        if normalized and program_path:
            associations[normalized] = program_path
    return associations


def get_file_association(extension: str) -> str:
    normalized = _normalize_file_extension(extension)
    if not normalized:
        return ""
    return get_file_associations().get(normalized, "")


def set_file_association(extension: str, program_path: str) -> Dict[str, str]:
    normalized = _normalize_file_extension(extension)
    associations = get_file_associations()
    if normalized:
        program = str(program_path or "").strip()
        if program:
            associations[normalized] = program
        else:
            associations.pop(normalized, None)
    update_settings({"file_associations": associations})
    return associations


def clear_file_association(extension: str) -> Dict[str, str]:
    normalized = _normalize_file_extension(extension)
    associations = get_file_associations()
    if normalized:
        associations.pop(normalized, None)
    update_settings({"file_associations": associations})
    return associations


def get_ftp_state() -> Dict[str, Any]:
    st = load_settings()
    sizes = st.get("ftp_splitter_sizes", [1, 1])
    if not isinstance(sizes, list) or len(sizes) != 2:
        sizes = [1, 1]
    try:
        sizes = [max(1, int(sizes[0])), max(1, int(sizes[1]))]
    except Exception:
        sizes = [1, 1]
    active = str(st.get("ftp_active_remote", "scratch")).lower()
    if active not in {"scratch", "home"}:
        active = "scratch"
    return {
        "local_dir": str(st.get("ftp_local_dir", "")),
        "active_remote": active,
        "splitter_sizes": sizes,
    }


def update_ftp_state(
    *,
    local_dir: str | None = None,
    active_remote: str | None = None,
    splitter_sizes: List[int] | None = None,
) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    if local_dir is not None:
        patch["ftp_local_dir"] = str(local_dir)
    if active_remote is not None:
        active = str(active_remote).lower()
        patch["ftp_active_remote"] = active if active in {"scratch", "home"} else "scratch"
    if splitter_sizes is not None and len(splitter_sizes) == 2:
        patch["ftp_splitter_sizes"] = [max(1, int(value)) for value in splitter_sizes]
    return update_settings(patch)


def save_config(cfg: Dict[str, Any]) -> None:
    p = _config_path()
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_profiles() -> List[Dict[str, Any]]:
    cfg = load_config()
    profs = cfg.get("profiles", [])
    return profs if isinstance(profs, list) else []


def upsert_profile(profile: Dict[str, Any]) -> None:
    """Insert or update by profile['name'] (case-sensitive)."""
    name = (profile.get("name") or "").strip()
    if not name:
        raise ValueError("profile name is required")

    cfg = load_config()
    profs = cfg.get("profiles", [])
    if not isinstance(profs, list):
        profs = []

    idx = next((i for i, p in enumerate(profs) if p.get("name") == name), None)
    if idx is None:
        profs.append(profile)
    else:
        profs[idx] = profile

    cfg["profiles"] = profs
    cfg["last_profile"] = name
    save_config(cfg)


def delete_profile(name: str) -> None:
    name = (name or "").strip()
    cfg = load_config()
    profs = cfg.get("profiles", [])
    if not isinstance(profs, list):
        profs = []
    cfg["profiles"] = [p for p in profs if p.get("name") != name]
    if cfg.get("last_profile") == name:
        cfg.pop("last_profile", None)
    save_config(cfg)


def get_last_profile_name() -> Optional[str]:
    cfg = load_config()
    v = cfg.get("last_profile")
    return v if isinstance(v, str) and v.strip() else None


def get_ui_pref_bool(key: str, default: bool = True) -> bool:
    cfg = load_config()
    ui = cfg.get("ui", {})
    if not isinstance(ui, dict):
        ui = {}
    v = ui.get(key)
    if isinstance(v, bool):
        return v
    return default


def set_ui_pref_bool(key: str, value: bool) -> None:
    cfg = load_config()
    ui = cfg.get("ui", {})
    if not isinstance(ui, dict):
        ui = {}
    ui[key] = bool(value)
    cfg["ui"] = ui
    save_config(cfg)
