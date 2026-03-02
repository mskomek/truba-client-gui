from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QMessageBox
)

from truba_gui.core.i18n import t
from truba_gui.core.ui_errors import show_exception
from truba_gui.core.history import append_event


class EditorWidget(QWidget):
    script_submitted = Signal(str, str)  # job_id, script_path

    def __init__(self):
        super().__init__()
        self.session = None
        self.current_path: str | None = None

        self.path_in = QLineEdit()
        self.path_in.setPlaceholderText(t("placeholders.script_path"))

        self.btn_load = QPushButton(t("editor.open"))
        self.btn_save = QPushButton(t("editor.save"))
        self.btn_save_submit = QPushButton(t("editor.save_submit") if t("editor.save_submit") != "[editor.save_submit]" else "Save + Submit")
        self.btn_lint = QPushButton(t("editor.lint") if t("editor.lint") != "[editor.lint]" else "Lint")

        self.btn_load.clicked.connect(self.load_path)
        self.btn_save.clicked.connect(self.save_path)
        self.btn_save_submit.clicked.connect(lambda: self.save_path(force_submit=True))
        self.btn_lint.clicked.connect(self.run_lint)

        top = QHBoxLayout()
        top.addWidget(QLabel("Remote:"))
        top.addWidget(self.path_in, 1)
        top.addWidget(self.btn_load)
        top.addWidget(self.btn_lint)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_save_submit)

        self.text = QTextEdit()

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.text)

    def set_session(self, session):
        self.session = session

    def open_file(self, path: str, content: str):
        self.current_path = path
        self.path_in.setText(path)
        self.text.setPlainText(content)

    def retranslate_ui(self):
        self.btn_load.setText(t("editor.open"))
        self.btn_lint.setText(t("editor.lint") if t("editor.lint") != "[editor.lint]" else "Lint")
        self.btn_save.setText(t("editor.save"))
        self.btn_save_submit.setText(t("editor.save_submit") if t("editor.save_submit") != "[editor.save_submit]" else "Save + Submit")
        self.path_in.setPlaceholderText(t("placeholders.script_path"))

    def run_lint(self):
        path = self.path_in.text().strip()
        text = self.text.toPlainText()
        if not path:
            QMessageBox.information(self, t("common.info"), t("editor.lint_need_path") if t("editor.lint_need_path") != "[editor.lint_need_path]" else "Please provide a target path first.")
            return
        issues = self._collect_lint_issues(path, text)
        if not issues:
            QMessageBox.information(self, t("common.info"), t("editor.lint_ok") if t("editor.lint_ok") != "[editor.lint_ok]" else "Lint passed. No obvious issues found.")
            return
        QMessageBox.warning(
            self,
            t("common.warning") if t("common.warning") != "[common.warning]" else "Warning",
            (t("editor.lint_found") if t("editor.lint_found") != "[editor.lint_found]" else "Lint found potential issues:") + "\n\n" + "\n".join(issues),
        )

    def load_path(self):
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        path = self.path_in.text().strip()
        if not path:
            return
        try:
            content = self.session["files"].read_text(path)
            self.open_file(path, content)
            append_event({"type": "editor_load", "path": path})
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=f"Dosya açılamadı: {e}", exc=e, area="EDITOR")

    def save_path(self, force_submit: bool = False):
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        path = self.path_in.text().strip()
        if not path:
            return
        text = self.text.toPlainText()
        if not self._validate_before_save(path, text):
            return
        try:
            self.session["files"].write_text(path, text)
            self.current_path = path
            append_event({"type": "editor_save", "path": path})
            self._offer_submit_after_save(path, force_submit=force_submit)
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=f"Kaydedilemedi: {e}", exc=e, area="EDITOR")

    def _validate_before_save(self, path: str, text: str) -> bool:
        is_slurm = path.lower().endswith((".slurm", ".sbatch"))
        if not is_slurm:
            return True

        warnings = self._collect_lint_issues(path, text)

        if not warnings:
            return True

        message = (t("editor.validation_title") if t("editor.validation_title") != "[editor.validation_title]" else "Script validation warnings:") + "\n\n" + "\n".join(warnings)
        answer = QMessageBox.question(
            self,
            t("common.warning") if t("common.warning") != "[common.warning]" else "Warning",
            message + "\n\n" + (t("editor.validation_continue") if t("editor.validation_continue") != "[editor.validation_continue]" else "Save anyway?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _offer_submit_after_save(self, path: str, *, force_submit: bool = False):
        is_slurm = path.lower().endswith((".slurm", ".sbatch"))
        if not is_slurm:
            QMessageBox.information(self, t("common.info"), t("editor.saved") if t("editor.saved") != "[editor.saved]" else "Saved.")
            return

        if not force_submit:
            answer = QMessageBox.question(
                self,
                t("editor.submit") if t("editor.submit") != "[editor.submit]" else "Submit (sbatch)",
                t("editor.ask_submit_after_save") if t("editor.ask_submit_after_save") != "[editor.ask_submit_after_save]" else "Saved. Submit to Slurm now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                QMessageBox.information(self, t("common.info"), t("editor.saved") if t("editor.saved") != "[editor.saved]" else "Saved.")
                return

        slurm = (self.session or {}).get("slurm")
        if not slurm:
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        try:
            out = slurm.sbatch(path)
            append_event({"type": "editor_submit", "path": path, "result": out})
            job_id = self._extract_job_id(out)
            if job_id:
                self.script_submitted.emit(job_id, path)
                msg = (t("editor.submitted_job") if t("editor.submitted_job") != "[editor.submitted_job]" else "Submitted. Job ID: {jobid}").format(jobid=job_id)
                QMessageBox.information(self, t("common.info"), msg + "\n" + (out or ""))
            else:
                # sbatch can fail and still return output text. Show actionable error.
                details = out or ""
                hint = self._diagnose_submit_output(details)
                QMessageBox.critical(
                    self,
                    t("common.error"),
                    (t("editor.submit_failed") if t("editor.submit_failed") != "[editor.submit_failed]" else "Submission failed.") + "\n\n" + hint + ("\n\n" + details if details else ""),
                )
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=f"Gonderim hatasi: {e}", exc=e, area="SLURM")

    @staticmethod
    def _extract_job_id(sbatch_output: str) -> str:
        txt = sbatch_output or ""
        m = re.search(r"Submitted batch job\s+(\d+)", txt, flags=re.IGNORECASE)
        if m:
            return m.group(1)
        return ""

    def _collect_lint_issues(self, path: str, text: str) -> list[str]:
        issues: list[str] = []
        is_slurm = path.lower().endswith((".slurm", ".sbatch"))
        if not is_slurm:
            return issues
        stripped = text.lstrip()
        if not stripped.startswith("#!"):
            issues.append(t("editor.validation_missing_shebang") if t("editor.validation_missing_shebang") != "[editor.validation_missing_shebang]" else "- Missing shebang (e.g. #!/bin/bash)")
        if "#SBATCH" not in text:
            issues.append(t("editor.validation_missing_sbatch") if t("editor.validation_missing_sbatch") != "[editor.validation_missing_sbatch]" else "- No #SBATCH directives found")
        if "USERNAME" in text or "<partition>" in text:
            issues.append(t("editor.validation_placeholders") if t("editor.validation_placeholders") != "[editor.validation_placeholders]" else "- Template placeholders detected (USERNAME / <partition>)")
        if "--time=" not in text and "\n#SBATCH -t " not in text:
            issues.append(t("editor.validation_missing_time") if t("editor.validation_missing_time") != "[editor.validation_missing_time]" else "- Time limit is not set (#SBATCH --time or -t)")
        if "--output=" not in text and "\n#SBATCH -o " not in text:
            issues.append(t("editor.validation_missing_output") if t("editor.validation_missing_output") != "[editor.validation_missing_output]" else "- Output file is not set (#SBATCH --output or -o)")
        return issues

    def _diagnose_submit_output(self, details: str) -> str:
        msg = (details or "").lower()
        if "invalid account" in msg:
            return t("editor.submit_hint_account") if t("editor.submit_hint_account") != "[editor.submit_hint_account]" else "Invalid account/partition combination. Verify #SBATCH -A and -p values."
        if "invalid qos" in msg or "qos" in msg and "invalid" in msg:
            return t("editor.submit_hint_qos") if t("editor.submit_hint_qos") != "[editor.submit_hint_qos]" else "QOS is invalid for this account. Try another QOS/partition."
        if "time limit" in msg or "walltime" in msg or "qosmaxwalldurationperjoblimit" in msg:
            return t("editor.submit_hint_time") if t("editor.submit_hint_time") != "[editor.submit_hint_time]" else "Requested time is above policy limits. Lower --time or change QOS."
        if "more processors requested than permitted" in msg or "assocmaxcpuperjoblimit" in msg:
            return t("editor.submit_hint_cpu") if t("editor.submit_hint_cpu") != "[editor.submit_hint_cpu]" else "CPU request exceeds allowed limit. Reduce -c/-n or ask for higher limits."
        if "gres" in msg and ("invalid" in msg or "requested node configuration is not available" in msg):
            return t("editor.submit_hint_gpu") if t("editor.submit_hint_gpu") != "[editor.submit_hint_gpu]" else "GPU request may be invalid for selected partition. Check --gres and partition."
        return t("editor.submit_failed_hint") if t("editor.submit_failed_hint") != "[editor.submit_failed_hint]" else "Check account/partition/time/memory and script directives."
