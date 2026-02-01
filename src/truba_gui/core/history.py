import json
from pathlib import Path
from datetime import datetime

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
    event = dict(event)
    event["ts"] = datetime.now().isoformat(timespec="seconds")
    data.append(event)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
