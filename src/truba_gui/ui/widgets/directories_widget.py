from __future__ import annotations

import os
import posixpath
import re
import shlex
from pathlib import Path

from PySide6.QtCore import QPoint, QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter, QMessageBox,
    QDialog, QPushButton, QPlainTextEdit, QFileDialog, QInputDialog, QDialogButtonBox
)

from truba_gui.core.i18n import t
from truba_gui.core.ui_errors import show_exception
from truba_gui.core.history import append_event
from truba_gui.config.system_profile import format_remote_path, normalize_system_settings
from truba_gui.ui.widgets.remote_dir_panel import RemoteDirPanel


class _SubmitSignals(QObject):
    finished = Signal(object, str, str)  # worker, script path, sbatch output
    failed = Signal(object, str, str)  # worker, script path, error


class _SubmitWorker(QRunnable):
    def __init__(self, slurm, script_path: str):
        super().__init__()
        self._slurm = slurm
        self._script_path = script_path
        self.signals = _SubmitSignals()

    @Slot()
    def run(self) -> None:
        try:
            output = self._slurm.sbatch(self._script_path)
        except Exception as exc:
            self.signals.failed.emit(self, self._script_path, str(exc))
            return
        self.signals.finished.emit(self, self._script_path, output or "")


class _ShellRunSignals(QObject):
    finished = Signal(object, str, str)  # worker, script path, command output
    failed = Signal(object, str, str)  # worker, script path, error


class _ShellRunWorker(QRunnable):
    def __init__(self, ssh, script_path: str):
        super().__init__()
        self._ssh = ssh
        self._script_path = script_path
        self.signals = _ShellRunSignals()

    @staticmethod
    def command_for(script_path: str) -> str:
        script_dir = posixpath.dirname(script_path) or "."
        script_name = posixpath.basename(script_path)
        return (
            f"cd {shlex.quote(script_dir)} && "
            f"bash {shlex.quote('./' + script_name)}"
        )

    @Slot()
    def run(self) -> None:
        try:
            command = self.command_for(self._script_path)
            code, out, err = self._ssh.run(command, log_output=False)
            output = out if out.strip() else err
            if code != 0:
                message = output.strip() or f"script failed [exit={code}]"
                self.signals.failed.emit(self, self._script_path, message)
                return
        except Exception as exc:
            self.signals.failed.emit(self, self._script_path, str(exc))
            return
        self.signals.finished.emit(self, self._script_path, output or "")


