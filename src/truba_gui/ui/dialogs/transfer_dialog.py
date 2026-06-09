from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

from truba_gui.core.i18n import t


@dataclass
class TransferItem:
    op: str
    src: str
    dst: str
    recursive: bool = False

    def label(self) -> str:
        name = (self.dst or self.src).rstrip("/").split("/")[-1] or (self.dst or self.src)
        return f"{self.op}: {name}"


class _TransferWorker(QObject):
    progress = Signal(int, object)
    finished = Signal(object, bool, str)

    def __init__(self, items: List[TransferItem], run_item: Callable[[TransferItem], None]):
        super().__init__()
        self._items = list(items)
        self._run_item = run_item
        self._cancel = False

    @Slot()
    def cancel(self) -> None:
        self._cancel = True

    @Slot()
    def run(self) -> None:
        total = len(self._items)
        for idx, item in enumerate(self._items, start=1):
            if self._cancel:
                self.finished.emit(item, True, t("dirs.cancelled") if t("dirs.cancelled") != "[dirs.cancelled]" else "Cancelled.")
                return
            self.progress.emit(idx, item)
            try:
                self._run_item(item)
            except Exception as exc:
                self.finished.emit(item, False, str(exc))
                return
        self.finished.emit(None, False, "")


class TransferDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        title: str,
        items: List[TransferItem],
        run_item: Callable[[TransferItem], None],
        parallel_limit: int = 1,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title or t("dirs.progress_title"))
        self._run_item = run_item
        self._parallel_limit = max(1, min(10, int(parallel_limit or 1)))
        self._items: List[TransferItem] = list(items)
        self._pending: List[TransferItem] = list(items)
        self._completed: List[TransferItem] = []
        self._errors: List[tuple[TransferItem, str]] = []
        self._running = False
        self._finished_cleanly = False
        self._stopped = False
        self._cancelled = False

        self.lbl_status = QLabel(self._status_text())

        self.tabs = QTabWidget()
        self.queue_list = QListWidget()
        self.errors_list = QListWidget()
        self.completed_list = QListWidget()
        self.tabs.addTab(self.queue_list, t("transfer.queue_tab"))
        self.tabs.addTab(self.errors_list, t("transfer.errors_tab"))
        self.tabs.addTab(self.completed_list, t("transfer.completed_tab"))

        self.queue_list.setMinimumHeight(140)
        self.errors_list.setMinimumHeight(140)
        self.completed_list.setMinimumHeight(140)
        self.errors_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.errors_list.customContextMenuRequested.connect(self._show_errors_menu)

        self.btn_stop = QPushButton(t("transfer.stop"))
        self.btn_cancel = QPushButton(t("transfer.cancel"))
        self.btn_retry = QPushButton(t("transfer.retry_failed"))
        self.btn_close = QPushButton(t("common.close"))
        self.btn_stop.clicked.connect(self.stop_after_current)
        self.btn_cancel.clicked.connect(self.cancel_all)
        self.btn_retry.clicked.connect(self.retry_selected_errors)
        self.btn_close.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_stop)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_retry)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_close)

        root = QVBoxLayout(self)
        root.addWidget(self.lbl_status)
        root.addWidget(QLabel(t("transfer.parallel_hint").format(limit=self._parallel_limit)))
        root.addWidget(self.tabs)
        root.addLayout(btn_row)

        self._thread = None
        self._worker = None
        self._worker_state = {"cancelled": False, "error": ""}

    def _status_text(self) -> str:
        return t("transfer.status").format(
            pending=len(self._pending),
            errors=len(self._errors),
            completed=len(self._completed),
        )

    def _refresh(self) -> None:
        self.lbl_status.setText(self._status_text())
        self.queue_list.clear()
        for item in self._pending:
            self.queue_list.addItem(item.label())
        self.errors_list.clear()
        for item, err in self._errors:
            lw = QListWidgetItem(f"{item.label()} — {err}")
            lw.setData(Qt.ItemDataRole.UserRole, item)
            self.errors_list.addItem(lw)
        self.completed_list.clear()
        for item in self._completed:
            self.completed_list.addItem(item.label())

    def start(self) -> None:
        if not self._items:
            self._finished_cleanly = True
            self.accept()
            return
        self._refresh()
        self._thread = _WorkerThread(self._pending, self._execute_item)
        self._thread.item_started.connect(self._on_item_started)
        self._thread.item_finished.connect(self._on_item_finished)
        self._thread.all_done.connect(self._on_all_done)
        self._thread.start()
        self._running = True

    def _execute_item(self, item: TransferItem) -> None:
        self._run_item(item)

    @Slot(int, object)
    def _on_item_started(self, _index: int, item: TransferItem) -> None:
        try:
            self._pending.remove(item)
        except ValueError:
            pass
        self._refresh()

    @Slot(object, bool, str)
    def _on_item_finished(self, item: TransferItem, cancelled: bool, error: str) -> None:
        if item is None:
            return
        if cancelled:
            self._pending.clear()
            self._running = False
            self._refresh()
            return
        if error:
            self._errors.append((item, error))
        else:
            self._completed.append(item)
        self._refresh()

    @Slot()
    def _on_all_done(self) -> None:
        self._running = False
        self._refresh()
        if not self._errors and not self._stopped and not self._cancelled and not self._pending:
            self._finished_cleanly = True
            self.accept()

    def _show_errors_menu(self, pos) -> None:
        item = self.errors_list.itemAt(pos)
        if item is not None:
            self.errors_list.setCurrentItem(item)
        if not self.errors_list.selectedItems():
            return
        menu = QMenu(self)
        act_retry = menu.addAction(t("transfer.retry_selected"))
        chosen = menu.exec(self.errors_list.mapToGlobal(pos))
        if chosen == act_retry:
            self.retry_selected_errors()

    def retry_selected_errors(self) -> None:
        selected = self.errors_list.selectedItems()
        if not selected:
            return
        restored: List[TransferItem] = []
        remaining: List[tuple[TransferItem, str]] = []
        selected_items = {id(item) for item in (lw.data(Qt.ItemDataRole.UserRole) for lw in selected) if item is not None}
        for item, err in self._errors:
            if id(item) in selected_items:
                restored.append(item)
            else:
                remaining.append((item, err))
        if not restored:
            return
        self._errors = remaining
        self._pending = restored + self._pending
        self._refresh()
        if not self._running:
            self.start()

    def stop_after_current(self) -> None:
        self._stopped = True
        if self._thread is not None:
            self._thread.stop_after_current()

    def cancel_all(self) -> None:
        self._cancelled = True
        if self._thread is not None:
            self._thread.cancel_all()
        self._pending.clear()
        self._refresh()

    def finished_cleanly(self) -> bool:
        return self._finished_cleanly and not self._errors

    def reject(self) -> None:  # type: ignore[override]
        self.cancel_all()
        super().reject()


class _WorkerThread(QObject):
    item_started = Signal(int, object)
    item_finished = Signal(object, bool, str)
    all_done = Signal()

    def __init__(self, items: List[TransferItem], run_item: Callable[[TransferItem], None]) -> None:
        super().__init__()
        self._items = list(items)
        self._run_item = run_item
        self._cancel = False
        self._stop_after_current = False

    def start(self) -> None:
        from threading import Thread

        Thread(target=self._run, daemon=True).start()

    @Slot()
    def stop_after_current(self) -> None:
        self._stop_after_current = True

    @Slot()
    def cancel_all(self) -> None:
        self._cancel = True
        self._stop_after_current = True

    def _run(self) -> None:
        for index, item in enumerate(list(self._items), start=1):
            if self._cancel:
                self.item_finished.emit(item, True, t("dirs.cancelled") if t("dirs.cancelled") != "[dirs.cancelled]" else "Cancelled.")
                self.all_done.emit()
                return
            self.item_started.emit(index, item)
            try:
                self._run_item(item)
                self.item_finished.emit(item, False, "")
            except Exception as exc:
                self.item_finished.emit(item, False, str(exc))
            if self._stop_after_current:
                break
        self.all_done.emit()
