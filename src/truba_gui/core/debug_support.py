from __future__ import annotations

import locale
import platform
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from truba_gui.core.logging import get_logger


@dataclass(frozen=True)
class ErrorId:
    """Short user-facing error identifier for correlating UI errors with logs."""

    area: str
    token: str

    def __str__(self) -> str:
        return f"{self.area}-{self.token}"


def new_error_id(area: str) -> ErrorId:
    area = (area or "GEN").upper()
    token = uuid.uuid4().hex[:6].upper()
    return ErrorId(area=area, token=token)


def log_startup_snapshot() -> None:
    """Log a one-shot environment snapshot useful for field debugging."""

    log = get_logger("truba_gui.startup")
    try:
        from truba_gui import __version__
    except Exception:
        __version__ = "unknown"

    frozen = bool(getattr(sys, "frozen", False))
    py = sys.version.split()[0]
    os_name = platform.system()
    os_release = platform.release()
    os_ver = platform.version()
    arch = platform.machine()
    try:
        loc = locale.getdefaultlocale()
        loc_s = f"{loc[0] or ''} {loc[1] or ''}".strip()
    except Exception:
        loc_s = ""

    try:
        import PySide6

        qt_v = getattr(PySide6.QtCore, "__version__", "") if hasattr(PySide6, "QtCore") else ""
        pyside_v = getattr(PySide6, "__version__", "")
    except Exception:
        qt_v = ""
        pyside_v = ""

    log.info("=== App startup ===")
    log.info("app_version=%s", __version__)
    log.info("mode=%s", "standalone_exe" if frozen else "source")
    log.info("python=%s", py)
    log.info("os=%s %s", os_name, os_release)
    log.info("os_version=%s", os_ver)
    log.info("arch=%s", arch)
    if loc_s:
        log.info("locale=%s", loc_s)
    if pyside_v:
        log.info("pyside6=%s", pyside_v)
    if qt_v:
        log.info("qt=%s", qt_v)

    # External helpers (best-effort)
    try:
        from truba_gui.services.putty_manager import plink_path

        p = plink_path()
        log.info("plink_path=%s", p)
        log.info("plink_exists=%s", p.exists())
    except Exception:
        pass

    try:
        from truba_gui.services.xserver_manager import vcxsrv_executable_path

        x = vcxsrv_executable_path()
        log.info("vcxsrv_path=%s", x)
        log.info("vcxsrv_exists=%s", bool(x) and x.exists())
    except Exception:
        pass


def log_exception_with_id(area: str, exc: BaseException, *, logger_name: str = "truba_gui") -> ErrorId:
    """Log an exception and return a stable error id to show the user."""

    err_id = new_error_id(area)
    log = get_logger(logger_name)
    # Use .exception to include traceback.
    log.exception("Error-ID=%s", str(err_id), exc_info=exc)
    return err_id


def timed() -> float:
    """Monotonic timer helper."""
    return time.monotonic()
