from __future__ import annotations

import json
import sys
from pathlib import Path


def flatten_keys(d: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for k, v in (d or {}).items():
        if not isinstance(k, str):
            continue
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out |= flatten_keys(v, p)
        else:
            out.add(p)
    return out


def main() -> int:
    base = Path(__file__).resolve().parents[1] / "src" / "truba_gui" / "i18n"
    tr = json.loads((base / "tr.json").read_text(encoding="utf-8"))
    en = json.loads((base / "en.json").read_text(encoding="utf-8"))
    k_tr = flatten_keys(tr)
    k_en = flatten_keys(en)
    miss_en = sorted(k_tr - k_en)
    miss_tr = sorted(k_en - k_tr)
    if not miss_en and not miss_tr:
        print("i18n key check: OK")
        return 0
    print("i18n key check: FAILED")
    if miss_en:
        print(f"Missing in en.json ({len(miss_en)}):")
        for k in miss_en:
            print("  -", k)
    if miss_tr:
        print(f"Missing in tr.json ({len(miss_tr)}):")
        for k in miss_tr:
            print("  -", k)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
