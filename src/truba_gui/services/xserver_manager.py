from __future__ import annotations

import os
import platform
import socket
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

from truba_gui.services.vcxsrv_release_downloader import get_latest_vcxsrv_asset

# Standalone goals:
# - No PuTTY/MobaXterm required (we download plink/vcxsrv with explicit user consent elsewhere).
# - For plink -X to work reliably on Windows, local X server must listen on TCP 127.0.0.1:6000 (DISPLAY :0).
# - VcXsrv must be SINGLE instance; starting a second one often exits immediately with "another window manager".

_LOCK_PATH = Path.home() / ".truba_slurm_gui" / "vcxsrv_start.lock"
_LAST_START_TS = 0.0
_PID_PATH = Path.home() / ".truba_slurm_gui" / "vcxsrv_pid.txt"


def stop_x_server_started_by_app(log: Optional[Callable[[str], None]] = None) -> bool:
    """Stop VcXsrv if it was started by TrubaGUI.

    We record the PID when we start VcXsrv. If the user runs their own
    X server, we do not attempt to kill it.
    """
    if not _is_windows():
        return False

    try:
        if not _PID_PATH.exists():
            return False
        pid_s = (_PID_PATH.read_text(encoding="utf-8", errors="ignore") or "").strip()
        pid = int(pid_s)
    except Exception:
        return False

    try:
        _log(log, f"VcXsrv kapatılıyor (pid={pid})")
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    finally:
        try:
            _PID_PATH.unlink(missing_ok=True)
        except Exception:
            pass


def _log(log: Optional[Callable[[str], None]], msg: str) -> None:
    if log:
        log(msg)


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except Exception:
        return False


def _is_display_listening(display: int = 0) -> bool:
    return _is_port_open("127.0.0.1", 6000 + int(display))


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]  # .../truba_gui


def _vcxsrv_dir() -> Path:
    return _project_root() / "third_party" / "vcxsrv"


