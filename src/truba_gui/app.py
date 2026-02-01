import sys
from PySide6.QtWidgets import QApplication

from truba_gui.core.i18n import load_language
from truba_gui.ui.main_window import MainWindow

def main() -> int:
    app = QApplication(sys.argv)
    load_language("tr")

    w = MainWindow()
    w.show()
    return app.exec()
