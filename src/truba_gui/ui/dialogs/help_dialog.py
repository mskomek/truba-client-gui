from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QHBoxLayout, QPushButton, QComboBox, QLabel
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

        top = QHBoxLayout()
        self.lbl_lib = QLabel(t("help.library_label"))
        self.cmb_lib = QComboBox(self)
        self.cmb_lib.addItem(t("help.library_core"), "core")
        self.cmb_lib.addItem(t("help.library_truba"), "truba")
        self.cmb_lib.addItem(t("help.library_generic"), "generic")
        self.cmb_lib.currentIndexChanged.connect(self._reload_doc)
        top.addWidget(self.lbl_lib)
        top.addWidget(self.cmb_lib, 1)
        layout.addLayout(top)

        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)

        layout.addWidget(self.browser, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn = QPushButton(t("common.close"), self)
        btn.clicked.connect(self.accept)
        bottom.addWidget(btn, 0, Qt.AlignRight)
        layout.addLayout(bottom)

        self._reload_doc()

    def _reload_doc(self):
        lang = current_language()
        kind = self.cmb_lib.currentData()
        if kind == "truba":
            md = read_doc_text(f"HELP_LIBRARY_TRUBA_{lang}.md")
        elif kind == "generic":
            md = read_doc_text(f"HELP_LIBRARY_GENERIC_{lang}.md")
        else:
            md = read_doc_text(f"HELP_{lang}.md")
        if md:
            self.browser.setMarkdown(md)
        else:
            self.browser.setPlainText(t("help.missing_help_text"))
