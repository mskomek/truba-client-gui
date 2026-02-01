from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor, QGuiApplication
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QLabel

from truba_gui.core.i18n import t
from truba_gui.core.logging import log_path

class LogsWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("LogsWidget")

        self.lbl = QLabel(t("logs.title") if t("logs.title") != "[logs.title]" else "Logs")
        self.txt = QTextEdit()
        self.txt.setReadOnly(True)

        self.btn_refresh = QPushButton(t("logs.refresh") if t("logs.refresh") != "[logs.refresh]" else "Yenile")
        self.btn_refresh.clicked.connect(self.refresh)

        self.btn_copy = QPushButton(t("logs.copy") if t("logs.copy") != "[logs.copy]" else "Kopyala")
        self.btn_copy.clicked.connect(self.copy_all)

        top = QHBoxLayout()
        top.addWidget(self.lbl)
        top.addStretch(1)
        top.addWidget(self.btn_copy)
        top.addWidget(self.btn_refresh)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.txt)

        # light auto-refresh
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        self.refresh()

    def refresh(self) -> None:
        p = log_path()
        if not p.exists():
            self.txt.setPlainText("Log dosyası henüz oluşmadı: " + str(p))
            return
        try:
            data = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            self.txt.setPlainText(f"Log okunamadı: {e}")
            return
        # tail last ~4000 chars
        if len(data) > 4000:
            data = data[-4000:]
        self.txt.setPlainText(data)
        self.txt.moveCursor(QTextCursor.End)

    def copy_all(self) -> None:
        QGuiApplication.clipboard().setText(self.txt.toPlainText())
