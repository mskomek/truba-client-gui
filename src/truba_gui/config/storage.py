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
        return {"profiles": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # corrupted config; keep a backup and start fresh
        try:
            p.rename(p.with_suffix(".json.bak"))
        except Exception:
            pass
        return {"profiles": []}


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
