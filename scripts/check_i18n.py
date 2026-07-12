from __future__ import annotations

import ast
import json
import re
from pathlib import Path


UI_METHODS = {
    "addAction",
    "addTab",
    "setAccessibleDescription",
    "setAccessibleName",
    "setDetailedText",
    "setHeaderLabels",
    "setInformativeText",
    "setLabelText",
    "setPlaceholderText",
    "setStatusTip",
    "setText",
    "setToolTip",
    "setWhatsThis",
    "setWindowTitle",
}
UI_CONSTRUCTORS = {
    "QAction",
    "QCheckBox",
    "QGroupBox",
    "QLabel",
    "QMenu",
    "QPushButton",
    "QRadioButton",
    "QToolButton",
}
MESSAGEBOX_METHODS = {"critical", "information", "question", "warning"}
FILE_DIALOG_METHODS = {"getExistingDirectory", "getOpenFileName", "getOpenFileNames", "getSaveFileName"}
I18N_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_messagebox_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "QMessageBox"
        and node.func.attr in MESSAGEBOX_METHODS
    )


def _literal_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value.strip()
        if text and any(ch.isalpha() for ch in text):
            return node.value
    return None


def _iter_literal_args(arg: ast.AST):
    if isinstance(arg, (ast.List, ast.Tuple)):
        yield from arg.elts
    else:
        yield arg


def find_hardcoded_ui_strings(src_root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        if any(part in {"i18n", "__pycache__"} for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            args: list[ast.AST] = []
            if name in UI_METHODS:
                args = node.args[:1]
            elif name in UI_CONSTRUCTORS:
                args = node.args[:1]
            elif _is_messagebox_call(node):
                args = node.args[1:3]
            elif name in FILE_DIALOG_METHODS:
                args = node.args[1:2]
            for arg in args:
                for item in _iter_literal_args(arg):
                    text = _literal_text(item)
                    if text is not None:
                        rel = path.relative_to(src_root.parent.parent)
                        findings.append(f"{rel}:{item.lineno}: {text!r}")
    return findings


def _is_translation_list_name(name: str) -> bool:
    upper = name.upper()
    return upper.endswith("_KEYS") or upper.endswith("_LABELS")


def _iter_string_literals(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node
    elif isinstance(node, (ast.List, ast.Tuple)):
        for item in node.elts:
            yield from _iter_string_literals(item)


def find_missing_translation_references(src_root: Path, catalog_keys: set[str]) -> list[str]:
    findings: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        if any(part in {"i18n", "__pycache__"} for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    key = arg.value
                    if key not in catalog_keys:
                        rel = path.relative_to(src_root.parent.parent)
                        findings.append(f"{rel}:{arg.lineno}: {key!r}")
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and _is_translation_list_name(target.id)
                for target in node.targets
            ):
                for item in _iter_string_literals(node.value):
                    key = item.value.strip()
                    if key == "---":
                        continue
                    if I18N_KEY_PATTERN.match(key) and key not in catalog_keys:
                        rel = path.relative_to(src_root.parent.parent)
                        findings.append(f"{rel}:{item.lineno}: {key!r}")
    return findings


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
    src_root = Path(__file__).resolve().parents[1] / "src" / "truba_gui"
    hardcoded = find_hardcoded_ui_strings(src_root)
    missing_refs = find_missing_translation_references(src_root, k_tr & k_en)
    if not miss_en and not miss_tr and not hardcoded and not missing_refs:
        print("i18n key check: OK")
        print("i18n reference check: OK")
        print("i18n hardcoded UI text check: OK")
        return 0
    print("i18n check: FAILED")
    if miss_en:
        print(f"Missing in en.json ({len(miss_en)}):")
        for k in miss_en:
            print("  -", k)
    if miss_tr:
        print(f"Missing in tr.json ({len(miss_tr)}):")
        for k in miss_tr:
            print("  -", k)
    if hardcoded:
        print(f"Hardcoded UI strings ({len(hardcoded)}):")
        for item in hardcoded:
            print("  -", item)
    if missing_refs:
        print(f"Missing i18n references ({len(missing_refs)}):")
        for item in missing_refs:
            print("  -", item)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
