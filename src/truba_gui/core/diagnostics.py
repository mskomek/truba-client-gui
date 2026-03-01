from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable


def _candidate_files() -> Iterable[Path]:
    base = Path.home() / ".truba_slurm_gui"
    names = [
        "app.log",
        "config.json",
        "history.json",
        "history.jsonl",
        "last_batch.json",
        "processes.json",
        "transfer_journal.jsonl",
        "vcxsrv_stdout.log",
        "vcxsrv_stderr.log",
        "language.json",
    ]
    for n in names:
        p = base / n
        if p.exists() and p.is_file():
            yield p


def create_diagnostic_bundle(dest_dir: str) -> Path:
    out_dir = Path(dest_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = out_dir / f"truba_diagnostics_{stamp}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in _candidate_files():
            zf.write(p, arcname=p.name)
        manifest = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "bundle": zip_path.name,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return zip_path