class DirectoriesWidget(QWidget):
    open_in_editor = Signal(str, str)  # path, content
    script_submitted = Signal(str, str)  # job_id, script_path

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.session = None
        self._submit_workers: set[_SubmitWorker] = set()
        self._shell_run_workers: set[_ShellRunWorker] = set()

        self.panel_scratch = RemoteDirPanel(title="/arf/scratch")
        self.panel_home = RemoteDirPanel(title="/arf/home")

        self.panel_scratch.open_file.connect(self.on_open_file)
        self.panel_home.open_file.connect(self.on_open_file)
        self.panel_scratch.submit_requested.connect(self.submit_script)
        self.panel_home.submit_requested.connect(self.submit_script)
        self.panel_scratch.run_shell_requested.connect(self.run_shell_script)
        self.panel_home.run_shell_requested.connect(self.run_shell_script)

        self.splitter = QSplitter()
        self.splitter.addWidget(self.panel_scratch)
        self.splitter.addWidget(self.panel_home)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        self.btn_new_slurm = QPushButton(
            t("dirs.new_slurm_edit") if t("dirs.new_slurm_edit") != "[dirs.new_slurm_edit]" else "Create/Edit ARF Slurm"
        )
        self.btn_new_slurm.clicked.connect(self.create_slurm_from_template)

        top = QHBoxLayout()
        top.addWidget(self.btn_new_slurm)
        top.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.splitter)

    @staticmethod
    def _local_paths_from_drop(event) -> list[str]:
        mime = event.mimeData()
        if not mime or not mime.hasUrls():
            return []
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]

    def _panel_at_widget_pos(self, pos: QPoint) -> RemoteDirPanel:
        for panel in (self.panel_scratch, self.panel_home):
            top_left = panel.mapTo(self, QPoint(0, 0))
            rect = panel.rect().translated(top_left)
            if rect.contains(pos):
                return panel
        return self.panel_scratch

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if self._local_paths_from_drop(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._local_paths_from_drop(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        paths = self._local_paths_from_drop(event)
        if not paths:
            super().dropEvent(event)
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        panel = self._panel_at_widget_pos(pos)
        target_dir = panel.current_dir
        event.acceptProposedAction()
        QTimer.singleShot(
            0,
            lambda dropped_paths=list(paths), target_panel=panel, target=target_dir: (
                target_panel._apply_local_upload(dropped_paths, target)
            ),
        )

    def set_session(self, session):
        self.session = session
        self.panel_scratch.set_session(session)
        self.panel_home.set_session(session)

        if not session or not session.get("connected"):
            return
        user = session["cfg"].username or "user"
        system = normalize_system_settings(
            getattr(session["cfg"], "system_settings", None)
        )
        scratch_dir = format_remote_path(system["scratch_dir"], user)
        home_dir = format_remote_path(system["home_dir"], user)
        self.panel_scratch.title = scratch_dir
        self.panel_scratch.lbl.setText(scratch_dir)
        self.panel_home.title = home_dir
        self.panel_home.lbl.setText(home_dir)
        self.panel_scratch.set_dir(scratch_dir)
        self.panel_home.set_dir(home_dir)

    def retranslate_ui(self):
        self.btn_new_slurm.setText(
            t("dirs.new_slurm_edit") if t("dirs.new_slurm_edit") != "[dirs.new_slurm_edit]" else "Create/Edit ARF Slurm"
        )
        self.panel_scratch.retranslate_ui()
        self.panel_home.retranslate_ui()

    def submit_script(self, script_path: str) -> None:
        slurm = (self.session or {}).get("slurm")
        if not slurm:
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            append_event(
                {
                    "type": "directories_submit",
                    "path": script_path,
                    "status": "failed",
                    "error": "no Slurm session",
                }
            )
            return

        worker = _SubmitWorker(slurm, script_path)
        self._submit_workers.add(worker)
        worker.signals.finished.connect(self._on_submit_finished)
        worker.signals.failed.connect(self._on_submit_failed)
        QThreadPool.globalInstance().start(worker)

    def run_shell_script(self, script_path: str) -> None:
        ssh = (self.session or {}).get("ssh")
        if not ssh:
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            append_event(
                {
                    "type": "directories_run_shell",
                    "path": script_path,
                    "status": "failed",
                    "error": "no SSH session",
                }
            )
            return

        worker = _ShellRunWorker(ssh, script_path)
        self._shell_run_workers.add(worker)
        worker.signals.finished.connect(self._on_shell_run_finished)
        worker.signals.failed.connect(self._on_shell_run_failed)
        QThreadPool.globalInstance().start(worker)

    @Slot(object, str, str)
    def _on_submit_finished(self, worker: _SubmitWorker, script_path: str, output: str) -> None:
        self._submit_workers.discard(worker)
        job_id = self._extract_job_id(output)
        if not job_id:
            append_event(
                {
                    "type": "directories_submit",
                    "path": script_path,
                    "status": "failed",
                    "result": output,
                    "error": "no valid job ID",
                }
            )
            message = t("dirs.submit_failed_no_job_id")
            if message == "[dirs.submit_failed_no_job_id]":
                message = "Submission returned no valid job ID. Check the script and Slurm response."
            if output:
                message += f"\n\n{output}"
            QMessageBox.critical(self, t("common.error"), message)
            return

        append_event(
            {
                "type": "directories_submit",
                "path": script_path,
                "status": "success",
                "jobid": job_id,
                "result": output,
            }
        )
        self.script_submitted.emit(job_id, script_path)
        message = t("dirs.submit_success")
        if message == "[dirs.submit_success]":
            message = "Submitted with sbatch. Job ID: {jobid}"
        QMessageBox.information(
            self,
            t("common.info"),
            message.format(jobid=job_id) + (f"\n\n{output}" if output else ""),
        )

    @Slot(object, str, str)
    def _on_submit_failed(self, worker: _SubmitWorker, script_path: str, error: str) -> None:
        self._submit_workers.discard(worker)
        append_event(
            {
                "type": "directories_submit",
                "path": script_path,
                "status": "failed",
                "error": error,
            }
        )
        message = t("dirs.submit_failed")
        if message == "[dirs.submit_failed]":
            message = "sbatch submission failed: {err}\nCheck the connection and Slurm script directives."
        QMessageBox.critical(self, t("common.error"), message.format(err=error))

    def _create_shell_run_result_dialog(
        self,
        script_path: str,
        message: str,
        output: str,
    ) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle(t("common.info"))
        layout = QVBoxLayout(dialog)
        summary = QLabel(message)
        summary.setWordWrap(True)
        path_label = QLabel(script_path)
        path_label.setWordWrap(True)
        output_view = QPlainTextEdit()
        output_view.setObjectName("shellRunOutput")
        output_view.setReadOnly(True)
        output_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        output_view.setPlainText(output or "")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(summary)
        layout.addWidget(path_label)
        layout.addWidget(output_view, 1)
        layout.addWidget(buttons)

        available = self.screen().availableGeometry()
        max_width = max(320, int(available.width() * 0.90))
        max_height = max(240, int(available.height() * 0.85))
        dialog.setMaximumSize(max_width, max_height)
        dialog.resize(min(800, max_width), min(520, max_height))
        return dialog

    @Slot(object, str, str)
    def _on_shell_run_finished(self, worker: _ShellRunWorker, script_path: str, output: str) -> None:

        self._shell_run_workers.discard(worker)
        append_event(
            {
                "type": "directories_run_shell",
                "path": script_path,
                "status": "success",
                "result": output,
            }
        )
        message = t("dirs.run_shell_success")
        if message == "[dirs.run_shell_success]":
            message = "Script completed in terminal."
        self._create_shell_run_result_dialog(script_path, message, output).exec()

    @Slot(object, str, str)
    def _on_shell_run_failed(self, worker: _ShellRunWorker, script_path: str, error: str) -> None:
        self._shell_run_workers.discard(worker)
        append_event(
            {
                "type": "directories_run_shell",
                "path": script_path,
                "status": "failed",
                "error": error,
            }
        )
        message = t("dirs.run_shell_failed")
        if message == "[dirs.run_shell_failed]":
            message = "Script run failed: {err}"
        QMessageBox.critical(self, t("common.error"), message.format(err=error))

    @staticmethod
    def _extract_job_id(sbatch_output: str) -> str:
        match = re.search(
            r"Submitted batch job\s+(\d+)",
            sbatch_output or "",
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else ""

    def create_slurm_from_template(self):
        if not self.session or not self.session.get("connected"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        template_key = self._pick_template_key()
        if not template_key:
            return
        try:
            template_path = self._resolve_template_path(template_key)
            template_text = template_path.read_text(encoding="utf-8")
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=f"template.slurm okunamadi: {e}", exc=e, area="FILES")
            return

        default_dir = self.panel_scratch.current_dir or ""
        if not default_dir:
            cfg = self.session.get("cfg") if self.session else None
            user = getattr(cfg, "username", "") or "user"
            system = normalize_system_settings(
                getattr(cfg, "system_settings", None)
            )
            default_dir = format_remote_path(system["scratch_dir"], user)

        name, ok = QInputDialog.getText(
            self,
            t("dirs.new_slurm_name_title") if t("dirs.new_slurm_name_title") != "[dirs.new_slurm_name_title]" else "New Slurm Script",
            t("dirs.new_slurm_name_label") if t("dirs.new_slurm_name_label") != "[dirs.new_slurm_name_label]" else "File name:",
            text="new_job.slurm",
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        if not name.lower().endswith((".slurm", ".sbatch")):
            name += ".slurm"
        target_path = default_dir.rstrip("/") + "/" + name

        files = self.session.get("files") if self.session else None
        if files is not None:
            exists = False
            try:
                exists = bool(files.exists(target_path))
            except Exception:
                exists = False
            if exists:
                ans = QMessageBox.question(
                    self,
                    t("dirs.conflict_title"),
                    (t("dirs.new_slurm_exists") if t("dirs.new_slurm_exists") != "[dirs.new_slurm_exists]" else "File already exists. Overwrite in editor?"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return

        append_event({"type": "new_slurm_from_template", "path": target_path})
        self.open_in_editor.emit(target_path, template_text)

    def _pick_template_key(self) -> str:
        options = [
            t("dirs.template_core") if t("dirs.template_core") != "[dirs.template_core]" else "Core template",
            t("dirs.template_cpu") if t("dirs.template_cpu") != "[dirs.template_cpu]" else "CPU template",
            t("dirs.template_gpu") if t("dirs.template_gpu") != "[dirs.template_gpu]" else "GPU template",
            t("dirs.template_mpi") if t("dirs.template_mpi") != "[dirs.template_mpi]" else "MPI template",
        ]
        choice, ok = QInputDialog.getItem(
            self,
            t("dirs.template_select_title") if t("dirs.template_select_title") != "[dirs.template_select_title]" else "Slurm template",
            t("dirs.template_select_label") if t("dirs.template_select_label") != "[dirs.template_select_label]" else "Template type:",
            options,
            0,
            False,
        )
        if not ok:
            return ""
        mapping = {
            options[0]: "core",
            options[1]: "cpu",
            options[2]: "gpu",
            options[3]: "mpi",
        }
        return mapping.get(choice, "core")

    @staticmethod
    def _resolve_template_path(template_key: str) -> Path:
        root = Path(__file__).resolve().parents[4]
        user_tpl = Path.home() / ".truba_slurm_gui" / "templates"
        env_tpl = Path(os.environ.get("TRUBA_TEMPLATE_DIR", "")).expanduser() if os.environ.get("TRUBA_TEMPLATE_DIR") else None
        filename_map = {
            "core": "template.slurm",
            "cpu": "template_cpu.slurm",
            "gpu": "template_gpu.slurm",
            "mpi": "template_mpi.slurm",
        }
        mapping = {
            "core": root / "template.slurm",
            "cpu": root / "templates" / "template_cpu.slurm",
            "gpu": root / "templates" / "template_gpu.slurm",
            "mpi": root / "templates" / "template_mpi.slurm",
        }
        fname = filename_map.get(template_key, "template.slurm")
        search_paths = []
        if env_tpl:
            search_paths.append(env_tpl / fname)
        search_paths.append(user_tpl / fname)
        search_paths.append(mapping.get(template_key, mapping["core"]))
        for p in search_paths:
            if p.exists():
                return p
        # Safe fallback to core template if variant file missing.
        return mapping["core"]

    def shutdown(self) -> None:
        """Best-effort shutdown for file operations (cancel in-flight batches)."""
        for p in (getattr(self, "panel_scratch", None), getattr(self, "panel_home", None)):
            try:
                if p is not None and hasattr(p, "shutdown"):
                    p.shutdown()
            except Exception:
                pass

    def on_open_file(self, path: str):
        # If directory, we don't support navigation yet (next step). For now ignore.
        if path.endswith("/"):
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(t("dirs.file_actions") if t("dirs.file_actions") != "[dirs.file_actions]" else "Dosya İşlemleri")

        btn_download = QPushButton(t("dirs.download") if t("dirs.download") != "[dirs.download]" else "İndir")
        btn_edit = QPushButton(t("dirs.edit") if t("dirs.edit") != "[dirs.edit]" else "Düzelt")
        btn_close = QPushButton(t("common.cancel"))

        row = QHBoxLayout(dlg)
        row.addWidget(QLabel(path))
        row.addStretch(1)
        row.addWidget(btn_download)
        row.addWidget(btn_edit)
        row.addWidget(btn_close)

        def do_download():
            if not self.session or not self.session.get("files"):
                QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
                return
            try:
                content = self.session["files"].read_text(path)
            except Exception as e:
                show_exception(self, title=t("common.error"), user_message=t("dirs.unreadable").format(err=e), exc=e, area="FILES")
                return
            save_path, _ = QFileDialog.getSaveFileName(self, t("dirs.save_as") if t("dirs.save_as") != "[dirs.save_as]" else "Farklı Kaydet")
            if not save_path:
                return
            try:
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                show_exception(self, title=t("common.error"), user_message=f"Kaydedilemedi: {e}", exc=e, area="FILES")
                return
            append_event({"type": "download", "remote": path, "local": save_path})
            dlg.accept()

        def do_edit():
            if not self.session or not self.session.get("files"):
                QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
                return
            try:
                content = self.session["files"].read_text(path)
            except Exception as e:
                show_exception(self, title=t("common.error"), user_message=f"Okunamadı: {e}", exc=e, area="FILES")
                return
            append_event({"type": "open_editor", "path": path})
            self.open_in_editor.emit(path, content)
            dlg.accept()

        btn_download.clicked.connect(do_download)
        btn_edit.clicked.connect(do_edit)
        btn_close.clicked.connect(dlg.reject)

        dlg.exec()
