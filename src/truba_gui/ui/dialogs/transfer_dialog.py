from __future__ import annotations

import inspect
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Lock
from typing import Callable, List

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
    size: int | None = None

    def label(self) -> str:
        name = (self.dst or self.src).rstrip("/").split("/")[-1] or (self.dst or self.src)
        op_label = {
            "upload": t("transfer.op_upload"),
            "download": t("transfer.op_download"),
            "download_tree": t("transfer.op_download"),
        }.get(self.op, self.op)
        return f"{op_label}: {name}"


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
                self.finished.emit(item, True, t("dirs.cancelled"))
                return
            self.progress.emit(idx, item)
            try:
                self._run_item(item)
            except Exception as exc:
                self.finished.emit(item, False, str(exc))
                return
        self.finished.emit(None, False, "")


class TransferDialog(QDialog):
    transferStatsChanged = Signal(str)
    transferListsChanged = Signal(object, object, object)
    transferProgressChanged = Signal(object, object, object)

    def __init__(
        self,
        parent=None,
        *,
        title: str,
        items: List[TransferItem],
        run_item: Callable[[TransferItem], None],
        parallel_limit: int = 1,
        max_parallel_limit: int = 10,
    ) -> None:
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle(title or t("dirs.progress_title"))
        self._run_item = run_item
        try:
            self._run_item_accepts_progress = (
                len(inspect.signature(run_item).parameters) >= 2
            )
        except (TypeError, ValueError):
            self._run_item_accepts_progress = False
        self._max_parallel_limit = max(1, min(10, int(max_parallel_limit or 10)))
        self._parallel_limit = max(
            1,
            min(self._max_parallel_limit, int(parallel_limit or 1)),
        )
        self._items: List[TransferItem] = list(items)
        self._pending: List[TransferItem] = list(items)
        self._completed: List[TransferItem] = []
        self._errors: List[tuple[TransferItem, str]] = []
        self._running = False
        self._finished_cleanly = False
        self._stopped = False
        self._cancelled = False
        self._started_at_by_item: dict[int, float] = {}
        self._active_item: TransferItem | None = None
        self._active_items: List[TransferItem] = []

        self.lbl_status = QLabel(self._status_text())
        self.lbl_transfer_stats = QLabel(t("transfer.no_active_transfer"))

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
        self.btn_clear_pending = QPushButton(t("transfer.clear_pending"))
        self.btn_retry = QPushButton(t("transfer.retry_failed"))
        self.btn_close = QPushButton(t("common.close"))
        self.btn_stop.clicked.connect(self.stop_after_current)
        self.btn_cancel.clicked.connect(self.cancel_all)
        self.btn_clear_pending.clicked.connect(self.clear_pending)
        self.btn_retry.clicked.connect(self.retry_selected_errors)
        self.btn_close.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_stop)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_clear_pending)
        btn_row.addWidget(self.btn_retry)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_close)

        root = QVBoxLayout(self)
        root.addWidget(self.lbl_status)
        root.addWidget(self.lbl_transfer_stats)
        self.lbl_parallel_hint = QLabel(
            t("transfer.parallel_hint").format(limit=self._parallel_limit)
        )
        root.addWidget(self.lbl_parallel_hint)
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
            lw = QListWidgetItem(item.label())
            lw.setData(Qt.ItemDataRole.UserRole, item)
            self.queue_list.addItem(lw)
        self.errors_list.clear()
        for item, err in self._errors:
            lw = QListWidgetItem(f"{item.label()} — {err}")
            lw.setData(Qt.ItemDataRole.UserRole, item)
            self.errors_list.addItem(lw)
        self.completed_list.clear()
        for item in self._completed:
            self.completed_list.addItem(item.label())
        self.btn_clear_pending.setEnabled(bool(self._pending))
        self.transferListsChanged.emit(
            list(self._pending),
            list(self._errors),
            list(self._completed),
        )

    def start(self) -> None:
        if not self._items:
            self._finished_cleanly = True
            self.accept()
            return
        self._refresh()
        self._thread = _WorkerThread(
            self._pending,
            self._execute_item,
            parallel_limit=self._parallel_limit,
        )
        self._thread.item_started.connect(self._on_item_started)
        self._thread.item_finished.connect(self._on_item_finished)
        self._thread.transfer_progress.connect(self._on_transfer_progress)
        self._thread.all_done.connect(self._on_all_done)
        self._thread.start()
        self._running = True

    def set_parallel_limit(self, parallel_limit: int) -> None:
        self._parallel_limit = max(
            1,
            min(self._max_parallel_limit, int(parallel_limit or 1)),
        )
        self.lbl_parallel_hint.setText(
            t("transfer.parallel_hint").format(limit=self._parallel_limit)
        )
        if self._thread is not None:
            self._thread.set_parallel_limit(self._parallel_limit)

    def _execute_item(self, item: TransferItem, progress_cb=None) -> None:
        if self._run_item_accepts_progress:
            self._run_item(item, progress_cb)
        else:
            self._run_item(item)

    @Slot(int, object)
    def _on_item_started(self, _index: int, item: TransferItem) -> None:
        self._started_at_by_item[id(item)] = time.monotonic()
        if item not in self._active_items:
            self._active_items.append(item)
        self._active_item = self._active_items[0] if self._active_items else item
        text = t("transfer.active_item").format(item=item.label())
        self.lbl_transfer_stats.setText(text)
        self.transferStatsChanged.emit(text)
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
        self._started_at_by_item.pop(id(item), None)
        try:
            self._active_items.remove(item)
        except ValueError:
            pass
        self._active_item = self._active_items[0] if self._active_items else None
        self._refresh()

    @Slot(object, object, object)
    def _on_transfer_progress(self, item: TransferItem, done: int, total: int) -> None:
        started_at = self._started_at_by_item.get(id(item), time.monotonic())
        elapsed = max(0.001, time.monotonic() - started_at)
        speed = max(0.0, float(done) / elapsed)
        remaining = max(0, int(total) - int(done)) if total else 0
        eta = remaining / speed if speed > 0 and total else 0
        text = t("transfer.progress_detail").format(
            item=item.label(),
            done=_format_size(done),
            total=_format_size(total) if total else "?",
            speed=f"{_format_size(speed)}/s",
            eta=_format_duration(eta) if total else "?",
        )
        self.lbl_transfer_stats.setText(text)
        self.transferStatsChanged.emit(text)
        self.transferProgressChanged.emit(item, done, total)

    @Slot()
    def _on_all_done(self) -> None:
        self._running = False
        self._refresh()
        if self._stopped and self._pending:
            text = t("transfer.stopped_after_current")
            self.lbl_transfer_stats.setText(text)
            self.transferStatsChanged.emit(text)
            return
        if self._cancelled:
            text = t("transfer.cancelled")
            self.lbl_transfer_stats.setText(text)
            self.transferStatsChanged.emit(text)
            return
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

    def clear_pending(self) -> None:
        self._stopped = True
        if self._thread is not None:
            self._thread.clear_pending()
        self._pending.clear()
        self._refresh()

    def remove_pending_items(self, items: List[TransferItem]) -> None:
        remove_ids = {id(item) for item in items}
        if not remove_ids:
            return
        self._pending = [item for item in self._pending if id(item) not in remove_ids]
        if self._thread is not None:
            self._thread.remove_pending_items(remove_ids)
        self._refresh()

    def finished_cleanly(self) -> bool:
        return self._finished_cleanly and not self._errors

    def reject(self) -> None:  # type: ignore[override]
        self.cancel_all()
        super().reject()


