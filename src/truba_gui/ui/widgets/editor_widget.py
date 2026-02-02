from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QMessageBox
)

from truba_gui.core.i18n import t
from truba_gui.core.ui_errors import show_exception
from truba_gui.core.history import append_event


class EditorWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.session = None
        self.current_path: str | None = None

        self.path_in = QLineEdit()
        self.path_in.setPlaceholderText(t("placeholders.script_path"))

        self.btn_load = QPushButton(t("editor.open"))
        self.btn_save = QPushButton(t("editor.save"))

        self.btn_load.clicked.connect(self.load_path)
        self.btn_save.clicked.connect(self.save_path)

        top = QHBoxLayout()
        top.addWidget(QLabel("Remote:"))
        top.addWidget(self.path_in, 1)
        top.addWidget(self.btn_load)
        top.addWidget(self.btn_save)

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

    def save_path(self):
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        path = self.path_in.text().strip()
        if not path:
            return
        try:
            self.session["files"].write_text(path, self.text.toPlainText())
            self.current_path = path
            append_event({"type": "editor_save", "path": path})
            QMessageBox.information(self, t("common.info"), "Kaydedildi.")
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=f"Kaydedilemedi: {e}", exc=e, area="EDITOR")
