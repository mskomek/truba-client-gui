from __future__ import annotations

import html
import re
import shlex

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFontDatabase
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

    def __init__(self):
        super().__init__()
        self.session = None

        self.active_script: str = ""
        self.active_out: str = ""
        self.active_err: str = ""
        self._last_sig = [None, None]  # (size,mtime) for out/err

        self.section_tabs = QTabWidget(self)
        self.details_tab = QWidget(self.section_tabs)
        self.files_tab = QWidget(self.section_tabs)
        self.outputs_tab = QWidget(self.section_tabs)

        # --- Jobs box
        self.jobs_box = QGroupBox(t("jobs.title") if t("jobs.title") != "[jobs.title]" else "İşler")
        self.jobs_text = QTextEdit()
        self.jobs_text.setReadOnly(True)

        self.btn_refresh = QPushButton(t("jobs.refresh") if t("jobs.refresh") != "[jobs.refresh]" else "Yenile")
        self.btn_refresh.clicked.connect(self.refresh_jobs)

        self.cancel_id = QLineEdit()
        self.cancel_id.setPlaceholderText("Job ID")
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
        self.meta_box = QGroupBox("Accounting & Details")
        self.meta_text = QTextEdit()
        self.meta_text.setReadOnly(True)
        self.meta_text.setPlaceholderText("sacct / scontrol results")
        self.meta_job_id = QLineEdit()
        self.meta_job_id.setPlaceholderText("Job ID")
        self.btn_sacct = QPushButton("Refresh sacct")
        self.btn_scontrol = QPushButton("Show job details")
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
        self.lssrv_text.setLineWrapMode(QTextEdit.NoWrap)
        self.lssrv_text.setFont(
            QFontDatabase.systemFont(QFontDatabase.FixedFont)
        )
        self.lssrv_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #e8e8e8; "
            "border: 1px solid #555; }"
        )
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

        details_layout = QVBoxLayout(self.details_tab)
        details_layout.addWidget(self.jobs_box)
        details_layout.addWidget(self.meta_box)
        details_layout.addWidget(self.lssrv_box, 2)

        files_layout = QVBoxLayout(self.files_tab)
        files_layout.addWidget(self.scratch_panel)

        # --- Outputs group (2 panels)
        self.out_group = QGroupBox(t("jobs_outputs.outputs_title") if t("jobs_outputs.outputs_title") != "[jobs_outputs.outputs_title]" else "Çıktılar")
        outputs_layout = QVBoxLayout(self.outputs_tab)
        vg = QVBoxLayout(self.out_group)

        self.lbl_script = QLabel(t("jobs_outputs.no_script") if t("jobs_outputs.no_script") != "[jobs_outputs.no_script]" else "Aktif Slurm Script: (yok)")
        vg.addWidget(self.lbl_script)

        # Output-1: stdout
        b1 = QGroupBox((t("jobs_outputs.output_stdout") if t("jobs_outputs.output_stdout") != "[jobs_outputs.output_stdout]" else "Çıktı-1: Output"))
        v1 = QVBoxLayout(b1)
        self.path_out = QLineEdit()
        self.path_out.setReadOnly(True)
        self.txt_out = QTextEdit()
        self.txt_out.setReadOnly(True)
        v1.addWidget(self.path_out)
        v1.addWidget(self.txt_out)

        # Output-2: stderr
        b2 = QGroupBox((t("jobs_outputs.output_stderr") if t("jobs_outputs.output_stderr") != "[jobs_outputs.output_stderr]" else "Çıktı-2: Error"))
        v2 = QVBoxLayout(b2)
        self.path_err = QLineEdit()
        self.path_err.setReadOnly(True)
        self.txt_err = QTextEdit()
        self.txt_err.setReadOnly(True)
        v2.addWidget(self.path_err)
        v2.addWidget(self.txt_err)

        vg.addWidget(b1)
        vg.addWidget(b2)
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
        self.retranslate_ui()

    def set_session(self, session):
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
        self._live_timer.stop()
        self._jobs_refresh_timer.stop()
        self.apply_refresh_settings()

        if not session or not session.get("connected"):
            return

        cfg = session.get("cfg")
        user = getattr(cfg, "username", "") if cfg else ""
        self.scratch_panel.set_session(session)
        self.scratch_panel.set_dir(f"/arf/scratch/{user}" if user else "/arf/scratch")
        self.refresh_jobs()
        self.refresh_sacct()
        self.refresh_lssrv()
        self._jobs_refresh_timer.start()

    def shutdown(self) -> None:
        """Stop timers / live watchers (best-effort)."""
        try:
            if hasattr(self, "_live_timer") and self._live_timer:
                self._live_timer.stop()
            if hasattr(self, "_jobs_refresh_timer") and self._jobs_refresh_timer:
                self._jobs_refresh_timer.stop()
        except Exception:
            pass

    # ---------------- Jobs
    def refresh_jobs(self):
        if not self.session or not self.session.get("slurm"):
            return
        user = self.session["cfg"].username
        try:
            txt = self.session["slurm"].squeue(user)
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="JOBS")
            return
        self.jobs_text.setPlainText(txt)
        append_event({"type": "squeue", "user": user})

    def cancel_job(self):
        if not self.session or not self.session.get("slurm"):
            return
        jobid = self.cancel_id.text().strip()
        if not jobid:
            return
        try:
            res = self.session["slurm"].scancel(jobid)
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="JOBS")
            return
        self.jobs_text.append("\n" + res)
        append_event({"type": "scancel", "jobid": jobid})

    def refresh_sacct(self):
        if not self.session or not self.session.get("slurm"):
            return
        user = self.session["cfg"].username
        try:
            txt = self.session["slurm"].sacct(user)
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="JOBS")
            return
        self.meta_text.setPlainText(txt)
        append_event({"type": "sacct", "user": user})

    def show_job_details(self):
        if not self.session or not self.session.get("slurm"):
            return
        jobid = (self.meta_job_id.text() or "").strip() or (self.cancel_id.text() or "").strip()
        if not jobid:
            QMessageBox.information(self, t("common.info"), "Job ID required.")
            return
        try:
            txt = self.session["slurm"].scontrol_show_job(jobid)
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="JOBS")
            return
        self.meta_text.setPlainText(txt)
        append_event({"type": "scontrol_show_job", "jobid": jobid})

    def refresh_lssrv(self):
        if (
            not self.session
            or not self.session.get("connected")
            or not self.session.get("slurm")
        ):
            return
        append_event({"type": "lssrv", "status": "attempt"})
        self.lssrv_text.setPlainText("")
        try:
            txt = self.session["slurm"].lssrv()
        except Exception as e:
            append_event({"type": "lssrv", "status": "failed", "error": str(e)})
            self.lssrv_text.setPlainText(t("jobs_outputs.lssrv_failed"))
            show_exception(
                self,
                title=t("common.error"),
                user_message=str(e),
                exc=e,
                area="JOBS",
            )
            return
        if txt:
            self.lssrv_text.setHtml(_ansi_to_html(txt))
        else:
            self.lssrv_text.setPlainText(t("jobs_outputs.lssrv_empty"))
        append_event({"type": "lssrv", "status": "success"})

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
        self._apply_live_refresh_interval()
        self._live_timer.start()
        self._poll_live()
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
        self.lbl_script.setText(f"Aktif Slurm Script: {script_path}")

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
        if self.session and self.session.get("connected"):
            self._jobs_refresh_timer.start()

    def _poll_jobs_and_lssrv(self) -> None:
        if not self.session or not self.session.get("connected"):
            self._jobs_refresh_timer.stop()
            return
        self.apply_refresh_settings()
        self.refresh_jobs()
        if get_lssrv_auto_refresh_enabled():
            self.refresh_lssrv()

    def _apply_live_refresh_interval(self) -> None:
        if self._live_timer.interval() != _LIVE_TAIL_INTERVAL_MS:
            self._live_timer.setInterval(_LIVE_TAIL_INTERVAL_MS)

    @staticmethod
    def _set_live_text(widget: QTextEdit, text: str) -> None:
        widget.setPlainText(text)
        scrollbar = widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _poll_live(self):
        if not self.session:
            self._live_timer.stop()
            return
        self._apply_live_refresh_interval()
        files = self.session.get("files")
        ssh = self.session.get("ssh")
        if not files:
            self._live_timer.stop()
            return

        job_state = None

        def current_job_state() -> str:
            nonlocal job_state
            if job_state is not None:
                return job_state
            job_state = ""
            jobid = (self.meta_job_id.text() or self.cancel_id.text()).strip()
            slurm = self.session.get("slurm")
            if not jobid or not slurm:
                return job_state
            try:
                details = slurm.scontrol_show_job(jobid)
                match = re.search(r"\bJobState=([A-Z_]+)", details or "")
                if match:
                    job_state = match.group(1)
            except Exception:
                pass
            return job_state

        def missing_file_message(kind: str, error: Exception) -> str:
            state = current_job_state()
            if state:
                return t("jobs_outputs.waiting_for_file").format(
                    kind=kind,
                    state=state,
                )
            return t("jobs_outputs.waiting_for_file_unknown").format(
                kind=kind,
                error=error,
            )

        def fetch_tail(path: str) -> str:
            # Prefer SSH tail (efficient). Fallback to read_text (may be heavy).
            if ssh:
                try:
                    code, out, err = ssh.run(
                        f"tail -n {_LIVE_TAIL_LINE_COUNT} -- {shlex.quote(path)}"
                    )
                    if code == 0:
                        return out
                except Exception:
                    pass
            # fallback
            try:
                txt = files.read_text(path)
                lines = txt.splitlines()[-_LIVE_TAIL_LINE_COUNT:]
                return "\n".join(lines) + ("\n" if lines else "")
            except Exception as e:
                return f"(Dosya okunamadı: {e})"

        # output
        if self.active_out:
            try:
                sig = files.stat(self.active_out)
            except Exception as e:
                self._set_live_text(
                    self.txt_out,
                    missing_file_message("Output", e),
                )
                sig = None
            if sig:
                self._last_sig[0] = sig
                self._set_live_text(
                    self.txt_out,
                    fetch_tail(self.active_out),
                )

        # error
        if self.active_err:
            try:
                sig = files.stat(self.active_err)
            except Exception as e:
                self._set_live_text(
                    self.txt_err,
                    missing_file_message("Error", e),
                )
                sig = None
            if sig:
                self._last_sig[1] = sig
                self._set_live_text(
                    self.txt_err,
                    fetch_tail(self.active_err),
                )

        if not self.active_out and not self.active_err:
            self._live_timer.stop()

    def retranslate_ui(self):
        details_title = f"{t('jobs.title')} / {t('common.details')}"
        files_title = t("jobs_outputs.files_title")
        outputs_title = t("jobs_outputs.outputs_title") if t("jobs_outputs.outputs_title") != "[jobs_outputs.outputs_title]" else "Çıktılar"
        self.section_tabs.setTabText(0, details_title)
        self.section_tabs.setTabText(1, files_title)
        self.section_tabs.setTabText(2, outputs_title)
        self.jobs_box.setTitle(t("jobs.title") if t("jobs.title") != "[jobs.title]" else "İşler")
        self.meta_box.setTitle("Accounting & Details")
        self.lssrv_box.setTitle(t("jobs_outputs.lssrv_title"))
        self.out_group.setTitle(outputs_title)
        self.lbl_script.setText(t("jobs_outputs.no_script") if t("jobs_outputs.no_script") != "[jobs_outputs.no_script]" else "Aktif Slurm Script: (yok)")
        self.btn_refresh.setText(t("jobs.refresh") if t("jobs.refresh") != "[jobs.refresh]" else "Yenile")
        self.btn_cancel.setText(t("jobs.cancel") if t("jobs.cancel") != "[jobs.cancel]" else "İşi İptal Et")
        self.btn_sacct.setText("Refresh sacct")
        self.btn_scontrol.setText("Show job details")
        self.btn_lssrv.setText(t("jobs_outputs.lssrv_refresh"))
