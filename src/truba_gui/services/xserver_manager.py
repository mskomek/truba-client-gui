from __future__ import annotations

import os
import platform
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from truba_gui.services.vcxsrv_release_downloader import get_latest_vcxsrv_asset

# --- Runtime state to avoid starting multiple VcXsrv instances at once
_XSERVER_STARTING = False
_XSERVER_STARTING_SINCE = 0.0

def _is_xserver_process_running() -> bool:
    """
    Windows üzerinde bilinen X server process'leri çalışıyor mu?
    """
    try:
        out = subprocess.check_output(
            ["tasklist"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True,
            errors="ignore"
        ).lower()
    except Exception:
        return False

    for name in (
        "xwin.exe",       # VcXsrv
        "vcxsrv.exe",
        "xming.exe",
        "mobaxterm.exe",
        "x410.exe"
    ):
        if name in out:
            return True
    return False

def _is_display_listening(display: int = 0) -> bool:
    """Check whether an X server is listening on TCP 6000 + display."""
    port = 6000 + int(display)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except Exception:
        return False


def _project_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[1]  # .../truba_gui


def _bundled_vcxsrv_dir() -> Path:
    root = _project_root()
    return root / "third_party" / "vcxsrv"



def _log(log: Optional[Callable[[str], None]], msg: str) -> None:
    if log:
        log(msg)


def _download_file(url: str, dest: Path, log: Optional[Callable[[str], None]] = None, parent=None) -> bool:
    """Download url to dest. If parent (Qt widget) is provided, show progress dialog."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    progress = None
    canceled = False
    try:
        if parent is not None:
            from PySide6.QtWidgets import QProgressDialog
            from PySide6.QtCore import Qt

            progress = QProgressDialog("VcXsrv indiriliyor...", "İptal", 0, 100, parent)
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "TrubaGUI/1.0 (+https://github.com/)"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            chunk = 1024 * 128
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    if progress is not None and progress.wasCanceled():
                        canceled = True
                        break
                    data = resp.read(chunk)
                    if not data:
                        break
                    f.write(data)
                    downloaded += len(data)
                    if total > 0 and progress is not None:
                        progress.setValue(min(100, int(downloaded * 100 / total)))
        if canceled:
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass
            _log(log, "İndirme iptal edildi.")
            return False

        if progress is not None:
            progress.setValue(100)
        return True
    except Exception as e:
        _log(log, f"İndirme hatası: {e}")
        return False
    finally:
        if progress is not None:
            progress.close()


def _run_noadmin_installer(installer: Path, target_dir: Path, log: Optional[Callable[[str], None]] = None) -> bool:
    """
    Run VcXsrv NSIS installer in silent mode into target_dir.

    Many VcXsrv releases ship an NSIS installer; /S is the standard silent switch.
    /D=... is NSIS' target directory override and must be the last argument.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        cmd = [str(installer), "/S", f"/D={str(target_dir)}"]
        _log(log, f"VcXsrv kurulumu başlatılıyor (sessiz): {cmd[0]}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            _log(log, f"VcXsrv kurulum hatası (rc={proc.returncode}). STDERR: {proc.stderr.strip()}")
            return False
        return True
    except Exception as e:
        _log(log, f"VcXsrv kurulum exception: {e}")
        return False


def _find_xwin_under(folder: Path) -> Optional[Path]:
    """Search recursively for XWin.exe under folder."""
    try:
        for p in folder.rglob("XWin.exe"):
            return p
    except Exception:
        return None
    return None


def _find_vcxsrv_under(folder: Path) -> Optional[Path]:
    """Search recursively for vcxsrv.exe under folder."""
    try:
        for p in folder.rglob("vcxsrv.exe"):
            return p
    except Exception:
        return None
    return None


def _find_xserver_exe(vc_dir: Path) -> Optional[Path]:
    """Find an X server executable (VcXsrv) in known locations.

    Prefer portable/bundled binaries under third_party/vcxsrv.
    """
    candidates = [
        vc_dir / "vcxsrv.exe",
        vc_dir / "XWin.exe",
        vc_dir / "runtime" / "vcxsrv.exe",
        vc_dir / "runtime" / "XWin.exe",
    ]
    for c in candidates:
        if c.exists():
            return c

    # If an installer placed files under runtime, try recursive search.
    for folder in [vc_dir / "runtime", vc_dir]:
        if folder.exists():
            p = _find_vcxsrv_under(folder) or _find_xwin_under(folder)
            if p:
                return p

    # Common system install locations
    for root in [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ]:
        for name in ["VcXsrv", "VcxSrv", "vcxsrv"]:
            base = root / name
            p = _find_vcxsrv_under(base) or _find_xwin_under(base)
            if p:
                return p
    return None



def _prompt_install(parent, log: Optional[Callable[[str], None]] = None) -> bool:
    """Ask user to download and install VcXsrv from GitHub releases."""
    try:
        from PySide6.QtWidgets import QMessageBox
    except Exception:
        _log(log, "PySide6 bulunamadı; indirme penceresi açılamıyor.")
        return False

    asset = get_latest_vcxsrv_asset()
    if not asset or not asset.download_url:
        _log(log, "VcXsrv release bilgisi alınamadı. İnternet bağlantısını kontrol et.")
        QMessageBox.warning(parent, "VcXsrv", "VcXsrv sürümü bulunamadı (GitHub API). İnternet bağlantısını kontrol edin.")
        return False

    msg = (
        "X11 penceresi açmak için Windows'ta bir X Server gerekir.\n\n"
        f"VcXsrv indirilsin ve kurulsun mu?\n\n"
        f"Sürüm etiketi: {asset.tag}\n"
        f"Dosya: {asset.name} ({asset.size/1024/1024:.1f} MB)\n\n"
        "Not: Bu işlem GitHub Releases üzerinden indirme yapar."
    )
    ret = QMessageBox.question(parent, "VcXsrv gerekli", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if ret != QMessageBox.StandardButton.Yes:
        return False

    root = _project_root()
    vc_dir = root / "third_party" / "vcxsrv"
    download_dir = Path.home() / ".truba_slurm_gui" / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    installer_path = download_dir / asset.name

    _log(log, f"VcXsrv indiriliyor: {asset.download_url}")
    if not _download_file(asset.download_url, installer_path, log=log, parent=parent):
        return False

    # install into project third_party/vcxsrv/runtime to keep things self-contained
    runtime_dir = vc_dir / "runtime"
    if not _run_noadmin_installer(installer_path, runtime_dir, log=log):
        return False

    xexe = _find_xserver_exe(vc_dir)
    if not xexe:
        _log(log, "Kurulum bitti ama VcXsrv çalıştırılabilir dosyası bulunamadı (vcxsrv.exe/XWin.exe).")
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(parent, "VcXsrv", "Kurulum tamamlandı ancak vcxsrv.exe/XWin.exe bulunamadı.")
        except Exception:
            pass
        return False

    _log(log, f"VcXsrv hazır: {xexe}")
    return True



def ensure_x_server_running(
    log: Optional[Callable[[str], None]] = None,
    *,
    display: int = 0,
    parent=None,
    allow_download: bool = True,
) -> bool:
    """Ensure a local X server exists on Windows for X11 forwarding.

    Returns True if an X server is listening (after any attempt), else False.

    Behavior:
    - If already listening on 127.0.0.1:6000 (display :0), return True.
    - On Windows, try to start bundled VcXsrv at:
        src/truba_gui/third_party/vcxsrv/XWin.exe
    - If missing and allow_download=True, prompt user to download VcXsrv from GitHub releases.
    """
    # If something is already listening on :0, or an X server process is already running,
    # reuse it. Starting a second instance causes "another window manager is running".
    if _is_display_listening(display) or _is_xserver_process_running():
        return True

    # Prevent races: if another call is already starting VcXsrv, wait briefly and reuse it.
    global _XSERVER_STARTING, _XSERVER_STARTING_SINCE
    if _XSERVER_STARTING:
        t0 = time.time()
        while time.time() - t0 < 3.0:
            if _is_display_listening(display) or _is_xserver_process_running():
                return True
            time.sleep(0.05)
        return _is_display_listening(display)

    if platform.system().lower() != "windows":
        return False

    vc_dir = _bundled_vcxsrv_dir()
    xexe = _find_xserver_exe(vc_dir)
    if not xexe:
        _log(log, "Yerel X server bulunamadı (vcxsrv.exe/XWin.exe).")
        if allow_download and parent is not None:
            ok = _prompt_install(parent, log=log)
            if ok:
                xexe = _find_xserver_exe(vc_dir)

    if not xexe:
        _log(log, "VcXsrv hâlâ yok. third_party/vcxsrv içine vcxsrv.exe veya XWin.exe ekleyin ya da indirmeye izin verin.")
        return False

    _XSERVER_STARTING = True
    _XSERVER_STARTING_SINCE = time.time()

    try:
        args = [
            str(xexe),
            f":{display}",
            "-multiwindow",
            "-clipboard",
            "-ac",
        ]
        creationflags = 0
        if platform.system().lower() == "windows" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        log_dir = Path.home() / ".truba_slurm_gui"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "vcxsrv_stdout.log"
        stderr_path = log_dir / "vcxsrv_stderr.log"
        stdout_f = open(stdout_path, "ab", buffering=0)
        stderr_f = open(stderr_path, "ab", buffering=0)

        subprocess.Popen(
            args,
            cwd=str(xexe.parent),
            stdout=stdout_f,
            stderr=stderr_f,
            stdin=subprocess.DEVNULL,
            close_fds=False,
            creationflags=creationflags,
        )
        _log(log, f"VcXsrv başlatıldı: {xexe.name} (cwd={xexe.parent})")
    except Exception as e:
        _XSERVER_STARTING = False
        _log(log, f"X server başlatılamadı: {e}")
        return False

    # Startup can take a moment on first run; wait until :{display} is listening.
    t0 = time.time()
    while time.time() - t0 < 3.0:
        if _is_display_listening(display) or _is_xserver_process_running():
            _XSERVER_STARTING = False
            return True
        time.sleep(0.05)
    _XSERVER_STARTING = False
    return _is_display_listening(display)
