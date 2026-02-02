from PySide6.QtWidgets import QMainWindow, QTabWidget
from PySide6.QtWidgets import QMenu, QToolButton, QWidget, QSizePolicy, QHBoxLayout
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QPolygonF
from PySide6.QtCore import Qt, QSize, QPointF
from PySide6.QtSvg import QSvgRenderer

from truba_gui.core.i18n import t, set_language
from .widgets.login_widget import LoginWidget
from .widgets.jobs_outputs_widget import JobsOutputsWidget
from .widgets.directories_widget import DirectoriesWidget
from .widgets.editor_widget import EditorWidget
from .widgets.logs_widget import LogsWidget
from .dialogs.help_dialog import HelpDialog


class MainWindow(QMainWindow):

    def _flag_icon(self, country_code: str) -> QIcon:
        """Return a small flag icon from packaged SVGs (stable on Windows)."""
        cc = (country_code or "").strip().lower()
        if cc == "en":
            cc = "gb"
        # Load SVG from: truba_gui/assets/flags/{cc}.svg
        try:
            from pathlib import Path
            base = Path(__file__).resolve().parent.parent  # ui -> truba_gui
            svg_path = base / "assets" / "flags" / f"{cc}.svg"
            if svg_path.exists():
                renderer = QSvgRenderer(str(svg_path))
                pm = QPixmap(18, 12)
                pm.fill(Qt.transparent)
                painter = QPainter(pm)
                renderer.render(painter)
                painter.end()
                return QIcon(pm)
        except Exception:
            pass

        # Fallback: simple colored badge (no text, no emoji)
        pm = QPixmap(18, 12)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor("#444" if cc != "tr" else "#E30A17"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(pm.rect().adjusted(0, 0, -1, -1), 2, 2)
        painter.end()
        return QIcon(pm)

    def __init__(self):
        super().__init__()
        self._shutdown_done = False
        self._init_language_menu()
        self.retranslate_ui()

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.login = LoginWidget()
        self.jobs_outputs = JobsOutputsWidget()
        self.directories = DirectoriesWidget()
        self.editor = EditorWidget()
        self.logs = LogsWidget()

        self.tabs.addTab(self.login, t("tabs.login"))
        self.tabs.addTab(self.jobs_outputs, t("tabs.jobs_outputs"))
        self.tabs.addTab(self.directories, t("tabs.directories"))
        self.tabs.addTab(self.editor, t("tabs.editor"))
        self.tabs.addTab(self.logs, t("tabs.logs") if t("tabs.logs") != "[tabs.logs]" else "Logs")

        self.login.session_changed.connect(self.on_session_changed)

        # Job completion monitor
        from PySide6.QtCore import QTimer
        self.job_timer = QTimer(self)
        self.job_timer.setInterval(5000)
        self.job_timer.timeout.connect(self._poll_jobs)
        self._last_job_ids = set()

        self.jobs_outputs.request_show_directories.connect(self.show_directories)
        self.directories.open_in_editor.connect(self.open_in_editor)

    def graceful_shutdown(self) -> None:
        """Graceful, idempotent shutdown sequence.

        This is called both from closeEvent and QApplication.aboutToQuit.
        It must never raise.
        """
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        try:
            # 1) Stop timers / background polling
            try:
                if hasattr(self, "job_timer") and self.job_timer:
                    self.job_timer.stop()
            except Exception:
                pass

            # 2) Stop live file watchers
            try:
                if hasattr(self, "jobs_outputs") and self.jobs_outputs and hasattr(self.jobs_outputs, "shutdown"):
                    self.jobs_outputs.shutdown()
            except Exception:
                pass

            # 3) Cancel in-flight file operations (best-effort)
            try:
                if hasattr(self, "directories") and self.directories and hasattr(self.directories, "shutdown"):
                    self.directories.shutdown()
            except Exception:
                pass

            # 4) External processes (VcXsrv / X11 ssh/plink)
            try:
                if hasattr(self, "login") and self.login and hasattr(self.login, "shutdown_external_processes"):
                    self.login.shutdown_external_processes()
            except Exception:
                pass

            # 5) Final marker for file log
            try:
                import logging

                logging.getLogger("truba_gui").info("graceful shutdown completed")
            except Exception:
                pass
        except Exception:
            pass

    
    def _asset_svg_icon(self, rel_path: str, w: int = 18, h: int = 18) -> QIcon:
        """Render an SVG asset into a QIcon (stable across platforms)."""
        try:
            from pathlib import Path
            base = Path(__file__).resolve().parent.parent  # ui -> truba_gui
            svg_path = base / rel_path
            if svg_path.exists():
                renderer = QSvgRenderer(str(svg_path))
                pm = QPixmap(w, h)
                pm.fill(Qt.transparent)
                painter = QPainter(pm)
                renderer.render(painter)
                painter.end()
                return QIcon(pm)
        except Exception:
            pass
        return QIcon()


    def _init_language_menu(self):
        """Top-right language selector (shows selected language with flag)."""
        menubar = self.menuBar()

        # Top-left Help button (always available)
        self._help_btn = QToolButton(self)
        self._help_btn.setAutoRaise(True)
        self._help_btn.setIcon(self._asset_svg_icon("assets/icons/help.svg", 18, 18))
        self._help_btn.setToolTip(t("help.help_title"))
        self._help_btn.clicked.connect(self._open_help)

        help_container = QWidget(self)
        help_container.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        h = QHBoxLayout(help_container)
        h.setContentsMargins(6, 0, 0, 0)
        h.addWidget(self._help_btn)
        menubar.setCornerWidget(help_container, Qt.TopLeftCorner)

        self._lang_menu = QMenu(self)

        # --- Language actions (icons + checkmark) ---
        self._act_tr = QAction(self)
        self._act_en = QAction(self)
        self._act_tr.setCheckable(True)
        self._act_en.setCheckable(True)

        self._act_tr.setIcon(self._flag_icon("TR"))
        self._act_en.setIcon(self._flag_icon("GB"))

        self._act_tr.triggered.connect(lambda: self._switch_language("tr"))
        self._act_en.triggered.connect(lambda: self._switch_language("en"))

        self._lang_menu.addAction(self._act_tr)
        self._lang_menu.addAction(self._act_en)

        # --- Top-right language selector (wide, shows selected language + flag) ---
        self._lang_btn = QToolButton(self)
        self._lang_btn.setPopupMode(QToolButton.InstantPopup)
        self._lang_btn.setMenu(self._lang_menu)
        self._lang_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._lang_btn.setIconSize(QSize(20, 14))
        self._lang_btn.setMinimumWidth(220)
        self._lang_btn.setStyleSheet(
            "QToolButton { padding: 4px 12px; text-align: left; }"
            "QToolButton::menu-indicator { subcontrol-position: right center; }"
        )

        # Put the button into a container so it doesn't get clipped by the cornerWidget geometry.
        lang_container = QWidget(self)
        lang_container.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout = QHBoxLayout(lang_container)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.addWidget(self._lang_btn)
        menubar.setCornerWidget(lang_container, Qt.TopRightCorner)


    def _open_help(self):
        try:
            dlg = HelpDialog(self)
            dlg.exec()
        except Exception:
            pass

    def _switch_language(self, lang: str):
        set_language(lang)
        self.retranslate_ui()

    def retranslate_ui(self):
        # Window + tabs
        self.setWindowTitle(t("app.title"))
        if hasattr(self, "tabs"):
            self.tabs.setTabText(self.tabs.indexOf(self.login), t("tabs.login"))
            self.tabs.setTabText(self.tabs.indexOf(self.jobs_outputs), t("tabs.jobs_outputs"))
            self.tabs.setTabText(self.tabs.indexOf(self.directories), t("tabs.directories"))
            self.tabs.setTabText(self.tabs.indexOf(self.editor), t("tabs.editor"))
            self.tabs.setTabText(self.tabs.indexOf(self.logs), t("tabs.logs"))

        # Language menu labels / selected language display
        if hasattr(self, "_act_tr"):
            self._act_tr.setText(t("language.turkish"))
        if hasattr(self, "_act_en"):
            self._act_en.setText(t("language.english"))

        # Button shows currently selected language (with flag) and is wide enough
        if hasattr(self, "_lang_btn"):
            cur = getattr(self, "_current_lang", None)
            if cur is None:
                from truba_gui.core.i18n import current_language as _cur_lang
                cur = _cur_lang()
            if cur == "tr":
                self._lang_btn.setIcon(self._flag_icon("TR"))
                self._lang_btn.setText(t("language.turkish"))
                if hasattr(self, "_act_tr"):
                    self._act_tr.setChecked(True)
                if hasattr(self, "_act_en"):
                    self._act_en.setChecked(False)
            else:
                self._lang_btn.setIcon(self._flag_icon("GB"))
                self._lang_btn.setText(t("language.english"))
                if hasattr(self, "_act_tr"):
                    self._act_tr.setChecked(False)
                if hasattr(self, "_act_en"):
                    self._act_en.setChecked(True)
            self._lang_btn.setToolTip(t("language.menu_title"))

        # Ask children to retranslate if they support it
        for w in (getattr(self, "login", None), getattr(self, "jobs_outputs", None), getattr(self, "directories", None),
                  getattr(self, "editor", None), getattr(self, "logs", None)):
            if w is not None and hasattr(w, "retranslate_ui"):
                try:
                    w.retranslate_ui()
                except Exception:
                    pass

    def on_session_changed(self, session):
        self.jobs_outputs.set_session(session)
        self.directories.set_session(session)
        self.editor.set_session(session)

    def show_directories(self):
        idx = self.tabs.indexOf(self.directories)
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)

    def open_in_editor(self, path: str, content: str):
        self.editor.open_file(path, content)
        idx = self.tabs.indexOf(self.editor)
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)

    def _poll_jobs(self):
        # Called every 5s when connected; logs finished jobs to login console
        session = getattr(self, "_session", None)
        if not session or not session.get("connected"):
            return
        ssh = session.get("ssh")
        cfg = session.get("cfg")
        if not ssh or not cfg:
            return
        try:
            # Get active job ids
            code, out, err = ssh.run(f'squeue -h -u {cfg.username} -o "%A"')
            job_ids = set([ln.strip() for ln in out.splitlines() if ln.strip().isdigit()])
        except Exception:
            return
        # detect finished
        finished = self._last_job_ids - job_ids
        for jid in sorted(finished):
            self.login.append_console(t("login.job_finished").format(jobid=jid))
        self._last_job_ids = job_ids

    def closeEvent(self, event):
        """Gracefully stop background helper processes on app exit.

        Controlled by Login settings:
        - close_vcxsrv_on_exit
        - close_x11_procs_on_exit
        """
        try:
            self.graceful_shutdown()
        except Exception:
            pass
        super().closeEvent(event)
