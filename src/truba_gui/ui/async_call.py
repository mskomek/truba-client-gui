from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class AsyncCallSignals(QObject):
    finished = Signal(object, object)
    failed = Signal(object, object)


class AsyncCall(QRunnable):
    def __init__(self, token: object, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.token = token
        self._fn = fn
        self.signals = AsyncCallSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:
            self.signals.failed.emit(self.token, exc)
            return
        self.signals.finished.emit(self.token, result)
