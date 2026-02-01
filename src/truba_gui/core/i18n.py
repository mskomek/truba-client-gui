import json
from pathlib import Path

_LANG: dict = {}
_CURRENT = "tr"

def load_language(lang: str = "tr") -> None:
    global _LANG, _CURRENT
    base = Path(__file__).resolve().parent.parent
    path = base / "i18n" / f"{lang}.json"
    with open(path, "r", encoding="utf-8") as f:
        _LANG = json.load(f)
    _CURRENT = lang

def t(key: str) -> str:
    cur = _LANG
    try:
        for part in key.split("."):
            cur = cur[part]
        return cur if isinstance(cur, str) else f"[{key}]"
    except Exception:
        return f"[{key}]"
