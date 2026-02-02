import json
import locale
from pathlib import Path

_SETTINGS_DIR = Path.home() / ".truba_slurm_gui"
_LANG_FILE = _SETTINGS_DIR / "language.json"

_LANG: dict = {}
_CURRENT = "tr"

def load_language(lang: str = "tr") -> None:
    global _LANG, _CURRENT
    base = Path(__file__).resolve().parent.parent
    path = base / "i18n" / f"{lang}.json"
    with open(path, "r", encoding="utf-8") as f:
        _LANG = json.load(f)
    _CURRENT = lang


def current_language() -> str:
    return _CURRENT


def set_language(lang: str) -> None:
    """Set UI language and persist it under ~/.truba_slurm_gui/language.json."""
    load_language(lang)
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(_LANG_FILE, "w", encoding="utf-8") as f:
            json.dump({"lang": lang}, f)
    except Exception:
        # non-fatal
        pass



def system_default_language() -> str:
    """Return 'tr' if OS/UI locale looks Turkish, otherwise 'en'."""
    try:
        loc = (locale.getdefaultlocale() or (None, None))[0] or ""
        loc = loc.lower()
        if loc.startswith("tr"):
            return "tr"
    except Exception:
        pass
    return "en"

def load_saved_language(default: str = "tr") -> str:
    """Load persisted language if present; returns the language code used."""
    lang = default
    try:
        if _LANG_FILE.exists():
            data = json.load(open(_LANG_FILE, "r", encoding="utf-8"))
            if isinstance(data, dict) and data.get("lang") in ("tr", "en"):
                lang = data["lang"]
    except Exception:
        pass
    load_language(lang)
    return lang

def t(key: str) -> str:
    cur = _LANG
    try:
        for part in key.split("."):
            cur = cur[part]
        return cur if isinstance(cur, str) else f"[{key}]"
    except Exception:
        return f"[{key}]"


def _flatten_keys(d: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for k, v in (d or {}).items():
        if not isinstance(k, str):
            continue
        p = f"{prefix}{k}" if not prefix else f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= _flatten_keys(v, p)
        else:
            keys.add(p)
    return keys


def validate_language_files() -> None:
    """Log-only regression guard: detect missing i18n keys.

    Compares tr.json and en.json and logs missing keys. No UI.
    """
    try:
        import logging

        log = logging.getLogger("truba_gui.i18n")
        base = Path(__file__).resolve().parent.parent
        tr = json.load(open(base / "i18n" / "tr.json", "r", encoding="utf-8"))
        en = json.load(open(base / "i18n" / "en.json", "r", encoding="utf-8"))
        k_tr = _flatten_keys(tr)
        k_en = _flatten_keys(en)
        miss_in_en = sorted(k_tr - k_en)
        miss_in_tr = sorted(k_en - k_tr)
        if miss_in_en:
            log.warning(f"i18n key drift: missing in en.json: {len(miss_in_en)}")
            for k in miss_in_en[:50]:
                log.warning(f"  missing_en: {k}")
        if miss_in_tr:
            log.warning(f"i18n key drift: missing in tr.json: {len(miss_in_tr)}")
            for k in miss_in_tr[:50]:
                log.warning(f"  missing_tr: {k}")
    except Exception:
        pass
