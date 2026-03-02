from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QHBoxLayout, QPushButton, QTabWidget
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

        self.tabs = QTabWidget(self)
        self.browser_core = QTextBrowser(self)
        self.browser_truba = QTextBrowser(self)
        self.browser_generic = QTextBrowser(self)
        self.browser_core.setOpenExternalLinks(True)
        self.browser_truba.setOpenExternalLinks(True)
        self.browser_generic.setOpenExternalLinks(True)
        self.tabs.addTab(self.browser_core, t("help.library_core"))
        self.tabs.addTab(self.browser_truba, t("help.library_truba"))
        self.tabs.addTab(self.browser_generic, t("help.library_generic"))
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.btn_tour = QPushButton(t("help.start_tour"), self)
        self.btn_tour.clicked.connect(self._start_tour)
        bottom.addWidget(self.btn_tour, 0, Qt.AlignLeft)
        bottom.addStretch(1)
        btn = QPushButton(t("common.close"), self)
        btn.clicked.connect(self.accept)
        bottom.addWidget(btn, 0, Qt.AlignRight)
        layout.addLayout(bottom)

        self._reload_docs()

    def _reload_docs(self):
        lang = current_language()
        docs = (
            (self.browser_core, read_doc_text(f"HELP_{lang}.md")),
            (self.browser_truba, read_doc_text(f"HELP_LIBRARY_TRUBA_{lang}.md")),
            (self.browser_generic, read_doc_text(f"HELP_LIBRARY_GENERIC_{lang}.md")),
        )
        for browser, md in docs:
            if md:
                browser.setMarkdown(md)
            else:
                browser.setPlainText(t("help.missing_help_text"))

    def _start_tour(self):
        try:
            p = self.parent()
            if p is not None and hasattr(p, "start_quick_tour"):
                p.start_quick_tour()
            self.accept()
        except Exception:
            pass
