from __future__ import annotations

import html
import re
import shlex

from PySide6.QtCore import QThreadPool, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QTextEdit,
    QLineEdit, QLabel, QMessageBox, QTabWidget
)

from truba_gui.config.storage import (
    get_jobs_outputs_refresh_interval_seconds,
    get_lssrv_auto_refresh_enabled,
)
from truba_gui.core.i18n import t
from truba_gui.core.ui_errors import show_exception
from truba_gui.core.history import append_event
from truba_gui.ui.widgets.remote_dir_panel import RemoteDirPanel
from truba_gui.services.slurm_script_parser import (
    parse_job_name,
    parse_output_error,
    resolve_path,
)
from truba_gui.config.system_profile import format_remote_path, normalize_system_settings
from truba_gui.ui.async_call import AsyncCall


_ANSI_TOKEN_RE = re.compile(
    r"\x1b(?:\[([0-9;]*)m|\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])"
)
_ANSI_COLORS = {
    30: "#000000", 31: "#cd3131", 32: "#0dbc79", 33: "#e5e510",
    34: "#2472c8", 35: "#bc3fbc", 36: "#11a8cd", 37: "#e5e5e5",
    90: "#666666", 91: "#f14c4c", 92: "#23d18b", 93: "#f5f543",
    94: "#3b8eea", 95: "#d670d6", 96: "#29b8db", 97: "#ffffff",
}
_LIVE_TAIL_INTERVAL_MS = 1000
_LIVE_TAIL_LINE_COUNT = 500


def _ansi_to_html(text: str) -> str:
    parts = []
    state = {"fg": "#e8e8e8", "bg": None, "bold": False}
    position = 0

    def append_segment(segment: str) -> None:
        if not segment:
            return
        styles = [f"color:{state['fg']}"]
        if state["bg"]:
            styles.append(f"background-color:{state['bg']}")
        if state["bold"]:
            styles.append("font-weight:bold")
        parts.append(
            f'<span style="{";".join(styles)}">{html.escape(segment)}</span>'
        )

    for match in _ANSI_TOKEN_RE.finditer(text or ""):
        append_segment((text or "")[position:match.start()])
        params = match.group(1)
        if params is not None:
            codes = [int(value) if value else 0 for value in params.split(";")]
            for code in codes:
                if code == 0:
                    state.update(fg="#e8e8e8", bg=None, bold=False)
                elif code == 1:
                    state["bold"] = True
                elif code == 22:
                    state["bold"] = False
                elif code == 39:
                    state["fg"] = "#e8e8e8"
                elif code == 49:
                    state["bg"] = None
                elif code in _ANSI_COLORS:
                    state["fg"] = _ANSI_COLORS[code]
                elif 40 <= code <= 47:
                    state["bg"] = _ANSI_COLORS[code - 10]
                elif 100 <= code <= 107:
                    state["bg"] = _ANSI_COLORS[code - 10]
        position = match.end()
    append_segment((text or "")[position:])
    return (
        '<pre style="margin:0; white-space:pre; font-family:monospace; '
        'font-size:10pt; background-color:#1e1e1e;">'
        + "".join(parts)
        + "</pre>"
    )


