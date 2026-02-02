from PySide6.QtWidgets import QMainWindow
from truba_gui.core.i18n import t
from truba_gui.ui.widgets.login_widget import LoginWidget
from truba_gui.ui.main_window import MainWindow

class ConnectionWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{t('app.title')} - {t('tabs.login')}")
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
