from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter, QMessageBox,
    QDialog, QPushButton, QFileDialog
)

from truba_gui.core.i18n import t
from truba_gui.core.history import append_event
from truba_gui.ui.widgets.remote_dir_panel import RemoteDirPanel


class DirectoriesWidget(QWidget):
    open_in_editor = Signal(str, str)  # path, content

    def __init__(self):
        super().__init__()
        self.session = None

        self.panel_scratch = RemoteDirPanel(title="/arf/scratch")
        self.panel_home = RemoteDirPanel(title="/arf/home")

        self.panel_scratch.open_file.connect(self.on_open_file)
        self.panel_home.open_file.connect(self.on_open_file)

        splitter = QSplitter()
        splitter.addWidget(self.panel_scratch)
        splitter.addWidget(self.panel_home)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        lay = QVBoxLayout(self)
        lay.addWidget(splitter)

    def set_session(self, session):
        self.session = session
        self.panel_scratch.set_session(session)
        self.panel_home.set_session(session)

        if not session or not session.get("connected"):
            return
        user = session["cfg"].username or "user"
        self.panel_scratch.set_dir(f"/arf/scratch/{user}")
        self.panel_home.set_dir(f"/arf/home/{user}")

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
                QMessageBox.warning(self, t("common.error"), "Bağlantı yok.")
                return
            try:
                content = self.session["files"].read_text(path)
            except Exception as e:
                QMessageBox.warning(self, t("common.error"), f"Okunamadı: {e}")
                return
            save_path, _ = QFileDialog.getSaveFileName(self, t("dirs.save_as") if t("dirs.save_as") != "[dirs.save_as]" else "Farklı Kaydet")
            if not save_path:
                return
            try:
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                QMessageBox.warning(self, t("common.error"), f"Kaydedilemedi: {e}")
                return
            append_event({"type": "download", "remote": path, "local": save_path})
            dlg.accept()

        def do_edit():
            if not self.session or not self.session.get("files"):
                QMessageBox.warning(self, t("common.error"), "Bağlantı yok.")
                return
            try:
                content = self.session["files"].read_text(path)
            except Exception as e:
                QMessageBox.warning(self, t("common.error"), f"Okunamadı: {e}")
                return
            append_event({"type": "open_editor", "path": path})
            self.open_in_editor.emit(path, content)
            dlg.accept()

        btn_download.clicked.connect(do_download)
        btn_edit.clicked.connect(do_edit)
        btn_close.clicked.connect(dlg.reject)

        dlg.exec()