class JobsOutputsWidget(QWidget):
    request_show_directories = Signal()
    polling_visibility_changed = Signal()

    def __init__(self):
        super().__init__()
        self.session = None
        self._page_active = True

        self.active_script: str = ""
        self.active_out: str = ""
        self.active_err: str = ""
        self._last_sig = [None, None]  # (size,mtime) for out/err
        self._tail_paused = False
        self._async_workers: set[AsyncCall] = set()
        self._async_busy: dict[str, int] = {}
        self._session_generation = 0

        self.section_tabs = QTabWidget(self)
        self.details_tab = QWidget(self.section_tabs)
        self.files_tab = QWidget(self.section_tabs)
        self.outputs_tab = QWidget(self.section_tabs)

        # --- Jobs box
        self.jobs_box = QGroupBox(t("jobs.title") if t("jobs.title") != "[jobs.title]" else "İşler")
        self.jobs_text = QTextEdit()
        self.jobs_text.setReadOnly(True)
        self._apply_terminal_output_style(self.jobs_text)

        self.btn_refresh = QPushButton(t("jobs.refresh") if t("jobs.refresh") != "[jobs.refresh]" else "Yenile")
        self.btn_refresh.clicked.connect(self.refresh_jobs)

        self.cancel_id = QLineEdit()
        self.cancel_id.setPlaceholderText(t("jobs.job_id"))
        self.btn_cancel = QPushButton(t("jobs.cancel") if t("jobs.cancel") != "[jobs.cancel]" else "İşi İptal Et")
        self.btn_cancel.clicked.connect(self.cancel_job)

        row = QHBoxLayout()
        row.addWidget(self.btn_refresh)
        row.addStretch(1)
        row.addWidget(self.cancel_id)
        row.addWidget(self.btn_cancel)

        vj = QVBoxLayout(self.jobs_box)
        vj.addLayout(row)
        vj.addWidget(self.jobs_text)

        # --- Accounting / details box
        self.meta_box = QGroupBox(t("jobs_outputs.accounting_details"))
        self.meta_text = QTextEdit()
        self.meta_text.setReadOnly(True)
        self.meta_text.setPlaceholderText(t("jobs_outputs.accounting_placeholder"))
        self._apply_terminal_output_style(self.meta_text)
        self.meta_job_id = QLineEdit()
        self.meta_job_id.setPlaceholderText(t("jobs.job_id"))
        self.btn_sacct = QPushButton(t("jobs_outputs.refresh_sacct"))
        self.btn_scontrol = QPushButton(t("jobs_outputs.show_job_details"))
        self.btn_sacct.clicked.connect(self.refresh_sacct)
        self.btn_scontrol.clicked.connect(self.show_job_details)
        meta_row = QHBoxLayout()
        meta_row.addWidget(self.btn_sacct)
        meta_row.addStretch(1)
        meta_row.addWidget(self.meta_job_id)
        meta_row.addWidget(self.btn_scontrol)
        vm = QVBoxLayout(self.meta_box)
        vm.addLayout(meta_row)
        vm.addWidget(self.meta_text)

        # --- lssrv
        self.lssrv_box = QGroupBox()
        self.btn_lssrv = QPushButton()
        self.btn_lssrv.clicked.connect(self.refresh_lssrv)
        self.lssrv_text = QTextEdit()
        self.lssrv_text.setReadOnly(True)
        self._apply_terminal_output_style(self.lssrv_text)
        lssrv_layout = QVBoxLayout(self.lssrv_box)
        lssrv_row = QHBoxLayout()
        lssrv_row.addWidget(self.btn_lssrv)
        lssrv_row.addStretch(1)
        lssrv_layout.addLayout(lssrv_row)
        lssrv_layout.addWidget(self.lssrv_text)

        # --- Scratch panel (Files subtab)
        self.scratch_panel = RemoteDirPanel(
            title=t("jobs_outputs.scratch_title") if t("jobs_outputs.scratch_title") != "[jobs_outputs.scratch_title]" else "Scratch"
        )
        self.scratch_panel.open_file.connect(self.load_one_file)  # double click
        self.scratch_panel.enable_output_menu = True
        self.scratch_panel.open_in_slot.connect(self.open_in_output_slot)
        self.btn_files_refresh = QPushButton()
        self.btn_files_refresh.clicked.connect(self.scratch_panel.refresh)

        details_layout = QVBoxLayout(self.details_tab)
        details_layout.addWidget(self.jobs_box)
        details_layout.addWidget(self.meta_box)
        details_layout.addWidget(self.lssrv_box, 2)

        files_layout = QVBoxLayout(self.files_tab)
        files_refresh_row = QHBoxLayout()
        files_refresh_row.addWidget(self.btn_files_refresh)
        files_refresh_row.addStretch(1)
        files_layout.addLayout(files_refresh_row)
        files_layout.addWidget(self.scratch_panel)

        # --- Outputs group (2 panels)
        self.out_group = QGroupBox(t("jobs_outputs.outputs_title") if t("jobs_outputs.outputs_title") != "[jobs_outputs.outputs_title]" else "Çıktılar")
        outputs_layout = QVBoxLayout(self.outputs_tab)
        vg = QVBoxLayout(self.out_group)

        self.lbl_script = QLabel(t("jobs_outputs.no_script") if t("jobs_outputs.no_script") != "[jobs_outputs.no_script]" else "Aktif Slurm Script: (yok)")
        vg.addWidget(self.lbl_script)
        self.btn_tail_pause = QPushButton()
        self.btn_tail_pause.clicked.connect(self._toggle_tail_pause)
        tail_controls = QHBoxLayout()
        tail_controls.addWidget(self.btn_tail_pause)
        tail_controls.addStretch(1)
        vg.addLayout(tail_controls)

        # Output-1: stdout
        self.out_box = QGroupBox(t("jobs_outputs.output_stdout"))
        v1 = QVBoxLayout(self.out_box)
        self.path_out = QLineEdit()
        self.path_out.setReadOnly(True)
        self.search_out = QLineEdit()
        self.btn_search_out = QPushButton()
        self.search_out.returnPressed.connect(lambda: self._find_in_output(0))
        self.btn_search_out.clicked.connect(lambda: self._find_in_output(0))
        search_out_row = QHBoxLayout()
        search_out_row.addWidget(self.search_out)
        search_out_row.addWidget(self.btn_search_out)
        self.txt_out = QTextEdit()
        self.txt_out.setReadOnly(True)
        v1.addWidget(self.path_out)
        v1.addLayout(search_out_row)
        v1.addWidget(self.txt_out)

        # Output-2: stderr
        self.err_box = QGroupBox(t("jobs_outputs.output_stderr"))
        v2 = QVBoxLayout(self.err_box)
        self.path_err = QLineEdit()
        self.path_err.setReadOnly(True)
        self.search_err = QLineEdit()
        self.btn_search_err = QPushButton()
        self.search_err.returnPressed.connect(lambda: self._find_in_output(1))
        self.btn_search_err.clicked.connect(lambda: self._find_in_output(1))
        search_err_row = QHBoxLayout()
        search_err_row.addWidget(self.search_err)
        search_err_row.addWidget(self.btn_search_err)
        self.txt_err = QTextEdit()
        self.txt_err.setReadOnly(True)
        v2.addWidget(self.path_err)
        v2.addLayout(search_err_row)
        v2.addWidget(self.txt_err)

        vg.addWidget(self.out_box)
        vg.addWidget(self.err_box)
        outputs_layout.addWidget(self.out_group)
        outputs_layout.addStretch(1)

        # --- Live timer
        self._live_timer = QTimer(self)
        self._apply_live_refresh_interval()
        self._live_timer.timeout.connect(self._poll_live)

        self._jobs_refresh_timer = QTimer(self)
        self._jobs_refresh_timer.timeout.connect(self._poll_jobs_and_lssrv)
        self.apply_refresh_settings()

        # --- main layout
        main = QVBoxLayout(self)
        main.addWidget(self.section_tabs)
        self.section_tabs.addTab(self.details_tab, "")
        self.section_tabs.addTab(self.files_tab, "")
        self.section_tabs.addTab(self.outputs_tab, "")
        self.section_tabs.setCurrentIndex(0)
        self.section_tabs.currentChanged.connect(
            self._on_section_tab_changed
        )
        self.retranslate_ui()

    @staticmethod
    def _apply_terminal_output_style(widget: QTextEdit) -> None:
        widget.setLineWrapMode(QTextEdit.NoWrap)
        widget.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        widget.setStyleSheet(
            "QTextEdit { background-color: #111111; color: #e8e8e8; "
            "border: 1px solid #555; selection-background-color: #264f78; }"
        )

    def set_session(self, session):
        self._session_generation += 1
        self._async_busy.clear()
        self.session = session
        self.jobs_text.setPlainText("")
        self.txt_out.setPlainText("")
        self.txt_err.setPlainText("")
        self.path_out.setText("")
        self.path_err.setText("")
        self.meta_text.setPlainText("")
        self.meta_job_id.setText("")
        self.lssrv_text.setPlainText("")
        self.active_script = ""
        self.active_out = ""
        self.active_err = ""
        self._last_sig = [None, None]
        self._tail_paused = False
        self._update_tail_pause_button()
        self._live_timer.stop()
        self._jobs_refresh_timer.stop()
        self.apply_refresh_settings()

        if not session or not session.get("connected"):
            return

        cfg = session.get("cfg")
        user = getattr(cfg, "username", "") if cfg else ""
        system = normalize_system_settings(
            getattr(cfg, "system_settings", None) if cfg else None
        )
        scratch_dir = format_remote_path(system["scratch_dir"], user)
        self.scratch_panel.set_session(session)
        self.scratch_panel.title = scratch_dir
        self.scratch_panel.lbl.setText(scratch_dir)
        self.scratch_panel.set_dir(scratch_dir)
        self._sync_polling(immediate=True)

    def set_page_active(self, active: bool) -> None:
        active = bool(active)
        if self._page_active == active:
            return
        self._page_active = active
        self._sync_polling(immediate=active)
        self.polling_visibility_changed.emit()

    def is_details_polling_visible(self) -> bool:
        return bool(
            self._page_active
            and self.section_tabs.currentWidget() is self.details_tab
        )

    def is_outputs_polling_visible(self) -> bool:
        return bool(
            self._page_active
            and self.section_tabs.currentWidget() is self.outputs_tab
        )

    def _on_section_tab_changed(self, _index: int) -> None:
        self._sync_polling(immediate=True)
        self.polling_visibility_changed.emit()

    def _sync_polling(self, *, immediate: bool = False) -> None:
        connected = bool(self.session and self.session.get("connected"))
        if connected and self.is_details_polling_visible():
            self._jobs_refresh_timer.start()
            if immediate:
                self.refresh_jobs()
                self.refresh_sacct()
                self.refresh_lssrv()
        else:
            self._jobs_refresh_timer.stop()

        should_tail = bool(
            connected
            and self.is_outputs_polling_visible()
            and not self._tail_paused
            and (self.active_out or self.active_err)
        )
        if should_tail:
            self._apply_live_refresh_interval()
            self._live_timer.start()
            if immediate:
                self._poll_live()
        else:
            self._live_timer.stop()

    def shutdown(self) -> None:
        """Stop timers / live watchers (best-effort)."""
        try:
            if hasattr(self, "_live_timer") and self._live_timer:
                self._live_timer.stop()
            if hasattr(self, "_jobs_refresh_timer") and self._jobs_refresh_timer:
                self._jobs_refresh_timer.stop()
            self._session_generation += 1
            self._async_busy.clear()
        except Exception:
            pass

    def _start_async(
        self,
        key: str,
        fn,
        on_success,
        *,
        on_error=None,
    ) -> bool:
        if key in self._async_busy:
            return False
        generation = self._session_generation
        token = (key, generation)
        worker = AsyncCall(token, fn)
        self._async_busy[key] = generation
        self._async_workers.add(worker)

        def finished(current_token, result) -> None:
            self._async_workers.discard(worker)
            if self._async_busy.get(key) == generation:
                self._async_busy.pop(key, None)
            if current_token != (key, self._session_generation):
                return
            on_success(result)

        def failed(current_token, exc) -> None:
            self._async_workers.discard(worker)
            if self._async_busy.get(key) == generation:
                self._async_busy.pop(key, None)
            if current_token != (key, self._session_generation):
                return
            if on_error is not None:
                on_error(exc)

        worker.signals.finished.connect(finished)
        worker.signals.failed.connect(failed)
        QThreadPool.globalInstance().start(worker)
        return True

    # ---------------- Jobs
    def refresh_jobs(self):
        if not self.session or not self.session.get("slurm"):
            return
        user = self.session["cfg"].username
        slurm = self.session["slurm"]

        def success(txt) -> None:
            if not self.is_details_polling_visible():
                return
            self.jobs_text.setPlainText(txt)
            append_event({"type": "squeue", "user": user})

        def failed(e) -> None:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="JOBS")

        self._start_async(
            "squeue",
            lambda: slurm.squeue(user),
            success,
            on_error=failed,
        )

    def cancel_job(self):
        if not self.session or not self.session.get("slurm"):
            return
        jobid = self.cancel_id.text().strip()
        if not jobid:
            return
        slurm = self.session["slurm"]

        def success(res) -> None:
            self.jobs_text.append("\n" + res)
            append_event({"type": "scancel", "jobid": jobid})

        def failed(e) -> None:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="JOBS")

        self._start_async(
            "scancel",
            lambda: slurm.scancel(jobid),
            success,
            on_error=failed,
        )

    def refresh_sacct(self):
        if not self.session or not self.session.get("slurm"):
            return
        user = self.session["cfg"].username
        slurm = self.session["slurm"]

        def success(txt) -> None:
            if not self.is_details_polling_visible():
                return
            self.meta_text.setPlainText(txt)
            append_event({"type": "sacct", "user": user})

        def failed(e) -> None:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="JOBS")

        self._start_async(
            "sacct",
            lambda: slurm.sacct(user),
            success,
            on_error=failed,
        )

    def show_job_details(self):
        if not self.session or not self.session.get("slurm"):
            return
        jobid = (self.meta_job_id.text() or "").strip() or (self.cancel_id.text() or "").strip()
        if not jobid:
            QMessageBox.information(
                self, t("common.info"), t("jobs_outputs.job_id_required")
            )
            return
        slurm = self.session["slurm"]

        def success(txt) -> None:
            self.meta_text.setPlainText(txt)
            append_event({"type": "scontrol_show_job", "jobid": jobid})

        def failed(e) -> None:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="JOBS")

        self._start_async(
            "scontrol",
            lambda: slurm.scontrol_show_job(jobid),
            success,
            on_error=failed,
        )

    def refresh_lssrv(self):
        if (
            not self.session
            or not self.session.get("connected")
            or not self.session.get("slurm")
        ):
            return
        slurm = self.session["slurm"]

        def success(txt) -> None:
            if not self.is_details_polling_visible():
                return
            if txt:
                self.lssrv_text.setHtml(_ansi_to_html(txt))
            else:
                self.lssrv_text.setPlainText(t("jobs_outputs.lssrv_empty"))
            append_event({"type": "lssrv", "status": "success"})

        def failed(e) -> None:
            append_event({"type": "lssrv", "status": "failed", "error": str(e)})
            self.lssrv_text.setPlainText(t("jobs_outputs.lssrv_failed"))
            show_exception(
                self,
                title=t("common.error"),
                user_message=str(e),
                exc=e,
                area="JOBS",
            )

        if self._start_async(
            "lssrv",
            slurm.lssrv,
            success,
            on_error=failed,
        ):
            append_event({"type": "lssrv", "status": "attempt"})

    def focus_job(self, jobid: str, script_path: str = ""):
        """Focus a submitted job in the jobs UI and optionally bind outputs from script."""
        if not jobid:
            return
        self.cancel_id.setText(jobid)
        self.meta_job_id.setText(jobid)
        self.refresh_jobs()
        self.refresh_sacct()
        if script_path:
            self._activate_slurm_script(script_path)
            self.section_tabs.setCurrentWidget(self.outputs_tab)

    # ---------------- File open behaviors
    def load_one_file(self, remote_path: str):
        """
        Çift tık: Eğer slurm script ise parse edip output/error'a bağlan.
        Değilse varsayılan olarak Çıktı-1'de aç ve izle.
        """
        if not remote_path:
            return
        lower = remote_path.lower()
        if lower.endswith((".slurm", ".sbatch")):
            self._activate_slurm_script(remote_path)
        else:
            self.open_in_output_slot(0, remote_path)

    def open_in_output_slot(self, slot: int, remote_path: str):
        """
        Sağ tuş menüsü: seçili dosyayı Output-1 (slot=0) veya Output-2 (slot=1) izle.
        """
        if slot == 0:
            self.active_out = remote_path
            self.path_out.setText(remote_path)
            self._last_sig[0] = None
            self.txt_out.setPlainText("")
        else:
            self.active_err = remote_path
            self.path_err.setText(remote_path)
            self._last_sig[1] = None
            self.txt_err.setPlainText("")
        self.section_tabs.setCurrentWidget(self.outputs_tab)
        self._sync_polling(immediate=True)
        append_event({"type": "open_watch", "slot": slot+1, "path": remote_path})

    def _activate_slurm_script(self, script_path: str):
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        files = self.session["files"]
        try:
            script_text = files.read_text(script_path)
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=f"Script açılamadı: {e}", exc=e, area="JOBS")
            return

        self.active_script = script_path
        self.lbl_script.setText(t("jobs_outputs.active_script").format(path=script_path))

        out_raw, err_raw = parse_output_error(script_text)
        job_name = parse_job_name(script_text)
        jobid = self.cancel_id.text().strip() or None
        # resolve paths relative to script dir
        out_path = resolve_path(script_path, out_raw, jobid, job_name) if out_raw else ""
        err_path = resolve_path(script_path, err_raw, jobid, job_name) if err_raw else ""

        if out_path:
            self.open_in_output_slot(0, out_path)
        if err_path:
            self.open_in_output_slot(1, err_path)

        self.section_tabs.setCurrentWidget(self.outputs_tab)
        self._poll_live()
        append_event({"type": "activate_slurm", "script": script_path, "out": out_path, "err": err_path})

    # ---------------- Live polling
    def apply_refresh_settings(self) -> None:
        interval_ms = max(1000, get_jobs_outputs_refresh_interval_seconds() * 1000)
        self._jobs_refresh_timer.setInterval(interval_ms)
        self._apply_live_refresh_interval()
        if (
            self.session
            and self.session.get("connected")
            and self.is_details_polling_visible()
        ):
            self._jobs_refresh_timer.start()
        else:
            self._jobs_refresh_timer.stop()

    def _poll_jobs_and_lssrv(self) -> None:
        if (
            not self.session
            or not self.session.get("connected")
            or not self.is_details_polling_visible()
        ):
            self._jobs_refresh_timer.stop()
            return
        self.apply_refresh_settings()
        self.refresh_jobs()
        if get_lssrv_auto_refresh_enabled():
            self.refresh_lssrv()

    def _apply_live_refresh_interval(self) -> None:
        if self._live_timer.interval() != _LIVE_TAIL_INTERVAL_MS:
            self._live_timer.setInterval(_LIVE_TAIL_INTERVAL_MS)

    def _update_tail_pause_button(self) -> None:
        key = "jobs_outputs.tail_resume" if self._tail_paused else "jobs_outputs.tail_pause"
        self.btn_tail_pause.setText(t(key))

    def _toggle_tail_pause(self) -> None:
        self._tail_paused = not self._tail_paused
        self._update_tail_pause_button()
        if self._tail_paused:
            self._live_timer.stop()
            return
        self._sync_polling(immediate=True)

    def _find_in_output(self, slot: int) -> None:
        search = self.search_out if slot == 0 else self.search_err
        output = self.txt_out if slot == 0 else self.txt_err
        query = search.text()
        if not query:
            return
        if output.find(query):
            return
        cursor = output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        output.setTextCursor(cursor)
        output.find(query)

    @staticmethod
    def _set_live_text(widget: QTextEdit, text: str) -> None:
        widget.setPlainText(text)
        scrollbar = widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _poll_live(self):
        if self._tail_paused or not self.is_outputs_polling_visible():
            self._live_timer.stop()
            return
        if not self.session:
            self._live_timer.stop()
            return
        self._apply_live_refresh_interval()
        files = self.session.get("files")
        ssh = self.session.get("ssh")
        if not files:
            self._live_timer.stop()
            return

        paths = (self.active_out, self.active_err)
        if not any(paths):
            self._live_timer.stop()
            return

        def fetch() -> list[tuple[int, str, str, str]]:
            results = []
            for slot, path in enumerate(paths):
                if not path:
                    continue
                try:
                    if ssh:
                        code, out, err = ssh.run(
                            f"tail -n {_LIVE_TAIL_LINE_COUNT} -- {shlex.quote(path)}",
                            log_output=False,
                        )
                        if code == 0:
                            results.append((slot, path, out, ""))
                            continue
                        raise RuntimeError(err.strip() or f"exit={code}")
                    text = files.read_text(path)
                    lines = text.splitlines()[-_LIVE_TAIL_LINE_COUNT:]
                    tail = "\n".join(lines) + ("\n" if lines else "")
                    results.append((slot, path, tail, ""))
                except Exception as exc:
                    results.append((slot, path, "", str(exc)))
            return results

        def success(results) -> None:
            if not self.is_outputs_polling_visible():
                return
            for slot, path, text, error in results:
                current_path = self.active_out if slot == 0 else self.active_err
                if path != current_path:
                    continue
                widget = self.txt_out if slot == 0 else self.txt_err
                if error:
                    kind_key = (
                        "jobs_outputs.output_kind"
                        if slot == 0
                        else "jobs_outputs.error_kind"
                    )
                    self._set_live_text(
                        widget,
                        t("jobs_outputs.waiting_for_file_unknown").format(
                            kind=t(kind_key),
                            error=error,
                        ),
                    )
                else:
                    self._set_live_text(widget, text)

        self._start_async("tail", fetch, success)

    def retranslate_ui(self):
        details_title = f"{t('jobs.title')} / {t('common.details')}"
        files_title = t("jobs_outputs.files_title")
        outputs_title = t("jobs_outputs.outputs_title") if t("jobs_outputs.outputs_title") != "[jobs_outputs.outputs_title]" else "Çıktılar"
        self.section_tabs.setTabText(0, details_title)
        self.section_tabs.setTabText(1, files_title)
        self.section_tabs.setTabText(2, outputs_title)
        self.jobs_box.setTitle(t("jobs.title") if t("jobs.title") != "[jobs.title]" else "İşler")
        self.meta_box.setTitle(t("jobs_outputs.accounting_details"))
        self.lssrv_box.setTitle(t("jobs_outputs.lssrv_title"))
        self.out_group.setTitle(outputs_title)
        self.out_box.setTitle(t("jobs_outputs.output_stdout"))
        self.err_box.setTitle(t("jobs_outputs.output_stderr"))
        self.lbl_script.setText(t("jobs_outputs.no_script") if t("jobs_outputs.no_script") != "[jobs_outputs.no_script]" else "Aktif Slurm Script: (yok)")
        self.btn_refresh.setText(t("jobs.refresh") if t("jobs.refresh") != "[jobs.refresh]" else "Yenile")
        self.btn_cancel.setText(t("jobs.cancel") if t("jobs.cancel") != "[jobs.cancel]" else "İşi İptal Et")
        self.cancel_id.setPlaceholderText(t("jobs.job_id"))
        self.meta_job_id.setPlaceholderText(t("jobs.job_id"))
        self.meta_text.setPlaceholderText(t("jobs_outputs.accounting_placeholder"))
        self.btn_sacct.setText(t("jobs_outputs.refresh_sacct"))
        self.btn_scontrol.setText(t("jobs_outputs.show_job_details"))
        self.btn_lssrv.setText(t("jobs_outputs.lssrv_refresh"))
        self.btn_files_refresh.setText(t("dirs.refresh"))
        self.search_out.setPlaceholderText(t("jobs_outputs.search_placeholder"))
        self.search_err.setPlaceholderText(t("jobs_outputs.search_placeholder"))
        self.btn_search_out.setText(t("jobs_outputs.search_next"))
        self.btn_search_err.setText(t("jobs_outputs.search_next"))
        self._update_tail_pause_button()
