from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QHBoxLayout, QPushButton, QCheckBox
from PySide6.QtCore import Qt

from truba_gui.core.i18n import t, current_language
from truba_gui.core.resources import read_doc_text


class WelcomeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("help.welcome_title"))
        self.setModal(True)
        self.setMinimumSize(720, 520)

        layout = QVBoxLayout(self)

        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)

        lang = current_language()
        md = read_doc_text(f"WELCOME_{lang}.md") or read_doc_text(f"HELP_{lang}.md")
        if md:
            # Qt6 QTextBrowser supports markdown natively.
            self.browser.setMarkdown(md)
        else:
            self.browser.setPlainText(t("help.missing_help_text"))

        layout.addWidget(self.browser, 1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 6, 0, 0)

        self.chk_no_show = QCheckBox(t("help.dont_show_again"), self)
        self.chk_no_show.setChecked(False)
        bottom.addWidget(self.chk_no_show, 0, Qt.AlignLeft)

        bottom.addStretch(1)

        btn = QPushButton(t("common.close"), self)
        btn.clicked.connect(self.accept)
        bottom.addWidget(btn, 0, Qt.AlignRight)

        layout.addLayout(bottom)

    def dont_show_again_checked(self) -> bool:
        return self.chk_no_show.isChecked()
