from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple

SBATCH_OUT_PATTERNS = [
    re.compile(r"^\s*#SBATCH\s+--output\s*=\s*(.+?)\s*$"),
    re.compile(r"^\s*#SBATCH\s+-o\s+(.+?)\s*$"),
]
SBATCH_ERR_PATTERNS = [
    re.compile(r"^\s*#SBATCH\s+--error\s*=\s*(.+?)\s*$"),
    re.compile(r"^\s*#SBATCH\s+-e\s+(.+?)\s*$"),
]

def _first_match(lines, patterns) -> Optional[str]:
    for ln in lines:
        for pat in patterns:
            m = pat.match(ln)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    return None

def parse_output_error(script_text: str) -> Tuple[Optional[str], Optional[str]]:
    lines = script_text.splitlines()
    out = _first_match(lines, SBATCH_OUT_PATTERNS)
    err = _first_match(lines, SBATCH_ERR_PATTERNS)
    return out, err

def resolve_path(script_remote_path: str, value: str, job_id: Optional[str] = None, job_name: Optional[str] = None) -> str:
    # Replace common placeholders if possible
    if job_id:
        value = value.replace("%j", str(job_id)).replace("%A", str(job_id))
    if job_name:
        value = value.replace("%x", str(job_name))
    # If relative, resolve relative to script directory
    if not value.startswith("/"):
        base = os.path.dirname(script_remote_path)
        value = base.rstrip("/") + "/" + value
    return value
