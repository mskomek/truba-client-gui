from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QTextEdit,
    QLineEdit, QLabel, QMessageBox, QTabWidget
)

from truba_gui.core.i18n import t
from truba_gui.core.ui_errors import show_exception
from truba_gui.core.history import append_event
from truba_gui.ui.widgets.remote_dir_panel import RemoteDirPanel
from truba_gui.services.slurm_script_parser import parse_output_error, resolve_path


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

        # --- Scratch panel
        self.scratch_panel = RemoteDirPanel(
            title=t("jobs_outputs.scratch_title") if t("jobs_outputs.scratch_title") != "[jobs_outputs.scratch_title]" else "Scratch"
        )
        self.scratch_panel.open_file.connect(self.load_one_file)  # double click
        self.scratch_panel.enable_output_menu = True
        self.scratch_panel.open_in_slot.connect(self.open_in_output_slot)

        details_layout = QVBoxLayout(self.details_tab)
        details_layout.addWidget(self.jobs_box)
        details_layout.addWidget(self.meta_box)
        details_layout.addWidget(self.scratch_panel, 2)

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
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._poll_live)

        # --- main layout
        main = QVBoxLayout(self)
        main.addWidget(self.section_tabs)
        self.section_tabs.addTab(self.details_tab, "")
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
        self.active_script = ""
        self.active_out = ""
        self.active_err = ""
        self._last_sig = [None, None]
        self._live_timer.stop()

        if not session or not session.get("connected"):
            return

        cfg = session.get("cfg")
        user = getattr(cfg, "username", "") if cfg else ""
        self.scratch_panel.set_session(session)
        self.scratch_panel.set_dir(f"/arf/scratch/{user}" if user else "/arf/scratch")
        self.refresh_jobs()
        self.refresh_sacct()

    def shutdown(self) -> None:
        """Stop timers / live watchers (best-effort)."""
        try:
            if hasattr(self, "_live_timer") and self._live_timer:
                self._live_timer.stop()
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
        self._live_timer.start()
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
        # resolve paths relative to script dir
        out_path = resolve_path(script_path, out_raw) if out_raw else ""
        err_path = resolve_path(script_path, err_raw) if err_raw else ""

        # handle %j if jobid provided
        jobid = self.cancel_id.text().strip()
        if jobid:
            out_path = out_path.replace("%j", jobid) if out_path else out_path
            err_path = err_path.replace("%j", jobid) if err_path else err_path

        if out_path:
            self.open_in_output_slot(0, out_path)
        if err_path:
            self.open_in_output_slot(1, err_path)

        self.section_tabs.setCurrentWidget(self.outputs_tab)
        append_event({"type": "activate_slurm", "script": script_path, "out": out_path, "err": err_path})

    # ---------------- Live polling
    def _poll_live(self):
        if not self.session:
            self._live_timer.stop()
            return
        files = self.session.get("files")
        ssh = self.session.get("ssh")
        if not files:
            self._live_timer.stop()
            return

        def fetch_tail(path: str) -> str:
            # Prefer SSH tail (efficient). Fallback to read_text (may be heavy).
            if ssh:
                try:
                    code, out, err = ssh.run(f"tail -n 200 {path}")
                    if code == 0:
                        return out
                except Exception:
                    pass
            # fallback
            try:
                txt = files.read_text(path)
                lines = txt.splitlines()[-200:]
                return "\n".join(lines) + ("\n" if lines else "")
            except Exception as e:
                return f"(Dosya okunamadı: {e})"

        # output
        if self.active_out:
            try:
                sig = files.stat(self.active_out)
            except Exception as e:
                self.txt_out.setPlainText(f"(Output dosyası yok/okunamadı: {e})")
                sig = None
            if sig and sig != self._last_sig[0]:
                self._last_sig[0] = sig
                self.txt_out.setPlainText(fetch_tail(self.active_out))

        # error
        if self.active_err:
            try:
                sig = files.stat(self.active_err)
            except Exception as e:
                self.txt_err.setPlainText(f"(Error dosyası yok/okunamadı: {e})")
                sig = None
            if sig and sig != self._last_sig[1]:
                self._last_sig[1] = sig
                self.txt_err.setPlainText(fetch_tail(self.active_err))

        if not self.active_out and not self.active_err:
            self._live_timer.stop()

    def retranslate_ui(self):
        details_title = f"{t('jobs.title')} / {t('common.details')}"
        outputs_title = t("jobs_outputs.outputs_title") if t("jobs_outputs.outputs_title") != "[jobs_outputs.outputs_title]" else "Çıktılar"
        self.section_tabs.setTabText(0, details_title)
        self.section_tabs.setTabText(1, outputs_title)
        self.jobs_box.setTitle(t("jobs.title") if t("jobs.title") != "[jobs.title]" else "İşler")
        self.meta_box.setTitle("Accounting & Details")
        self.out_group.setTitle(outputs_title)
        self.lbl_script.setText(t("jobs_outputs.no_script") if t("jobs_outputs.no_script") != "[jobs_outputs.no_script]" else "Aktif Slurm Script: (yok)")
        self.btn_refresh.setText(t("jobs.refresh") if t("jobs.refresh") != "[jobs.refresh]" else "Yenile")
        self.btn_cancel.setText(t("jobs.cancel") if t("jobs.cancel") != "[jobs.cancel]" else "İşi İptal Et")
        self.btn_sacct.setText("Refresh sacct")
        self.btn_scontrol.setText("Show job details")
