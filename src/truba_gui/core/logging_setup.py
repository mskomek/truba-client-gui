from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from truba_gui.core.logging import log_path


def setup_logging(level: int = logging.INFO) -> None:
    """Configure a rotating file logger.

    - Never raises (must not crash the GUI)
    - Single file: ~/.truba_slurm_gui/app.log
    """
    try:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)

        root = logging.getLogger("truba_gui")
        root.setLevel(level)

        # Avoid duplicating handlers on restart (e.g. interactive reload)
        if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            return

        fmt = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        fh = RotatingFileHandler(
            p,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        fh.setLevel(level)
        root.addHandler(fh)

        # Also capture warnings and reduce silent failures
        logging.captureWarnings(True)

    except Exception:
        # Never crash the GUI because of logging.
        pass


def install_excepthook() -> None:
    """Log uncaught exceptions to the app log."""

    def _hook(exc_type, exc, tb):
        try:
            logging.getLogger("truba_gui").exception("Uncaught exception", exc_info=(exc_type, exc, tb))
        except Exception:
            pass
        # Keep default behavior (prints to stderr)
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _hook
