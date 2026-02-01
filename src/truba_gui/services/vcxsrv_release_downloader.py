from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Optional

GITHUB_API_LATEST = "https://api.github.com/repos/marchaesen/vcxsrv/releases/latest"

@dataclass
class ReleaseAsset:
    name: str
    download_url: str
    size: int
    tag: str

def _http_get_json(url: str, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            # GitHub API is rate-limited; a UA improves compatibility.
            "User-Agent": "TrubaGUI/1.0 (+https://github.com/)",
            "Accept": "application/vnd.github+json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8", errors="replace"))

def pick_best_asset(release_json: dict) -> Optional[ReleaseAsset]:
    """
    Prefer a 'noadmin' installer (usually NSIS) to avoid requiring admin rights.
    Also avoid 'debug' assets when possible.
    """
    tag = str(release_json.get("tag_name") or "")
    assets = release_json.get("assets") or []

    def score(a: dict) -> int:
        name = str(a.get("name") or "").lower()
        s = 0
        if name.endswith(".exe"):
            s += 10
        if "installer" in name:
            s += 10
        if "noadmin" in name:
            s += 50
        if "debug" in name:
            s -= 20
        if "32" in name or "x86" in name:
            s -= 10
        # prefer 64-bit
        if "64" in name or "x64" in name:
            s += 5
        return s

    best = None
    best_score = -10**9
    for a in assets:
        sc = score(a)
        if sc > best_score:
            best_score = sc
            best = a

    if not best:
        return None

    return ReleaseAsset(
        name=str(best.get("name") or ""),
        download_url=str(best.get("browser_download_url") or ""),
        size=int(best.get("size") or 0),
        tag=tag,
    )

def get_latest_vcxsrv_asset() -> Optional[ReleaseAsset]:
    try:
        rel = _http_get_json(GITHUB_API_LATEST)
        return pick_best_asset(rel)
    except Exception:
        return None
