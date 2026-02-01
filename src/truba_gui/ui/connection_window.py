from PySide6.QtWidgets import QMainWindow
from core.i18n import t
from ui.widgets.login_widget import LoginWidget
from ui.main_window import MainWindow

class ConnectionWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("app.title") + " - " + t("tabs.login") if t("tabs.login") != "[tabs.login]" else "Bağlantı")
        self.login = LoginWidget()
        self.setCentralWidget(self.login)

        self._main = None
        self.login.session_changed.connect(self.on_session_changed)

    def on_session_changed(self, session: dict):
        # open main window and hide connection window
        self._main = MainWindow(session=session, connection_window=self)
        self._main.show()
        self.hide()

    def show_again(self):
        # called when main window closes, to allow reconnect
        self.show()
        self.raise_()
        self.activateWindow()
