import sys
import logging
from PySide6.QtWidgets import QApplication

from truba_gui.core.i18n import load_saved_language, system_default_language
from truba_gui.core.i18n import validate_language_files
from truba_gui.core.logging_setup import setup_logging, install_excepthook
from truba_gui.core.debug_support import log_startup_snapshot
from truba_gui.ui.main_window import MainWindow
from truba_gui.config.storage import get_ui_pref_bool, set_ui_pref_bool
from truba_gui.ui.dialogs.welcome_dialog import WelcomeDialog


def _bootstrap_safety_checks() -> None:
    """Best-effort startup guards.

    - Detect i18n key drift (logs only)
    - Cleanup stale/orphan external process records (logs only)
    """
    try:
        validate_language_files()
    except Exception:
        pass
    try:
        from truba_gui.services.process_registry import cleanup_orphans

        # Conservative orphan guard: kills only TrubaGUI-recorded helpers older than 2h.
        cleanup_orphans(aggressive=True)
    except Exception:
        pass

def main() -> int:
    app = QApplication(sys.argv)

    # Logging (file-backed, rotating). Must not crash the GUI.
    setup_logging(level=logging.INFO)
    install_excepthook()
    try:
        log_startup_snapshot()
    except Exception:
        pass

    _bootstrap_safety_checks()

    # Slightly darker neutral background for the whole app (without affecting input widgets).
    app.setStyleSheet(
        """
        QMainWindow { background-color: #f0f0f0; }
        QTabWidget::pane { background-color: #f0f0f0; }
        """
    )

    load_saved_language(system_default_language())

    w = MainWindow()
    # Crash-safe shutdown: ensure cleanup runs even if window closeEvent is skipped.
    try:
        app.aboutToQuit.connect(w.graceful_shutdown)
    except Exception:
        pass
    w.show()

    # First-run welcome / guide (user can disable permanently)
    try:
        if get_ui_pref_bool("show_welcome", True):
            dlg = WelcomeDialog(w)
            dlg.exec()
            if dlg.dont_show_again_checked():
                set_ui_pref_bool("show_welcome", False)
    except Exception:
        pass

    return app.exec()
