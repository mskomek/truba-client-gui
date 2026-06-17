# -*- mode: python ; coding: utf-8 -*-
# build/windows/truba-client-gui.spec

from __future__ import annotations
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

# PyInstaller provides SPECPATH in spec execution namespace.
SPEC_PATH = Path(globals().get("SPECPATH", "")).resolve()
if not SPEC_PATH.is_file():
    SPEC_PATH = (Path.cwd() / "build" / "windows" / "truba-client-gui.spec").resolve()

SPEC_DIR = SPEC_PATH.parent  # .../<repo>/build/windows

# Find repo root by walking upwards until "src" folder exists
REPO_ROOT = SPEC_DIR
while REPO_ROOT != REPO_ROOT.parent and not (REPO_ROOT / "src").is_dir():
    REPO_ROOT = REPO_ROOT.parent
if not (REPO_ROOT / "src").is_dir():
    raise SystemExit(f"[spec] Could not locate repo root from {SPEC_DIR}")

SRC_DIR = REPO_ROOT / "src"
ENTRY_SCRIPT = SRC_DIR / "truba_gui" / "__main__.py"

ASSETS_DIR = SRC_DIR / "truba_gui" / "assets"
I18N_DIR   = SRC_DIR / "truba_gui" / "i18n"
DOCS_DIR   = SRC_DIR / "truba_gui" / "docs"

ICON_PATH = SPEC_DIR / "truba-client-gui.ico"
VERSION_FILE = SPEC_DIR / "version_info.txt"

# -----------------------------
# Build toggles
# -----------------------------
ONEFILE = False          # <<< TEK DOSYA İÇİN TRUE
ENABLE_UPX = False      # Kurumsal ortam için False önerilir

if not ENTRY_SCRIPT.exists():
    raise SystemExit(f"[spec] ENTRY_SCRIPT not found: {ENTRY_SCRIPT}")

block_cipher = None

datas = []
if ASSETS_DIR.exists():
    datas.append((str(ASSETS_DIR), "truba_gui/assets"))
if I18N_DIR.exists():
    datas.append((str(I18N_DIR), "truba_gui/i18n"))
if DOCS_DIR.exists():
    datas.append((str(DOCS_DIR), "truba_gui/docs"))

hiddenimports = sorted(
    {
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtSvg",
        "PySide6.QtWidgets",
        "shiboken6",
        "shiboken6.Shiboken",
    }
)

binaries = collect_dynamic_libs("shiboken6")

excludes = [
    "PySide6.scripts.deploy_lib",
    "_truba_gui_perf_probe",
]

a = Analysis(
    [str(ENTRY_SCRIPT)],
    pathex=[str(REPO_ROOT), str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if ONEFILE:
    # -----------------------------
    # ONEFILE: tek exe
    # -----------------------------
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="truba-client-gui",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=ENABLE_UPX,
        upx_exclude=[],
        console=False,
        icon=str(ICON_PATH) if ICON_PATH.exists() else None,
        version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
    )
else:
    # -----------------------------
    # ONEDIR: klasörlü dağıtım
    # -----------------------------
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="truba-client-gui",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=ENABLE_UPX,
        upx_exclude=[],
        console=False,
        icon=str(ICON_PATH) if ICON_PATH.exists() else None,
        version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=ENABLE_UPX,
        upx_exclude=[],
        name="truba-client-gui",
    )
