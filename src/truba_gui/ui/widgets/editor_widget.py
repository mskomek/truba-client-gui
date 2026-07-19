from __future__ import annotations

import posixpath
import re

from PySide6.QtCore import QEvent, Signal, Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QMessageBox, QTabWidget
)

from truba_gui.core.i18n import t
from truba_gui.core.ui_errors import show_exception
from truba_gui.core.history import append_event


class _EditorTextEdit(QTextEdit):
    def __init__(self, owner: "EditorWidget", parent=None):
        super().__init__(parent)
        self._owner = owner

    def event(self, event) -> bool:  # type: ignore[override]
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and (
                (
                    event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and event.key()
                    in (
                        Qt.Key.Key_S,
                        Qt.Key.Key_F,
                        Qt.Key.Key_O,
                        Qt.Key.Key_W,
                        Qt.Key.Key_Tab,
                    )
                )
                or event.key() == Qt.Key.Key_F3
            )
        ):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_S:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self._owner.save_path(force_submit=True)
                else:
                    self._owner.save_path()
                event.accept()
                return
            if event.key() == Qt.Key.Key_F:
                self._owner.find_text()
                event.accept()
                return
            if event.key() == Qt.Key.Key_O:
                self._owner.focus_open_path()
                event.accept()
                return
            if event.key() == Qt.Key.Key_W:
                self._owner.close_active_tab()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Tab:
                self._owner.switch_document(
                    -1
                    if modifiers & Qt.KeyboardModifier.ShiftModifier
                    else 1
                )
                event.accept()
                return
        if event.key() == Qt.Key.Key_F3:
            self._owner.find_next()
            event.accept()
            return
        if (
            event.key() == Qt.Key.Key_End
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            scrollbar = self.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            event.accept()
            return
        super().keyPressEvent(event)


class _EditorDocument(QWidget):
    def __init__(
        self,
        owner: "EditorWidget",
        path: str = "",
        content: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.path = path
        self.text = _EditorTextEdit(owner, self)
        self.text.setPlainText(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text)


class EditorWidget(QWidget):
    script_submitted = Signal(str, str)  # job_id, script_path

    def __init__(self):
        super().__init__()
        self.session = None
        self.current_path: str | None = None

        self.path_in = QLineEdit()
        self.path_in.setPlaceholderText(t("placeholders.script_path"))
        self.path_in.returnPressed.connect(self.load_path)

        self.btn_load = QPushButton(t("editor.open"))
        self.btn_save = QPushButton(t("editor.save"))
        self.btn_save_submit = QPushButton(t("editor.save_submit") if t("editor.save_submit") != "[editor.save_submit]" else "Save + Submit")
        self.btn_lint = QPushButton(t("editor.lint") if t("editor.lint") != "[editor.lint]" else "Lint")

        self.btn_load.clicked.connect(self.load_path)
        self.btn_save.clicked.connect(self.save_path)
        self.btn_save_submit.clicked.connect(lambda: self.save_path(force_submit=True))
        self.btn_lint.clicked.connect(self.run_lint)

        top = QHBoxLayout()
        self.lbl_remote = QLabel(t("editor.remote"))
        top.addWidget(self.lbl_remote)
        top.addWidget(self.path_in, 1)
        top.addWidget(self.btn_load)
        top.addWidget(self.btn_lint)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_save_submit)

        self.document_tabs = QTabWidget()
        self.document_tabs.setTabsClosable(True)
        self.document_tabs.setMovable(True)
        self.document_tabs.currentChanged.connect(self._on_current_document_changed)
        self.document_tabs.tabCloseRequested.connect(self._close_document_tab)
        self._add_document()
        self._last_find_query = ""
        self.find_bar = QWidget()
        self.find_bar.setVisible(False)
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(0, 0, 0, 0)
        self.find_in = QLineEdit()
        self.find_in.setPlaceholderText(t("editor.find_placeholder"))
        self.replace_in = QLineEdit()
        self.replace_in.setPlaceholderText(t("editor.replace_placeholder"))
        self.btn_find_next = QPushButton(t("editor.find_next"))
        self.btn_replace = QPushButton(t("editor.replace"))
        self.btn_replace_all = QPushButton(t("editor.replace_all"))
        self.btn_find_close = QPushButton(t("common.close"))
        self.find_in.returnPressed.connect(self.find_next)
        self.btn_find_next.clicked.connect(self.find_next)
        self.btn_replace.clicked.connect(self.replace_current)
        self.btn_replace_all.clicked.connect(self.replace_all)
        self.btn_find_close.clicked.connect(self.find_bar.hide)
        find_layout.addWidget(QLabel(t("editor.find_label")))
        find_layout.addWidget(self.find_in, 1)
        find_layout.addWidget(QLabel(t("editor.replace_label")))
        find_layout.addWidget(self.replace_in, 1)
        find_layout.addWidget(self.btn_find_next)
        find_layout.addWidget(self.btn_replace)
        find_layout.addWidget(self.btn_replace_all)
        find_layout.addWidget(self.btn_find_close)
        self._shortcuts: list[QShortcut] = []
        self._install_shortcuts()

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.find_bar)
        lay.addWidget(self.document_tabs)

    def _add_shortcut(self, sequence, callback) -> None:
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)

    def _install_shortcuts(self) -> None:
        self._add_shortcut("Ctrl+S", self.save_path)
        self._add_shortcut("Ctrl+Shift+S", lambda: self.save_path(force_submit=True))
        self._add_shortcut("Ctrl+Z", lambda: self.text.undo())
        self._add_shortcut("Ctrl+Y", lambda: self.text.redo())
        self._add_shortcut("Ctrl+X", lambda: self.text.cut())
        self._add_shortcut("Ctrl+C", lambda: self.text.copy())
        self._add_shortcut("Ctrl+V", lambda: self.text.paste())
        self._add_shortcut("Ctrl+A", lambda: self.text.selectAll())
        self._add_shortcut("Ctrl+F", self.find_text)
        self._add_shortcut("F3", self.find_next)
        self._add_shortcut("Ctrl+O", self.focus_open_path)
        self._add_shortcut("Ctrl+W", self.close_active_tab)
        self._add_shortcut("Ctrl+Tab", lambda: self.switch_document(1))
        self._add_shortcut("Ctrl+Shift+Tab", lambda: self.switch_document(-1))

    @property
    def text(self) -> QTextEdit:
        document = self._current_document()
        if document is None:
            document = self._add_document()
        return document.text

    def _current_document(self) -> _EditorDocument | None:
        current = self.document_tabs.currentWidget()
        return current if isinstance(current, _EditorDocument) else None

    @staticmethod
    def _tab_title(path: str) -> str:
        return posixpath.basename(path.rstrip("/")) if path else t("editor.title")

    def _add_document(self, path: str = "", content: str = "") -> _EditorDocument:
        document = _EditorDocument(self, path, content, self.document_tabs)
        index = self.document_tabs.addTab(document, self._tab_title(path))
        self.document_tabs.setTabToolTip(index, path)
        self.document_tabs.setCurrentIndex(index)
        return document

    def _document_index_for_path(self, path: str) -> int:
        for index in range(self.document_tabs.count()):
            document = self.document_tabs.widget(index)
            if isinstance(document, _EditorDocument) and document.path == path:
                return index
        return -1

    def _on_current_document_changed(self, _index: int) -> None:
        document = self._current_document()
        path = document.path if document is not None else ""
        self.current_path = path or None
        self.path_in.setText(path)

    def _close_document_tab(self, index: int) -> None:
        document = self.document_tabs.widget(index)
        self.document_tabs.removeTab(index)
        if document is not None:
            document.deleteLater()
        if self.document_tabs.count() == 0:
            self._add_document()

    def close_active_tab(self) -> None:
        index = self.document_tabs.currentIndex()
        if index >= 0:
            self._close_document_tab(index)

    def switch_document(self, offset: int) -> None:
        count = self.document_tabs.count()
        if count < 2:
            return
        index = (self.document_tabs.currentIndex() + offset) % count
        self.document_tabs.setCurrentIndex(index)

    def focus_open_path(self) -> None:
        self.path_in.setFocus()
        self.path_in.selectAll()

    def find_text(self) -> None:
        self.find_bar.setVisible(True)
        if self._last_find_query and not self.find_in.text():
            self.find_in.setText(self._last_find_query)
        self.find_in.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.find_in.selectAll()

    def find_next(self) -> None:
        query = self.find_in.text()
        if not query:
            self.find_text()
            return
        self._last_find_query = query
        if self.text.find(query):
            return
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.text.setTextCursor(cursor)
        self.text.find(query)

    def replace_current(self) -> bool:
        query = self.find_in.text()
        if not query:
            self.find_text()
            return False
        cursor = self.text.textCursor()
        if cursor.selectedText() != query:
            self.find_next()
            cursor = self.text.textCursor()
            if cursor.selectedText() != query:
                return False
        cursor.insertText(self.replace_in.text())
        self.text.setTextCursor(cursor)
        return True

    def replace_all(self) -> int:
        query = self.find_in.text()
        if not query:
            self.find_text()
            return 0
        replacement = self.replace_in.text()
        text = self.text.toPlainText()
        count = text.count(query)
        if count <= 0:
            return 0
        self.text.setPlainText(text.replace(query, replacement))
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.text.setTextCursor(cursor)
        return count

    def _set_active_document_path(self, path: str) -> None:
        document = self._current_document()
        if document is None:
            document = self._add_document()
        document.path = path
        index = self.document_tabs.indexOf(document)
        self.document_tabs.setTabText(index, self._tab_title(path))
        self.document_tabs.setTabToolTip(index, path)
        self.current_path = path or None
        self.path_in.setText(path)

    def set_session(self, session):
        self.session = session

    def open_file(self, path: str, content: str):
        existing = self._document_index_for_path(path)
        if existing >= 0:
            self.document_tabs.setCurrentIndex(existing)
            return
        current = self._current_document()
        if (
            current is not None
            and not current.path
            and not current.text.toPlainText()
            and self.document_tabs.count() == 1
        ):
            current.path = path
            current.text.setPlainText(content)
            index = self.document_tabs.indexOf(current)
            self.document_tabs.setTabText(index, self._tab_title(path))
            self.document_tabs.setTabToolTip(index, path)
            self._on_current_document_changed(index)
            return
        self._add_document(path, content)

    def retranslate_ui(self):
        self.lbl_remote.setText(t("editor.remote"))
        self.btn_load.setText(t("editor.open"))
        self.btn_lint.setText(t("editor.lint") if t("editor.lint") != "[editor.lint]" else "Lint")
        self.btn_save.setText(t("editor.save"))
        self.btn_save_submit.setText(t("editor.save_submit") if t("editor.save_submit") != "[editor.save_submit]" else "Save + Submit")
        self.path_in.setPlaceholderText(t("placeholders.script_path"))
        self.find_in.setPlaceholderText(t("editor.find_placeholder"))
        self.replace_in.setPlaceholderText(t("editor.replace_placeholder"))
        self.btn_find_next.setText(t("editor.find_next"))
        self.btn_replace.setText(t("editor.replace"))
        self.btn_replace_all.setText(t("editor.replace_all"))
        self.btn_find_close.setText(t("common.close"))
        for index in range(self.document_tabs.count()):
            document = self.document_tabs.widget(index)
            if isinstance(document, _EditorDocument) and not document.path:
                self.document_tabs.setTabText(index, self._tab_title(""))

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
            show_exception(self, title=t("common.error"), user_message=t("editor.open_failed").format(err=e), exc=e, area="EDITOR")

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
            self._set_active_document_path(path)
            append_event({"type": "editor_save", "path": path})
            self._offer_submit_after_save(path, force_submit=force_submit)
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=t("editor.save_failed").format(err=e), exc=e, area="EDITOR")

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
            show_exception(self, title=t("common.error"), user_message=t("editor.submit_error").format(err=e), exc=e, area="SLURM")

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
