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
