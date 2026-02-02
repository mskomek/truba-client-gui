from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt

from truba_gui.core.i18n import t, current_language
from truba_gui.core.resources import read_doc_text


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("help.help_title"))
        self.setModal(True)
        self.setMinimumSize(820, 620)

        layout = QVBoxLayout(self)

        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)

        lang = current_language()
        md = read_doc_text(f"HELP_{lang}.md")
        if md:
            self.browser.setMarkdown(md)
        else:
            self.browser.setPlainText(t("help.missing_help_text"))

        layout.addWidget(self.browser, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn = QPushButton(t("common.close"), self)
        btn.clicked.connect(self.accept)
        bottom.addWidget(btn, 0, Qt.AlignRight)
        layout.addLayout(bottom)
