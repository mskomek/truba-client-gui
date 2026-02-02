from __future__ import annotations

"""PuTTY tooling bootstrap (standalone).

Goal
----
TrubaGUI must be able to run X11 forwarding on Windows *without* requiring the
user to install PuTTY/MobaXterm. For password-based SSH, Windows OpenSSH is not
practical from a GUI (no TTY), so we rely on **plink.exe**.

This module ensures a usable plink.exe exists under:
    ~/.truba_slurm_gui/third_party/putty/plink.exe

We download a single executable on demand (first use).
"""

import platform
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from truba_gui.core.i18n import t


PUTTY_PLINK_URL = "https://the.earth.li/~sgtatham/putty/latest/w64/plink.exe"


from truba_gui.core.paths import third_party_dir


def _project_root() -> Path:
    # Kept for backward compatibility (no longer used for file paths).
    return Path(__file__).resolve().parents[1]


def _log(log: Optional[Callable[[str], None]], msg: str) -> None:
    if log:
        log(msg)


def plink_path() -> Path:
    return third_party_dir() / "putty" / "plink.exe"


def _download(url: str, dest: Path, log: Optional[Callable[[str], None]] = None, parent=None) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)

    progress = None
    canceled = False
    try:
        if parent is not None:
            from PySide6.QtWidgets import QProgressDialog
            from PySide6.QtCore import Qt

            progress = QProgressDialog(t("putty.downloading"), t("common.cancel"), 0, 100, parent)
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
            _log(log, t("putty.download_cancelled"))
            return False

        if progress is not None:
            progress.setValue(100)
        return True
    except Exception as e:
        _log(log, t("putty.download_error").format(err=e))
        return False
    finally:
        if progress is not None:
            progress.close()



def _prompt_download_plink(parent) -> bool:
    """Ask user permission before downloading plink.exe."""
    try:
        from PySide6.QtWidgets import QMessageBox
    except Exception:
        return False

    msg = t("putty.needed_msg").format(url=PUTTY_PLINK_URL)
    ret = QMessageBox.question(
        parent,
        t("putty.needed_title"),
        msg,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return ret == QMessageBox.StandardButton.Yes


def ensure_plink_available(*, log: Optional[Callable[[str], None]] = None, parent=None) -> bool:
    """Ensure plink.exe exists (Windows only)."""

    if platform.system().lower() != "windows":
        return False

    dest = plink_path()
    if dest.exists():
        return True

    _log(log, t("putty.missing_log").format(url=PUTTY_PLINK_URL))

    if parent is None:
        _log(log, t("putty.parent_none_log"))
        return False

    if not _prompt_download_plink(parent):
        _log(log, t("putty.download_cancelled"))
        return False

    _log(log, t("putty.downloading_log").format(url=PUTTY_PLINK_URL))
    ok = _download(PUTTY_PLINK_URL, dest, log=log, parent=parent)
    if ok and dest.exists():
        _log(log, t("putty.ready_log").format(path=dest))
        return True
    return False
