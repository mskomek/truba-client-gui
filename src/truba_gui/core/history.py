import json
from pathlib import Path
from datetime import datetime

from truba_gui.services.command_history_store import is_sensitive_command


def _redact_cmd(cmd: str) -> str:
    """Redact secrets inside a command string.

    We avoid persisting secrets entirely in command history. For event logs,
    we store a redacted placeholder when the command looks sensitive.
    """
    if is_sensitive_command(cmd):
        return "<redacted>"
    return cmd


def _sanitize_event(event: dict) -> dict:
    e = dict(event or {})
    # Never persist plaintext password-like keys if they appear.
    for k in list(e.keys()):
        if str(k).lower() in {"password", "pass", "passphrase", "parola", "sifre", "secret", "token", "api_key", "apikey"}:
            e[k] = "<redacted>"
    if "cmd" in e and isinstance(e["cmd"], str):
        e["cmd"] = _redact_cmd(e["cmd"])
    return e

def _history_path() -> Path:
    base = Path.home() / ".truba_slurm_gui"
    base.mkdir(parents=True, exist_ok=True)
    return base / "history.json"

def append_event(event: dict) -> None:
    p = _history_path()
    data = []
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = []
    event = _sanitize_event(event)
    event["ts"] = datetime.now().isoformat(timespec="seconds")
    data.append(event)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
