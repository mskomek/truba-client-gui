import webbrowser

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QProgressDialog, QSystemTrayIcon,
    QTabWidget
)
from PySide6.QtWidgets import (
    QMenu, QToolButton, QWidget, QSizePolicy, QHBoxLayout, QLabel
)
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import QObject, QThread, QThreadPool, QTimer, Qt, QSize, Signal, Slot
from PySide6.QtSvg import QSvgRenderer

from truba_gui import __version__
from truba_gui.core.paths import is_frozen_exe
from truba_gui.core.i18n import t, set_language
from truba_gui.services.app_updater import (
    download_and_verify_release,
    get_latest_release,
    is_newer_version,
    launch_update_installer,
)
from .widgets.login_widget import LoginWidget
from .widgets.jobs_outputs_widget import JobsOutputsWidget
from .widgets.directories_widget import DirectoriesWidget
from .widgets.ftp_widget import FtpWidget
from .widgets.editor_widget import EditorWidget
from .widgets.logs_widget import LogsWidget
from .dialogs.help_dialog import HelpDialog
from .dialogs.settings_dialog import SettingsDialog
from .dialogs.quick_tour import QuickTourOverlay
from .async_call import AsyncCall


class _BackgroundCall(QObject):
    finished = Signal(object)
    failed = Signal(str)
    done = Signal()
    progress = Signal(int, str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self._fn(self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.done.emit()


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
        self._update_jobs: set[QThread] = set()
        self._update_workers: dict[QThread, _BackgroundCall] = {}
        self._update_busy_count = 0
        self._update_progress: QProgressDialog | None = None
        self._update_manual = False
        self._update_interactive = False
        self._job_poll_worker: AsyncCall | None = None
        self._job_poll_generation = 0
        self._init_language_menu()
        self.retranslate_ui()

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.login = LoginWidget()
        self.jobs_outputs = JobsOutputsWidget()
        self.directories = DirectoriesWidget()
        self.ftp = FtpWidget()
        self.editor = EditorWidget()
        self.logs = LogsWidget()

        self.tabs.addTab(self.login, t("tabs.login"))
        self.tabs.addTab(self.jobs_outputs, t("tabs.jobs_outputs"))
        self.tabs.addTab(self.directories, t("tabs.directories"))
        self.tabs.addTab(
            self.ftp,
            t("tabs.ftp") if t("tabs.ftp") != "[tabs.ftp]" else "FTP",
        )
        self.tabs.addTab(self.editor, t("tabs.editor"))
        self.tabs.addTab(self.logs, t("tabs.logs") if t("tabs.logs") != "[tabs.logs]" else "Logs")
        self.tabs.currentChanged.connect(self._sync_command_polling)
        self.jobs_outputs.polling_visibility_changed.connect(
            self._sync_command_polling
        )

        self.login.session_changed.connect(self.on_session_changed)
        self.ftp.defaultPathsRequested.connect(
            self.login.update_active_profile_remote_defaults
        )

        # Job completion monitor
        self.job_timer = QTimer(self)
        self.job_timer.setInterval(15000)
        self.job_timer.timeout.connect(self._poll_jobs)
        self._last_job_ids = set()
        self._job_monitor_initialized = False
        self._job_tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._job_tray = QSystemTrayIcon(self)
            tray_icon = self.windowIcon()
            if tray_icon.isNull():
                tray_icon = QApplication.windowIcon()
            self._job_tray.setIcon(tray_icon)
            self._job_tray.show()
        self._sync_command_polling()

        self.jobs_outputs.request_show_directories.connect(self.show_directories)
        self.directories.open_in_editor.connect(self.open_in_editor)
        self.directories.script_submitted.connect(self.on_script_submitted)
        self.ftp.openFileRequested.connect(self.directories.on_open_file)
        self.ftp.submitRequested.connect(self.directories.submit_script)
        self.editor.script_submitted.connect(self.on_script_submitted)
        QTimer.singleShot(1500, lambda: self._check_for_updates(manual=False))

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
                self._job_poll_generation += 1
                self._job_poll_worker = None
                if getattr(self, "_job_tray", None):
                    self._job_tray.hide()
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
                if hasattr(self, "ftp") and self.ftp and hasattr(self.ftp, "shutdown"):
                    self.ftp.shutdown()
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

    def _init_language_menu(self):
        """Top-right settings, help, and language controls."""
        menubar = self.menuBar()

        self._help_menu = menubar.addMenu(t("help.help_title"))
        self._act_help_center = QAction(t("help.open_help"), self)
        self._act_help_center.triggered.connect(self._open_help)
        self._help_menu.addAction(self._act_help_center)

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

        self._help_btn = QToolButton(self)
        self._help_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._help_btn.setIcon(self._asset_svg_icon("assets/icons/help.svg", 18, 18))
        self._help_btn.setAutoRaise(False)
        self._help_btn.clicked.connect(self._open_help)

        self._settings_btn = QToolButton(self)
        self._settings_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._settings_btn.setAutoRaise(False)
        self._settings_btn.setMinimumWidth(88)
        self._settings_btn.clicked.connect(self._open_settings)

        self._update_btn = QToolButton(self)
        self._update_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._update_btn.setAutoRaise(False)
        self._update_btn.setMinimumWidth(100)
        self._update_btn.clicked.connect(
            lambda: self._check_for_updates(manual=True)
        )

        # Put the button into a container so it doesn't get clipped by the cornerWidget geometry.
        lang_container = QWidget(self)
        lang_container.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout = QHBoxLayout(lang_container)
        layout.setContentsMargins(0, 0, 6, 0)
        self._version_label = QLabel(f"v{__version__}", lang_container)
        self._version_label.setStyleSheet(
            "QLabel { color: #555; padding: 0 8px; font-weight: 600; }"
        )
        layout.addWidget(self._version_label)
        layout.addWidget(self._update_btn)
        layout.addWidget(self._settings_btn)
        layout.addWidget(self._help_btn)
        layout.addWidget(self._lang_btn)
        menubar.setCornerWidget(lang_container, Qt.TopRightCorner)

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

    def _open_help(self):
        try:
            dlg = HelpDialog(self)
            dlg.exec()
        except Exception:
            pass

    def _open_settings(self):
        try:
            dlg = SettingsDialog(
                self,
                session=getattr(self, "_session", None),
                update_remote_defaults=self.login.update_active_profile_remote_defaults,
            )
            dlg.exec()
            self.jobs_outputs.apply_refresh_settings()
            self.ftp.apply_settings()
        except Exception:
            pass

    def _show_update_progress(self, value: int, status_key: str) -> None:
        if self._update_progress is None:
            dialog = QProgressDialog(self)
            dialog.setWindowTitle(t("updates.progress_title"))
            dialog.setCancelButton(None)
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            dialog.setMinimumDuration(0)
            dialog.setRange(0, 100)
            dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self._update_progress = dialog
        self._on_update_progress(value, status_key)
        self._update_progress.show()

    def _on_update_progress(self, value: int, status_key: str) -> None:
        if self._update_progress is None:
            return
        label = t(f"updates.status_{status_key}")
        if label.startswith("[updates.status_"):
            label = status_key
        self._update_progress.setLabelText(label)
        self._update_progress.setValue(max(0, min(100, int(value))))

    def _close_update_progress(self) -> None:
        if self._update_progress is not None:
            self._update_progress.close()
            self._update_progress.deleteLater()
            self._update_progress = None

    def _run_update_job(self, fn, on_success) -> None:
        thread = QThread(self)
        worker = _BackgroundCall(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_success)
        worker.failed.connect(self._on_update_error)
        worker.progress.connect(self._on_update_progress)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda current=thread: self._update_job_finished(current))
        self._update_jobs.add(thread)
        self._update_workers[thread] = worker
        self._update_busy_count += 1
        self._update_btn.setEnabled(False)
        thread.start()

    def _update_job_finished(self, thread: QThread) -> None:
        self._update_jobs.discard(thread)
        self._update_workers.pop(thread, None)
        self._update_busy_count = max(0, self._update_busy_count - 1)
        if self._update_busy_count == 0:
            self._update_btn.setEnabled(True)

    def _check_for_updates(self, manual: bool = True) -> None:
        if self._update_busy_count:
            return
        self._update_manual = manual
        self._update_interactive = manual
        if manual:
            self._show_update_progress(5, "checking")
        self._run_update_job(
            lambda progress: get_latest_release(),
            self._on_release_checked,
        )

    def _on_release_checked(self, release) -> None:
        if not is_newer_version(release.version, __version__):
            self._close_update_progress()
            if self._update_manual:
                QMessageBox.information(
                    self,
                    t("updates.title"),
                    t("updates.up_to_date").format(version=__version__),
                )
            return

        self._update_interactive = True
        if not is_frozen_exe():
            self._close_update_progress()
            QMessageBox.information(
                self,
                t("updates.title"),
                t("updates.source_mode").format(version=release.version),
            )
            if release.html_url:
                webbrowser.open(release.html_url)
            return

        if not self._update_manual:
            self._show_update_progress(10, "available")
        else:
            self._on_update_progress(10, "available")
        answer = QMessageBox.question(
            self,
            t("updates.available_title"),
            t("updates.available_message").format(
                current=__version__,
                latest=release.version,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._close_update_progress()
            return
        self._on_update_progress(10, "downloading")
        self._run_update_job(
            lambda progress: (
                release,
                download_and_verify_release(release, progress_cb=progress),
            ),
            self._on_update_downloaded,
        )

    def _on_update_downloaded(self, result) -> None:
        release, zip_path = result
        answer = QMessageBox.question(
            self,
            t("updates.ready_title"),
            t("updates.ready_message").format(version=release.version),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._close_update_progress()
            return
        try:
            self._on_update_progress(100, "installing")
            launch_update_installer(zip_path, release.version)
        except Exception as exc:
            self._on_update_error(str(exc))
            return
        QApplication.quit()

    def _on_update_error(self, message: str) -> None:
        self._close_update_progress()
        if not self._update_interactive:
            return
        QMessageBox.critical(
            self,
            t("updates.error_title"),
            t("updates.error_message").format(error=message),
        )

    def start_quick_tour(self):
        try:
            overlay = QuickTourOverlay(self)
            overlay.show()
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
            self.tabs.setTabText(
                self.tabs.indexOf(self.ftp),
                t("tabs.ftp") if t("tabs.ftp") != "[tabs.ftp]" else "FTP",
            )
            self.tabs.setTabText(self.tabs.indexOf(self.editor), t("tabs.editor"))
            self.tabs.setTabText(self.tabs.indexOf(self.logs), t("tabs.logs"))

        # Language menu labels / selected language display
        if hasattr(self, "_act_tr"):
            self._act_tr.setText(t("language.turkish"))
        if hasattr(self, "_act_en"):
            self._act_en.setText(t("language.english"))
        if hasattr(self, "_help_menu"):
            self._help_menu.setTitle(t("help.help_title"))
        if hasattr(self, "_act_help_center"):
            self._act_help_center.setText(t("help.open_help"))
        if hasattr(self, "_help_btn"):
            self._help_btn.setText(t("help.help_title"))
            self._help_btn.setToolTip(t("help.open_help"))
        if hasattr(self, "_settings_btn"):
            self._settings_btn.setText(t("settings.action"))
            self._settings_btn.setToolTip(t("settings.dialog_title"))
        if hasattr(self, "_update_btn"):
            self._update_btn.setText(t("updates.action"))
            self._update_btn.setToolTip(t("updates.check_tip"))
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
        for w in (
            getattr(self, "login", None),
            getattr(self, "jobs_outputs", None),
            getattr(self, "directories", None),
            getattr(self, "ftp", None),
            getattr(self, "editor", None),
            getattr(self, "logs", None),
        ):
            if w is not None and hasattr(w, "retranslate_ui"):
                try:
                    w.retranslate_ui()
                except Exception:
                    pass

    def on_session_changed(self, session):
        self._job_poll_generation += 1
        self._job_poll_worker = None
        self._session = session
        self._last_job_ids = set()
        self._job_monitor_initialized = False
        self.jobs_outputs.set_session(session)
        self.directories.set_session(session)
        self.ftp.set_session(session)
        self.editor.set_session(session)
        self._sync_command_polling()

    def _sync_command_polling(self, _index: int = -1) -> None:
        if not hasattr(self, "tabs") or not hasattr(self, "jobs_outputs"):
            return
        page_active = self.tabs.currentWidget() is self.jobs_outputs
        self.jobs_outputs.set_page_active(page_active)
        session = getattr(self, "_session", None)
        should_poll_jobs = bool(
            session
            and session.get("connected")
            and self.jobs_outputs.is_details_polling_visible()
        )
        if should_poll_jobs:
            self.job_timer.start()
            self._poll_jobs()
        else:
            self.job_timer.stop()

    def show_directories(self):
        idx = self.tabs.indexOf(self.directories)
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)

    def open_in_editor(self, path: str, content: str):
        self.editor.open_file(path, content)
        idx = self.tabs.indexOf(self.editor)
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)

    def on_script_submitted(self, job_id: str, script_path: str):
        try:
            idx = self.tabs.indexOf(self.jobs_outputs)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
            if hasattr(self.jobs_outputs, "focus_job"):
                self.jobs_outputs.focus_job(job_id, script_path)
        except Exception:
            pass

    def _poll_jobs(self):
        # Runs periodically while Job Details is visible; reports finished jobs.
        if not self.jobs_outputs.is_details_polling_visible():
            self.job_timer.stop()
            return
        if self._job_poll_worker is not None:
            return
        session = getattr(self, "_session", None)
        if not session or not session.get("connected"):
            return
        ssh = session.get("ssh")
        slurm = session.get("slurm")
        cfg = session.get("cfg")
        if not ssh or not slurm or not cfg:
            return
        previous_ids = set(self._last_job_ids)
        initialized = self._job_monitor_initialized
        generation = self._job_poll_generation

        def fetch():
            out = slurm.active_job_ids(cfg.username)
            job_ids = {
                line.strip()
                for line in out.splitlines()
                if line.strip().isdigit()
            }
            states = {}
            if initialized:
                for jid in previous_ids - job_ids:
                    try:
                        state_out = slurm.job_state(jid)
                        states[jid] = next(
                            (
                                line.split("|", 1)[0].strip().split("+", 1)[0]
                                for line in state_out.splitlines()
                                if line.strip()
                            ),
                            "",
                        )
                    except Exception:
                        states[jid] = ""
            return job_ids, states

        worker = AsyncCall(generation, fetch)
        self._job_poll_worker = worker

        def failed(token, _exc) -> None:
            if self._job_poll_worker is worker:
                self._job_poll_worker = None

        def finished(token, result) -> None:
            if self._job_poll_worker is worker:
                self._job_poll_worker = None
            if token != self._job_poll_generation:
                return
            job_ids, states = result
            if not self._job_monitor_initialized:
                self._last_job_ids = job_ids
                self._job_monitor_initialized = True
                return
            self._show_finished_jobs(states)
            self._last_job_ids = job_ids

        worker.signals.failed.connect(failed)
        worker.signals.finished.connect(finished)
        QThreadPool.globalInstance().start(worker)

    def _show_finished_jobs(self, states: dict[str, str]) -> None:
        for jid in sorted(states):
            state = states[jid]
            if state == "COMPLETED":
                message = t("login.job_completed").format(jobid=jid)
            elif state:
                message = t("login.job_failed").format(jobid=jid, state=state)
            else:
                message = t("login.job_finished").format(jobid=jid)
            self.login.append_console(message)
            if self._job_tray:
                self._job_tray.showMessage(
                    t("login.job_notification_title"),
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    8000,
                )

    def closeEvent(self, event):
        """Gracefully stop background helper processes on app exit.

        Controlled by app settings:
        - close_vcxsrv_on_exit
        - close_x11_procs_on_exit
        """
        try:
            self.graceful_shutdown()
        except Exception:
            pass
        super().closeEvent(event)
