from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit

from truba_gui.services.command_history_store import get_global_history_store


class TerminalInput(QLineEdit):
    """A single-line command input with ↑/↓ history navigation.

    - Enter submits
    - Up/Down navigates command history
    - History persists to disk (jsonl)

    IMPORTANT: Do not use this for password input.
    """

    command_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Shared history store (single backing file) + per-widget navigation cursor.
        self.history = get_global_history_store()
        self._hist_index = len(self.history.items)
        self.setPlaceholderText("Komut gir (↑/↓ geçmiş, Enter çalıştır)")
        self.setClearButtonEnabled(True)

    def submit_current(self) -> None:
        cmd = (self.text() or "").strip()
        if not cmd:
            return
        self.history.add(cmd)
        # Reset navigation cursor after adding.
        self._hist_index = len(self.history.items)
        self.command_submitted.emit(cmd)
        self.clear()

    def _history_prev(self) -> str:
        if not self.history.items:
            return ""
        self._hist_index = max(0, self._hist_index - 1)
        return self.history.items[self._hist_index]

    def _history_next(self) -> str:
        if not self.history.items:
            return ""
        self._hist_index = min(len(self.history.items), self._hist_index + 1)
        if self._hist_index == len(self.history.items):
            return ""
        return self.history.items[self._hist_index]

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key_Up:
            self.setText(self._history_prev())
            self.end(False)
            return
        if k == Qt.Key_Down:
            self.setText(self._history_next())
            self.end(False)
            return
        if k in (Qt.Key_Return, Qt.Key_Enter):
            self.submit_current()
            return
        super().keyPressEvent(event)
