from __future__ import annotations

import inspect
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Lock
from typing import Callable, List

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from truba_gui.core.i18n import t


def _tr(key: str, fallback: str) -> str:
    value = t(key)
    return fallback if value == f"[{key}]" else value


@dataclass
class TransferItem:
    op: str
    src: str
    dst: str
    recursive: bool = False
    priority: str = "Normal"

    def label(self) -> str:
        name = (self.dst or self.src).rstrip("/").split("/")[-1] or (self.dst or self.src)
        return f"{self.op}: {name}"


class TransferPreflightDialog(QDialog):
    """Read-only upload plan shown before any transfer worker starts."""

    def __init__(
        self,
        parent=None,
        *,
        title: str,
        items: List[TransferItem],
        parallel_limit: int,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(
            _tr("transfer.preflight_title", "Confirm upload plan")
        )
        self._items = list(items)

        file_count = sum(item.op == "upload" for item in self._items)
        folder_count = sum(item.op == "mkdir_remote" for item in self._items)
        self.lbl_summary = QLabel(
            _tr(
                "transfer.preflight_summary",
                "{files} files, {folders} folder steps, {steps} total steps. "
                "Up to {parallel} transfers will run at once.",
            ).format(
                files=file_count,
                folders=folder_count,
                steps=len(self._items),
                parallel=parallel_limit,
            )
        )
        self.lbl_summary.setWordWrap(True)

        self.plan_list = QTreeWidget()
        self.plan_list.setColumnCount(3)
        self.plan_list.setHeaderLabels(
            [
                _tr("transfer.preflight_operation", "Operation"),
                _tr("transfer.preflight_source", "Source"),
                _tr("transfer.preflight_destination", "Destination"),
            ]
        )
        operation_labels = {
            "upload": _tr("transfer.preflight_upload", "Upload"),
            "mkdir_remote": _tr("transfer.preflight_create_folder", "Create folder"),
            "delete": _tr("transfer.preflight_delete", "Delete existing"),
        }
        for item in self._items:
            QTreeWidgetItem(
                self.plan_list,
                [
                    operation_labels.get(item.op, item.op),
                    item.src or "—",
                    item.dst or "—",
                ],
            )
        self.plan_list.resizeColumnToContents(0)
        self.plan_list.resizeColumnToContents(1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.btn_start = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.btn_start.setText(_tr("transfer.preflight_start", "Start transfer"))
        self.btn_cancel.setText(_tr("common.cancel", "Cancel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.cb_dont_ask_again = QCheckBox(
            _tr("transfer.preflight_dont_ask_again", "Don't ask again")
        )

        root = QVBoxLayout(self)
        root.addWidget(QLabel(title))
        root.addWidget(self.lbl_summary)
        root.addWidget(self.plan_list)
        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self.cb_dont_ask_again)
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.buttons)
        root.addLayout(bottom_row)
        self.resize(850, 480)


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
    _MAX_VISIBLE_LIST_ITEMS = 500

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
        self._max_parallel_limit = max(1, min(10, int(max_parallel_limit or 1)))
        self._parallel_limit = 1
        self.set_parallel_limit(parallel_limit)
        self._items: List[TransferItem] = list(items)
        self._pending: List[TransferItem] = list(items)
        self._completed: List[TransferItem] = []
        self._errors: List[tuple[TransferItem, str]] = []
        self._running = False
        self._finished_cleanly = False
        self._stopped = False
        self._cancelled = False
        self._started_at_by_item: dict[int, float] = {}
        self._item_progress_baselines: dict[int, tuple[float, float]] = {}  # item_id -> (done, time)
        self._active_item: TransferItem | None = None
        self._active_items: List[TransferItem] = []

        self.lbl_status = QLabel(self._status_text())
        self.lbl_transfer_stats = QLabel(_tr("transfer.no_active_transfer", "No active transfer."))

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
        self.btn_clear_pending = QPushButton(_tr("transfer.clear_pending", "Clear queued"))
        self.btn_retry = QPushButton(t("transfer.retry_failed"))
        self.btn_close = QPushButton(t("common.close"))
        self.btn_stop.clicked.connect(self.cancel_all)
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
            _tr(
                "transfer.parallel_hint",
                "Configured parallel transfer limit: {limit}",
            ).format(limit=self._parallel_limit)
        )
        root.addWidget(self.lbl_parallel_hint)
        root.addWidget(self.tabs)
        root.addLayout(btn_row)

        self._thread = None
        self._worker = None
        self._worker_state = {"cancelled": False, "error": ""}
        self._refresh_scheduled = False

    def set_parallel_limit(self, parallel_limit: int) -> int:
        """Set queue concurrency without exceeding the backend-safe cap."""
        requested = max(1, min(10, int(parallel_limit or 1)))
        self._parallel_limit = min(requested, self._max_parallel_limit)
        if hasattr(self, "lbl_parallel_hint"):
            self.lbl_parallel_hint.setText(
                _tr(
                    "transfer.parallel_hint",
                    "Configured parallel transfer limit: {limit}",
                ).format(limit=self._parallel_limit)
            )
        return self._parallel_limit

    def _status_text(self) -> str:
        return t("transfer.status").format(
            pending=len(self._pending),
            errors=len(self._errors),
            completed=len(self._completed),
        )

    def _refresh(self) -> None:
        self.lbl_status.setText(self._status_text())
        self.queue_list.clear()
        for item in self._pending[: self._MAX_VISIBLE_LIST_ITEMS]:
            self.queue_list.addItem(item.label())
        self._append_hidden_count(self.queue_list, len(self._pending))
        self.errors_list.clear()
        for item, err in self._errors[: self._MAX_VISIBLE_LIST_ITEMS]:
            lw = QListWidgetItem(f"{item.label()} — {err}")
            lw.setData(Qt.ItemDataRole.UserRole, item)
            self.errors_list.addItem(lw)
        self._append_hidden_count(self.errors_list, len(self._errors))
        self.completed_list.clear()
        for item in self._completed[: self._MAX_VISIBLE_LIST_ITEMS]:
            self.completed_list.addItem(item.label())
        self._append_hidden_count(self.completed_list, len(self._completed))
        self.btn_clear_pending.setEnabled(bool(self._pending))
        self.transferListsChanged.emit(
            list(self._pending),
            list(self._errors),
            list(self._completed),
        )

    def _append_hidden_count(self, view: QListWidget, total: int) -> None:
        hidden = total - self._MAX_VISIBLE_LIST_ITEMS
        if hidden > 0:
            view.addItem(f"Remaining: {hidden}")

    def _schedule_refresh(self) -> None:
        """Coalesce worker bursts into one bounded GUI update."""
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        QTimer.singleShot(50, self._run_scheduled_refresh)

    def _run_scheduled_refresh(self) -> None:
        self._refresh_scheduled = False
        self._refresh()

    def start(self) -> None:
        if self._running or self._active_items or self._active_item is not None:
            return
        if not self._items:
            self._finished_cleanly = True
            self.accept()
            return
        self._schedule_refresh()
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

    def _execute_item(self, item: TransferItem, progress_cb=None) -> None:
        if self._run_item_accepts_progress:
            self._run_item(item, progress_cb)
        else:
            self._run_item(item)

    @Slot(int, object)
    def _on_item_started(self, _index: int, item: TransferItem) -> None:
        if id(item) not in self._started_at_by_item:
            self._started_at_by_item[id(item)] = time.monotonic()
        if item not in self._active_items:
            self._active_items.append(item)
        self._active_item = self._active_items[0] if self._active_items else item
        text = _tr("transfer.active_item", "Running: {item}").format(item=item.label())
        self.lbl_transfer_stats.setText(text)
        self.transferStatsChanged.emit(text)
        try:
            self._pending.remove(item)
        except ValueError:
            pass
        self._schedule_refresh()

    @Slot(object, bool, str)
    def _on_item_finished(self, item: TransferItem, cancelled: bool, error: str) -> None:
        if item is None:
            return
        self._started_at_by_item.pop(id(item), None)
        self._item_progress_baselines.pop(id(item), None)
        if cancelled:
            self._pending.clear()
            self._running = False
            self._schedule_refresh()
            return
        if error:
            self._errors.append((item, error))
        else:
            self._completed.append(item)
        try:
            self._active_items.remove(item)
        except ValueError:
            pass
        self._active_item = self._active_items[0] if self._active_items else None
        self._schedule_refresh()

    @Slot(object, object, object)
    def _on_transfer_progress(self, item: TransferItem, done: int, total: int) -> None:
        now = time.monotonic()
        baseline = self._item_progress_baselines.get(id(item))
        if baseline is None:
            self._item_progress_baselines[id(item)] = (float(done), now)
            speed = 0.0
        else:
            baseline_done, baseline_time = baseline
            elapsed = max(0.001, now - baseline_time)
            speed = max(0.0, float(done - baseline_done) / elapsed) if done > baseline_done else 0.0

        remaining = max(0, int(total) - int(done)) if total else 0
        eta = remaining / speed if speed > 0 and total else 0

        text = _tr(
            "transfer.progress_detail",
            "{item} — {done}/{total}, {speed}, remaining {eta}",
        ).format(
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
            text = _tr("transfer.stopped_after_current", "Stopped after the current transfer.")
            self.lbl_transfer_stats.setText(text)
            self.transferStatsChanged.emit(text)
            return
        if self._cancelled:
            text = _tr("transfer.cancelled", "Transfer cancelled.")
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
        selected_items = [
            lw.data(Qt.ItemDataRole.UserRole)
            for lw in selected
            if lw.data(Qt.ItemDataRole.UserRole) is not None
        ]
        self.retry_failed_items(selected_items)

    def retry_failed_items(self, items: List[TransferItem]) -> int:
        selected_ids = {id(item) for item in items}
        if not selected_ids:
            return 0
        restored: List[TransferItem] = []
        remaining: List[tuple[TransferItem, str]] = []
        for item, err in self._errors:
            if id(item) in selected_ids:
                restored.append(item)
            else:
                remaining.append((item, err))
        if not restored:
            return 0
        self._errors = remaining
        self._pending = restored + self._pending
        self._refresh()
        if not self._running:
            self.start()
        return len(restored)

    def retry_all_errors(self) -> int:
        return self.retry_failed_items([item for item, _err in self._errors])

    def process_queue(self) -> bool:
        """Start paused queued work, without creating a duplicate worker."""
        if self._running or self._active_items or self._active_item is not None:
            return False
        if not self._pending:
            return False
        self._stopped = False
        self._cancelled = False
        self._finished_cleanly = False
        self.start()
        return True

    def set_pending_priority(self, items: List[TransferItem], priority: str) -> int:
        """Apply a stable priority order to queued transfer items only."""
        priorities = ("Highest", "High", "Normal", "Low", "Lowest")
        if priority not in priorities:
            return 0
        selected_ids = {id(item) for item in items}
        changed = 0
        for item in self._pending:
            if id(item) in selected_ids:
                item.priority = priority
                changed += 1
        order = {name: index for index, name in enumerate(priorities)}
        self._pending.sort(key=lambda item: order.get(getattr(item, "priority", "Normal"), 2))
        if self._thread is not None:
            self._thread.set_pending_priorities(items, priority)
        self._refresh()
        return changed

    def remove_pending_items(self, items: List[TransferItem]) -> int:
        selected_ids = {id(item) for item in items}
        removed = [item for item in self._pending if id(item) in selected_ids]
        if not removed:
            return 0
        if self._thread is not None:
            self._thread.remove_pending_items(removed)
        self._pending = [item for item in self._pending if id(item) not in selected_ids]
        self._refresh()
        return len(removed)

    def remove_failed_items(self, items: List[TransferItem]) -> int:
        selected_ids = {id(item) for item in items}
        before = len(self._errors)
        self._errors = [
            (item, error)
            for item, error in self._errors
            if id(item) not in selected_ids
        ]
        self._refresh()
        return before - len(self._errors)

    def clear_failed(self) -> None:
        self._errors.clear()
        self._refresh()

    def remove_completed_items(self, items: List[TransferItem]) -> int:
        selected_ids = {id(item) for item in items}
        before = len(self._completed)
        self._completed = [
            item for item in self._completed if id(item) not in selected_ids
        ]
        self._refresh()
        return before - len(self._completed)

    def clear_completed(self) -> None:
        self._completed.clear()
        self._refresh()

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
        self._items = self._normalize_recursive_transfer_plan(items)
        self._run_item = run_item
        self._parallel_limit = max(1, min(10, int(parallel_limit or 1)))
        self._cancel = False
        self._stop_after_current = False
        self._clear_pending = False
        self._removed_item_ids: set[int] = set()
        self._started_item_ids: set[int] = set()
        self._priority_by_id = {
            id(item): str(getattr(item, "priority", "Normal") or "Normal")
            for item in self._items
        }
        self._lock = Lock()

    @staticmethod
    def _normalize_recursive_transfer_plan(items: List[TransferItem]) -> List[TransferItem]:
        """Prepare all recursive directories before the bounded file phase.

        Only plans made entirely of mkdir/upload/download are normalized.
        Any mutation such as delete, move, or copy retains its original order.
        """
        plan = list(items)
        allowed = {"mkdir_remote", "mkdir_local", "upload", "download"}
        if not plan or any(item.op not in allowed for item in plan):
            return plan
        mkdirs = [item for item in plan if item.op in {"mkdir_remote", "mkdir_local"}]
        transfers = [item for item in plan if item.op in {"upload", "download"}]
        return mkdirs + transfers if mkdirs and transfers else plan

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

    def remove_pending_items(self, items: List[TransferItem]) -> None:
        with self._lock:
            self._removed_item_ids.update(id(item) for item in items)

    def set_pending_priorities(self, items: List[TransferItem], priority: str) -> None:
        """Update only work the scheduler has not submitted yet."""
        with self._lock:
            for item in items:
                item_id = id(item)
                if item_id not in self._started_item_ids:
                    self._priority_by_id[item_id] = priority

    def _priority_for(self, item: TransferItem) -> int:
        order = {"Highest": 0, "High": 1, "Normal": 2, "Low": 3, "Lowest": 4}
        with self._lock:
            value = self._priority_by_id.get(
                id(item),
                str(getattr(item, "priority", "Normal") or "Normal"),
            )
        return order.get(value, 2)

    def _prioritize_transfer_run(self, start_index: int) -> None:
        """Stably reorder only the next uninterrupted upload/download run."""
        end_index = start_index
        while (
            end_index < len(self._items)
            and self._items[end_index].op in {"upload", "download"}
        ):
            end_index += 1
        if end_index - start_index > 1:
            self._items[start_index:end_index] = sorted(
                self._items[start_index:end_index],
                key=self._priority_for,
            )

    def _state(self) -> tuple[bool, bool, bool]:
        with self._lock:
            return self._cancel, self._stop_after_current, self._clear_pending

    def _is_removed(self, item: TransferItem) -> bool:
        with self._lock:
            return id(item) in self._removed_item_ids

    def _run_one(self, item: TransferItem) -> tuple[TransferItem, bool, str]:
        try:
            def progress(done: int, total: int, current=item) -> None:
                cancel, _stop, _clear = self._state()
                if cancel:
                    raise _TransferCancelled()
                self.transfer_progress.emit(current, int(done), int(total))

            self._run_item(item, progress)
            return item, False, ""
        except _TransferCancelled:
            return (
                item,
                True,
                t("dirs.cancelled")
                if t("dirs.cancelled") != "[dirs.cancelled]"
                else "Cancelled.",
            )
        except Exception as exc:
            return item, False, str(exc)

    def _run(self) -> None:
        next_index = 0
        futures = {}
        with ThreadPoolExecutor(max_workers=self._parallel_limit) as executor:
            while next_index < len(self._items) or futures:
                cancel, stop_after_current, clear_pending = self._state()
                if cancel:
                    break
                # Directory preparation and every non-transfer operation stay
                # sequential.  In particular, an upload/download batch cannot
                # start until preceding mkdir_remote/mkdir_local items finish.
                if not futures and next_index < len(self._items):
                    item = self._items[next_index]
                    if item.op not in {"upload", "download"}:
                        next_index += 1
                        if self._is_removed(item):
                            continue
                        if stop_after_current or clear_pending:
                            break
                        self.item_started.emit(next_index, item)
                        finished_item, cancelled, error = self._run_one(item)
                        self.item_finished.emit(finished_item, cancelled, error)
                        if cancelled:
                            break
                        continue
                while (
                    next_index < len(self._items)
                    and len(futures) < self._parallel_limit
                    and not stop_after_current
                    and not clear_pending
                ):
                    self._prioritize_transfer_run(next_index)
                    item = self._items[next_index]
                    if item.op not in {"upload", "download"}:
                        # Barrier: wait for the active transfer batch before
                        # running a later mkdir or other remote mutation.
                        break
                    next_index += 1
                    if self._is_removed(item):
                        continue
                    self.item_started.emit(next_index, item)
                    with self._lock:
                        self._started_item_ids.add(id(item))
                    futures[executor.submit(self._run_one, item)] = item
                    cancel, stop_after_current, clear_pending = self._state()
                    if cancel:
                        break
                if not futures:
                    break
                done, _pending = wait(futures, return_when=FIRST_COMPLETED)
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