def _find_xserver_exe(vc_dir: Path) -> Optional[Path]:
    candidates = [
        vc_dir / "runtime" / "vcxsrv.exe",
        vc_dir / "runtime" / "XWin.exe",
        vc_dir / "vcxsrv.exe",
        vc_dir / "XWin.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    # recursive fallback
    for folder in (vc_dir / "runtime", vc_dir):
        if folder.exists():
            try:
                for p in folder.rglob("vcxsrv.exe"):
                    return p
                for p in folder.rglob("XWin.exe"):
                    return p
            except Exception:
                pass
    return None


@contextmanager
def _file_lock(path: Path, timeout_s: float = 6.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    fd = None
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            break
        except FileExistsError:
            if time.time() - t0 > timeout_s:
                raise TimeoutError("vcxsrv start lock timeout")
            time.sleep(0.1)
    try:
        yield
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def _download_file(url: str, dest: Path, log: Optional[Callable[[str], None]] = None, parent=None) -> bool:
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

        req = urllib.request.Request(url, headers={"User-Agent": "TrubaGUI/1.0"}, method="GET")
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
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        cmd = [str(installer), "/S", f"/D={str(target_dir)}"]
        _log(log, f"VcXsrv kurulumu başlatılıyor (sessiz): {cmd[0]}")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
        if proc.returncode != 0:
            _log(log, f"VcXsrv kurulum hatası (rc={proc.returncode}). STDERR: {proc.stderr.strip()}")
            return False
        return True
    except Exception as e:
        _log(log, f"VcXsrv kurulum exception: {e}")
        return False


def _prompt_install(parent, log: Optional[Callable[[str], None]] = None) -> bool:
    from PySide6.QtWidgets import QMessageBox

    asset = get_latest_vcxsrv_asset()
    if not asset or not asset.download_url:
        _log(log, "VcXsrv release bilgisi alınamadı. İnternet bağlantısını kontrol et.")
        QMessageBox.warning(parent, "VcXsrv", "VcXsrv sürümü bulunamadı. İnternet bağlantısını kontrol edin.")
        return False

    msg = (
        "X11 penceresi açmak için Windows'ta bir X Server gerekir.\n\n"
        f"İndirilecek dosya:\n  {asset.name}  ({asset.size/1024/1024:.1f} MB)\n"
        "Kaynak: GitHub Releases (marchaesen/vcxsrv)\n\n"
        "İndirip kurulsun mu?"
    )
    ret = QMessageBox.question(parent, "VcXsrv gerekli", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if ret != QMessageBox.StandardButton.Yes:
        return False

    vc_dir = _vcxsrv_dir()
    download_dir = Path.home() / ".truba_slurm_gui" / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    installer_path = download_dir / asset.name

    _log(log, f"VcXsrv indiriliyor: {asset.download_url}")
    if not _download_file(asset.download_url, installer_path, log=log, parent=parent):
        return False

    runtime_dir = vc_dir / "runtime"
    if not _run_noadmin_installer(installer_path, runtime_dir, log=log):
        return False

    xexe = _find_xserver_exe(vc_dir)
    if not xexe:
        _log(log, "Kurulum bitti ama vcxsrv.exe/XWin.exe bulunamadı.")
        QMessageBox.warning(parent, "VcXsrv", "Kurulum tamamlandı ancak vcxsrv.exe/XWin.exe bulunamadı.")
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
    """Return True only if 127.0.0.1:6000 is listening (required for plink -X)."""

    if not _is_windows():
        return False

    # Already good
    if _is_display_listening(display):
        return True

    # Cooldown: avoid start-loop / popup spam
    global _LAST_START_TS
    if time.time() - _LAST_START_TS < 8.0:
        for _ in range(80):  # wait up to 8s for someone else to finish starting
            if _is_display_listening(display):
                return True
            time.sleep(0.1)
        return _is_display_listening(display)

    vc_dir = _vcxsrv_dir()
    xexe = _find_xserver_exe(vc_dir)

    if not xexe:
        _log(log, "Yerel X server bulunamadı (vcxsrv.exe/XWin.exe).")
        if allow_download and parent is not None:
            if _prompt_install(parent, log=log):
                xexe = _find_xserver_exe(vc_dir)

    if not xexe:
        _log(log, "VcXsrv yok. İndirme için kullanıcı onayı gerekiyor.")
        return False

    # Single instance: cross-process lock
    try:
        with _file_lock(_LOCK_PATH, timeout_s=6.0):
            # Someone else might have started it while we waited
            if _is_display_listening(display):
                return True

            # Start VcXsrv with TCP listening (plink requirement).
            # Keep args minimal & stable; invalid args cause help popup (and no server).
            args = [
                str(xexe),
                f":{display}",
                "-multiwindow",
                "-ac",
                "-noreset",
                "-notrayicon",
                "-listen",
                "tcp",
            ]

            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            log_dir = Path.home() / ".truba_slurm_gui"
            log_dir.mkdir(parents=True, exist_ok=True)
            stdout_path = log_dir / "vcxsrv_stdout.log"
            stderr_path = log_dir / "vcxsrv_stderr.log"
            stdout_f = open(stdout_path, "ab", buffering=0)
            stderr_f = open(stderr_path, "ab", buffering=0)

            proc = subprocess.Popen(
                args,
                cwd=str(xexe.parent),
                stdout=stdout_f,
                stderr=stderr_f,
                stdin=subprocess.DEVNULL,
                close_fds=False,
                creationflags=creationflags,
            )

            _LAST_START_TS = time.time()
            _log(log, f"VcXsrv başlatılıyor: {xexe.name} (pid={proc.pid})")
            try:
                _PID_PATH.parent.mkdir(parents=True, exist_ok=True)
                _PID_PATH.write_text(str(proc.pid), encoding="utf-8")
            except Exception:
                # PID recording is best-effort
                pass

            # Wait for TCP 6000
            for _ in range(60):  # 6s
                if _is_display_listening(display):
                    _log(log, "VcXsrv hazır: 127.0.0.1:6000 dinliyor.")
                    return True
                if proc.poll() is not None:
                    _log(
                        log,
                        "X11: VcXsrv başlatıldı ama hemen kapandı.\n"
                        "Detay: C:\\Users\\<user>\\.truba_slurm_gui\\vcxsrv_stderr.log"
                    )
                    return False
                time.sleep(0.1)

            _log(
                log,
                "X11: VcXsrv çalışıyor görünüyor ama 127.0.0.1:6000 açılmadı.\n"
                "Windows Firewall engelliyor olabilir (ilk çalıştırmada izin verin).\n"
                "Detay: C:\\Users\\<user>\\.truba_slurm_gui\\vcxsrv_stderr.log"
            )
            return False

    except TimeoutError:
        _log(log, "X11: VcXsrv start lock timeout (başka bir instance olabilir).")
        return False