class _WorkerThread(QObject):
    item_started = Signal(int, object)
    item_finished = Signal(object, bool, str)
    transfer_progress = Signal(object, object, object)
    all_done = Signal()

    def __init__(
        self,
        items: List[TransferItem],
        run_item: Callable[[TransferItem], None],
        *,
        parallel_limit: int = 1,
    ) -> None:
        super().__init__()
        self._items = list(items)
        self._run_item = run_item
        self._parallel_limit = max(1, min(10, int(parallel_limit or 1)))
        self._cancel = False
        self._stop_after_current = False
        self._clear_pending = False
        self._removed_item_ids: set[int] = set()
        self._lock = Lock()

    def start(self) -> None:
        from threading import Thread

        Thread(target=self._run, daemon=True).start()

    @Slot()
    def stop_after_current(self) -> None:
        with self._lock:
            self._stop_after_current = True

    @Slot()
    def cancel_all(self) -> None:
        with self._lock:
            self._cancel = True
            self._stop_after_current = True
            self._clear_pending = True

    @Slot()
    def clear_pending(self) -> None:
        with self._lock:
            self._clear_pending = True
            self._stop_after_current = True

    def remove_pending_items(self, item_ids: set[int]) -> None:
        with self._lock:
            self._removed_item_ids.update(item_ids)

    @Slot(int)
    def set_parallel_limit(self, parallel_limit: int) -> None:
        with self._lock:
            self._parallel_limit = max(1, min(10, int(parallel_limit or 1)))

    def _state(self) -> tuple[bool, bool, bool, int, set[int]]:
        with self._lock:
            return (
                self._cancel,
                self._stop_after_current,
                self._clear_pending,
                self._parallel_limit,
                set(self._removed_item_ids),
            )

    def _run_one(self, item: TransferItem) -> tuple[TransferItem, bool, str]:
        try:
            def progress(done: int, total: int, current=item) -> None:
                cancel, _stop, _clear, _limit, _removed = self._state()
                if cancel:
                    raise _TransferCancelled()
                self.transfer_progress.emit(current, int(done), int(total))

            self._run_item(item, progress)
            return item, False, ""
        except _TransferCancelled:
            return (
                item,
                True,
                t("dirs.cancelled"),
            )
        except Exception as exc:
            return item, False, str(exc)

    def _run(self) -> None:
        next_index = 0
        futures = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            while next_index < len(self._items) or futures:
                cancel, stop_after_current, clear_pending, parallel_limit, removed_item_ids = self._state()
                if cancel:
                    break
                while (
                    next_index < len(self._items)
                    and len(futures) < parallel_limit
                    and not stop_after_current
                    and not clear_pending
                ):
                    item = self._items[next_index]
                    next_index += 1
                    if id(item) in removed_item_ids:
                        continue
                    self.item_started.emit(next_index, item)
                    futures[executor.submit(self._run_one, item)] = item
                    cancel, stop_after_current, clear_pending, parallel_limit, removed_item_ids = self._state()
                    if cancel:
                        break
                if not futures:
                    break
                done, _pending = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                if not done:
                    continue
                should_stop = False
                for future in done:
                    futures.pop(future, None)
                    item, cancelled, error = future.result()
                    self.item_finished.emit(item, cancelled, error)
                    if cancelled:
                        should_stop = True
                if should_stop:
                    break
        self.all_done.emit()


def _format_size(value: float) -> str:
    try:
        amount = float(value)
    except Exception:
        amount = 0.0
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while amount >= 1024 and index < len(units) - 1:
        amount /= 1024.0
        index += 1
    return f"{amount:.1f} {units[index]}" if index else f"{int(amount)} {units[index]}"


def _format_duration(seconds: float) -> str:
    try:
        remaining = max(0, int(seconds))
    except Exception:
        remaining = 0
    minutes, secs = divmod(remaining, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class _TransferCancelled(Exception):
    pass
