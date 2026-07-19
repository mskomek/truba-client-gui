from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QMenu,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from truba_gui.config.storage import (
    get_transfer_completion_action,
    get_ftp_state,
    get_ftp_transfer_type,
    set_transfer_completion_action,
    update_ftp_state,
)
from truba_gui.config.system_profile import format_remote_path, normalize_system_settings
from truba_gui.core.i18n import t
from truba_gui.services.transfer_mode import (
    ASCII,
    AUTO,
    BINARY,
    resolve_transfer_mode,
)
from truba_gui.ui.widgets.local_dir_panel import LocalDirPanel
from truba_gui.ui.widgets.remote_accordion import RemoteAccordion
from truba_gui.ui.widgets.remote_dir_panel import RemoteDirPanel


def _tr(key: str, fallback: str) -> str:
    value = t(key)
    return fallback if value == f"[{key}]" else value


class TransferActivityPanel(QGroupBox):
    _MAX_VISIBLE_TRANSFER_ROWS = 500

    _COLUMNS = [
        "Server/Local file",
        "Direction",
        "Remote file",
        "Size",
        "Progress",
        "Priority",
        "Status",
    ]
    _PROGRESS_COLUMN = 4

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._controller = None
        self._controllers: list = []
        self._controller_connections_by_id: dict[int, list[tuple[object, object]]] = {}
        self._finished_errors: list[tuple[object, str]] = []
        self._finished_completed: list = []
        self._last_status_text = _tr("transfer.no_active_transfer", "No active transfer.")
        self._progress_by_item: dict[int, int] = {}
        self.status_label = QLabel(_tr("transfer.no_active_transfer", "No active transfer."))
        self.summary_label = QLabel()
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.queue_list = self._make_transfer_table()
        self.failed_list = self._make_transfer_table()
        self.completed_list = self._make_transfer_table()
        for view in (
            self.queue_list,
            self.failed_list,
            self.completed_list,
        ):
            view.setMinimumHeight(92)
        self.tabs.addTab(self.queue_list, _tr("transfer.queue_tab", "Queue"))
        self.tabs.addTab(self.failed_list, _tr("transfer.failed_tab", "Failed"))
        self.tabs.addTab(self.completed_list, _tr("transfer.completed_tab", "Completed"))
        for view, kind in (
            (self.queue_list, "queue"),
            (self.failed_list, "failed"),
            (self.completed_list, "completed"),
        ):
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(
                lambda pos, current=view, current_kind=kind: self._show_transfer_menu(
                    current,
                    pos,
                    current_kind,
                )
            )

        self.btn_stop = QPushButton(_tr("transfer.stop", "Stop"))
        self.btn_cancel = QPushButton(_tr("transfer.cancel", "Cancel"))
        self.btn_clear_pending = QPushButton(_tr("transfer.clear_pending", "Clear queued"))
        self.btn_stop.clicked.connect(lambda: self._call_controller("cancel_all"))
        self.btn_cancel.clicked.connect(lambda: self._call_controller("cancel_all"))
        self.btn_clear_pending.clicked.connect(lambda: self._call_controller("clear_pending"))
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_stop)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_clear_pending)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.tabs)
        layout.addLayout(buttons)
        self._set_controls_enabled(False)
        self._update_summary([])
        self.retranslate_ui()

    def _make_transfer_table(self) -> QTreeWidget:
        view = QTreeWidget()
        view.setColumnCount(len(self._COLUMNS))
        view.setHeaderLabels(self._COLUMNS)
        view.setRootIsDecorated(True)
        view.setAlternatingRowColors(True)
        view.setUniformRowHeights(False)
        view.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        return view

    def retranslate_ui(self) -> None:
        self.setTitle(_tr("transfer.ftp_activity_title", "Transfers"))
        labels = (
            self._tab_label("Queued files", self.queue_list.topLevelItemCount()),
            self._tab_label("Failed transfers", self.failed_list.topLevelItemCount()),
            self._tab_label("Successful transfers", self.completed_list.topLevelItemCount()),
        )
        for index, label in enumerate(labels):
            self.tabs.setTabText(index, label)
        self.btn_stop.setText(_tr("transfer.stop", "Stop"))
        self.btn_cancel.setText(_tr("transfer.cancel", "Cancel"))
        self.btn_clear_pending.setText(_tr("transfer.clear_pending", "Clear queued"))

    @staticmethod
    def _item_label(item) -> str:
        try:
            return item.label()
        except Exception:
            dst = getattr(item, "dst", "") or getattr(item, "src", "")
            op = getattr(item, "op", "transfer")
            name = dst.rstrip("/").split("/")[-1] if dst else ""
            return f"{op}: {name or dst}"

    @staticmethod
    def _format_size(size: int) -> str:
        try:
            value = float(size)
        except Exception:
            return ""
        units = ("bytes", "KB", "MB", "GB", "TB")
        index = 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024.0
            index += 1
        if index == 0:
            return f"{int(value):,} bytes"
        return f"{value:.1f} {units[index]}"

    @classmethod
    def _item_size(cls, item) -> int:
        path = getattr(item, "src", "") if getattr(item, "op", "") == "upload" else getattr(item, "dst", "")
        try:
            from pathlib import Path

            local = Path(path)
            return local.stat().st_size if local.exists() and local.is_file() else 0
        except Exception:
            return 0

    @classmethod
    def _item_columns(cls, item, status: str) -> list[str]:
        op = getattr(item, "op", "transfer")
        src = str(getattr(item, "src", "") or "")
        dst = str(getattr(item, "dst", "") or "")
        if op == "upload":
            local_file, remote_file, direction = src, dst, "-->"
        elif op == "download":
            local_file, remote_file, direction = dst, src, "<--"
        else:
            local_file, remote_file, direction = src, dst, "->"
        return [
            local_file,
            direction,
            remote_file,
            cls._format_size(cls._item_size(item)),
            "",
            str(getattr(item, "priority", "Normal") or "Normal"),
            status,
        ]

    @staticmethod
    def _visible_transfer_items(items) -> list:
        return [
            item
            for item in list(items or [])
            if getattr(item, "op", "") in {"upload", "download"}
        ]

    @staticmethod
    def _tab_label(label: str, count: int) -> str:
        return f"{label} ({count})"

    def _update_summary(self, items: list) -> None:
        total_size = sum(self._item_size(item) for item in items)
        self.summary_label.setText(
            f"{len(items)} files. Total size: {total_size:,} bytes"
        )

    def _add_transfer_row(
        self,
        view: QTreeWidget,
        item,
        status: str,
        detail: str = "",
    ) -> QTreeWidgetItem:
        row = QTreeWidgetItem(self._item_columns(item, status))
        row.setData(0, Qt.ItemDataRole.UserRole, item)
        view.addTopLevelItem(row)
        self._install_progress_bar(view, row, item, status)
        if detail:
            child = QTreeWidgetItem(["", "", detail, "", "", "", ""])
            row.addChild(child)
            row.setExpanded(True)
        return row

    def _render_transfer_rows(
        self,
        view: QTreeWidget,
        items,
        status: str,
        detail: str = "",
    ) -> list:
        logical_items = self._visible_transfer_items(items)
        for item in logical_items[: self._MAX_VISIBLE_TRANSFER_ROWS]:
            self._add_transfer_row(view, item, status, detail)
        hidden_count = len(logical_items) - self._MAX_VISIBLE_TRANSFER_ROWS
        if hidden_count > 0:
            view.addTopLevelItem(
                QTreeWidgetItem(
                    ["", "", f"Remaining: {hidden_count}", "", "", "", ""]
                )
            )
        return logical_items

    def _progress_value(self, item, status: str) -> int:
        if status == "Successful":
            return 100
        return max(0, min(100, int(self._progress_by_item.get(id(item), 0))))

    def _install_progress_bar(
        self,
        view: QTreeWidget,
        row: QTreeWidgetItem,
        item,
        status: str,
    ) -> None:
        bar = QProgressBar(view)
        bar.setRange(0, 100)
        bar.setTextVisible(True)
        bar.setFormat("%p%")
        bar.setValue(self._progress_value(item, status))
        view.setItemWidget(row, self._PROGRESS_COLUMN, bar)

    def record(self, event: str, items: list, title: str = "") -> None:
        if event == "controller" and items:
            self.attach_controller(items[0])
            return
        if event == "queued":
            self.queue_list.clear()
            logical_items = self._render_transfer_rows(
                self.queue_list,
                items,
                "Queued",
            )
            self._update_summary(logical_items)
            self.retranslate_ui()
            self.tabs.setCurrentWidget(self.queue_list)
            return
        if event == "completed":
            self.queue_list.clear()
            self.completed_list.clear()
            self._render_transfer_rows(self.completed_list, items, "Successful")
            self._update_summary([])
            self.retranslate_ui()
            self.tabs.setCurrentWidget(self.completed_list)
            return
        if event == "failed":
            self.queue_list.clear()
            self.failed_list.clear()
            self._render_transfer_rows(self.failed_list, items, "Failed", title)
            self._update_summary([])
            self.retranslate_ui()
            self.tabs.setCurrentWidget(self.failed_list)

    def attach_controller(self, controller) -> None:
        if controller in self._controllers:
            self._controller = controller
            self._sync_lists_from_controller()
            self._update_controls()
            return

        self._controllers.append(controller)
        self._controller = controller
        connections = (
            (
                controller.transferStatsChanged,
                lambda text, current=controller: self._set_status_text(text)
                if current in self._controllers
                else None,
            ),
            (
                controller.transferListsChanged,
                lambda _pending, _errors, _completed, current=controller:
                self._sync_lists_from_controller()
                if current in self._controllers
                else None,
            ),
            (
                controller.transferProgressChanged,
                lambda item, done, total, current=controller: self._set_item_progress(
                    item, done, total
                )
                if current in self._controllers
                else None,
            ),
            (
                controller.finished,
                lambda _result, current=controller: self._on_controller_finished(current),
            ),
        )
        connected: list[tuple[object, object]] = []
        try:
            for signal, slot in connections:
                signal.connect(slot)
                connected.append((signal, slot))
        except Exception:
            for signal, slot in connected:
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            self._controllers.remove(controller)
            self._controller = self._controllers[-1] if self._controllers else None
            self._update_controls()
            return

        self._controller_connections_by_id[id(controller)] = connected
        self._sync_lists_from_controller()
        self._update_controls()

    def _detach_controller(self, controller=None) -> None:
        targets = list(self._controllers) if controller is None else [controller]
        for target in targets:
            for signal, slot in self._controller_connections_by_id.pop(id(target), []):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            try:
                self._controllers.remove(target)
            except ValueError:
                pass
        self._controller = self._controllers[-1] if self._controllers else None
        self._update_controls()

    def _on_controller_finished(self, controller) -> None:
        if controller not in self._controllers:
            return
        for item, error in list(getattr(controller, "_errors", []) or []):
            if not any(existing is item for existing, _ in self._finished_errors):
                self._finished_errors.append((item, str(error)))
        for item in list(getattr(controller, "_completed", []) or []):
            if not any(existing is item for existing in self._finished_completed):
                self._finished_completed.append(item)
        self._detach_controller(controller)
        self._sync_lists_from_controller()

    def _set_status_text(self, text: str) -> None:
        self._last_status_text = text or ""
        self.status_label.setText(self._last_status_text)
        # Progress/stat messages can arrive for every transferred chunk.  The
        # transfer-list signal handles structural changes; never rebuild the
        # bounded queue for a text-only status update.
        for index in range(self.queue_list.topLevelItemCount()):
            row = self.queue_list.topLevelItem(index)
            if row.childCount() > 0:
                row.child(0).setText(2, self._last_status_text)

    def _set_item_progress(self, item, done, total) -> None:
        try:
            total_value = int(total)
            done_value = int(done)
        except Exception:
            return
        if total_value <= 0:
            return
        self._progress_by_item[id(item)] = max(
            0,
            min(100, int(done_value * 100 / total_value)),
        )
        for index in range(self.queue_list.topLevelItemCount()):
            row = self.queue_list.topLevelItem(index)
            if row.data(0, Qt.ItemDataRole.UserRole) is not item:
                continue
            bar = self.queue_list.itemWidget(row, self._PROGRESS_COLUMN)
            if bar is not None:
                bar.setValue(self._progress_by_item[id(item)])
            break

    def _sync_lists_from_controller(self) -> None:
        pending: list = []
        errors = list(self._finished_errors)
        completed = list(self._finished_completed)
        active_items: list = []
        for controller in self._controllers:
            pending.extend(list(getattr(controller, "_pending", []) or []))
            errors.extend(list(getattr(controller, "_errors", []) or []))
            completed.extend(list(getattr(controller, "_completed", []) or []))
            controller_active = list(getattr(controller, "_active_items", []) or [])
            legacy_active = getattr(controller, "_active_item", None)
            if not controller_active and legacy_active is not None:
                controller_active = [legacy_active]
            active_items.extend(controller_active)
        self._sync_lists(pending, errors, completed, active_items)

    def _sync_lists(self, pending, errors, completed, active_items=None) -> None:
        self.queue_list.clear()
        active_items = list(active_items or [])
        active_transfers = self._visible_transfer_items(active_items)
        pending_transfers = self._visible_transfer_items(pending)
        queue_items = active_transfers + pending_transfers
        visible_active_count = min(
            len(active_transfers),
            self._MAX_VISIBLE_TRANSFER_ROWS,
        )
        for active in active_transfers[:visible_active_count]:
            self._add_transfer_row(
                self.queue_list,
                active,
                "Transferring",
                self._last_status_text,
            )
        remaining_slots = self._MAX_VISIBLE_TRANSFER_ROWS - visible_active_count
        for item in pending_transfers[:remaining_slots]:
            self._add_transfer_row(self.queue_list, item, "Queued")
        hidden_count = len(queue_items) - self._MAX_VISIBLE_TRANSFER_ROWS
        if hidden_count > 0:
            self.queue_list.addTopLevelItem(
                QTreeWidgetItem(
                    ["", "", f"Remaining: {hidden_count}", "", "", "", ""]
                )
            )
        self.failed_list.clear()
        failed_items = [
            item
            for item, _err in errors
            if getattr(item, "op", "") in {"upload", "download"}
        ]
        failed_details = {
            id(item): str(err)
            for item, err in errors
            if getattr(item, "op", "") in {"upload", "download"}
        }
        for item in failed_items[: self._MAX_VISIBLE_TRANSFER_ROWS]:
            self._add_transfer_row(
                self.failed_list,
                item,
                "Failed",
                failed_details.get(id(item), ""),
            )
        failed_hidden = len(failed_items) - self._MAX_VISIBLE_TRANSFER_ROWS
        if failed_hidden > 0:
            self.failed_list.addTopLevelItem(
                QTreeWidgetItem(
                    ["", "", f"Remaining: {failed_hidden}", "", "", "", ""]
                )
            )
        self.completed_list.clear()
        self._render_transfer_rows(self.completed_list, completed, "Successful")
        self._update_summary(queue_items)
        self.retranslate_ui()
        self._update_controls()

    def _call_controller(self, method: str, *args) -> None:
        if method in {"cancel_all", "clear_pending"}:
            handled = False
            for controller in list(self._controllers):
                action = getattr(controller, method, None)
                if callable(action):
                    action(*args)
                    handled = True
            if handled:
                return
        action = getattr(self._controller, method, None) if self._controller else None
        if callable(action):
            action(*args)
            return
        history_actions = {
            "remove_failed_items": lambda items: self._remove_history_items(
                self.failed_list,
                items,
            ),
            "clear_failed": self.failed_list.clear,
            "remove_completed_items": lambda items: self._remove_history_items(
                self.completed_list,
                items,
            ),
            "clear_completed": self.completed_list.clear,
        }
        fallback = history_actions.get(method)
        if callable(fallback):
            fallback(*args)
            self.retranslate_ui()

    def _controller_action_available(self, method: str) -> bool:
        if self._controller is not None and callable(
            getattr(self._controller, method, None)
        ):
            return True
        return method in {
            "remove_failed_items",
            "clear_failed",
            "remove_completed_items",
            "clear_completed",
        }

    @staticmethod
    def _remove_history_items(view: QTreeWidget, items: list) -> None:
        selected_ids = {id(item) for item in items}
        for index in range(view.topLevelItemCount() - 1, -1, -1):
            row = view.topLevelItem(index)
            if id(row.data(0, Qt.ItemDataRole.UserRole)) in selected_ids:
                view.takeTopLevelItem(index)

    @staticmethod
    def _selected_transfer_items(view: QTreeWidget, *, queued_only: bool = False) -> list:
        items = []
        seen: set[int] = set()
        for row in view.selectedItems():
            if row.parent() is not None:
                row = row.parent()
            if queued_only and row.text(6) != "Queued":
                continue
            item = row.data(0, Qt.ItemDataRole.UserRole)
            if item is not None and id(item) not in seen:
                seen.add(id(item))
                items.append(item)
        return items

    def _show_queue_menu(self, pos) -> None:
        self._show_transfer_menu(self.queue_list, pos, "queue")

    def _show_transfer_menu(self, view: QTreeWidget, pos, kind: str) -> None:
        menu = QMenu(self)
        selected = self._selected_transfer_items(
            view,
            queued_only=kind == "queue",
        )
        controller = self._controller
        pending = bool(getattr(controller, "_pending", []) or []) if controller else False
        running = bool(getattr(controller, "_running", False)) if controller else False
        active = bool(
            getattr(controller, "_active_items", [])
            or getattr(controller, "_active_item", None)
        ) if controller else False
        failed = bool(getattr(controller, "_errors", []) or []) if controller else False
        failed = failed or self.failed_list.topLevelItemCount() > 0
        completed = bool(getattr(controller, "_completed", []) or []) if controller else False
        completed = completed or self.completed_list.topLevelItemCount() > 0
        actions: dict[object, tuple[str, tuple]] = {}

        def add_action(
            label_key: str,
            fallback: str,
            method: str,
            *args,
            enabled: bool = True,
        ) -> None:
            action = menu.addAction(_tr(label_key, fallback))
            action.setEnabled(enabled and self._controller_action_available(method))
            if args and not args[0]:
                action.setEnabled(False)
            actions[action] = (method, args)

        def add_disabled_action(label_key: str, fallback: str, tooltip_key: str) -> None:
            action = menu.addAction(_tr(label_key, fallback))
            action.setEnabled(False)
            tooltip = _tr(tooltip_key, "Not available in this version.")
            if hasattr(action, "setToolTip"):
                action.setToolTip(tooltip)

        def add_priority_menu() -> None:
            priority_menu = menu.addMenu(
                _tr("transfer.set_priority", "Set Priority")
            )
            for priority in ("Highest", "High", "Normal", "Low", "Lowest"):
                action = priority_menu.addAction(
                    _tr(f"transfer.priority_{priority.lower()}", priority)
                )
                action.setEnabled(bool(selected) and self._controller_action_available("set_pending_priority"))
                actions[action] = ("set_pending_priority", (selected, priority))

        def add_completion_menu() -> None:
            completion_menu = menu.addMenu(
                _tr("transfer.after_completion", "Action after queue completion")
            )
            selected_action = get_transfer_completion_action()
            choices = (
                ("none", "transfer.completion_none", "None"),
                ("notification", "transfer.completion_notification", "Show notification bubble"),
                ("attention", "transfer.completion_attention", "Request attention"),
                ("close_once", "transfer.completion_close_once", "Close TrubaGUI once"),
                ("run_command", "transfer.completion_run_command", "Run command..."),
                ("play_sound", "transfer.completion_play_sound", "Play sound"),
                ("close", "transfer.completion_close", "Close TrubaGUI"),
                ("reboot_once", "transfer.completion_reboot_once", "Reboot system once"),
                ("shutdown_once", "transfer.completion_shutdown_once", "Shutdown system once"),
                ("suspend_once", "transfer.completion_suspend_once", "Suspend system once"),
            )
            for value, key, fallback in choices:
                action = completion_menu.addAction(_tr(key, fallback))
                if hasattr(action, "setCheckable"):
                    action.setCheckable(True)
                    action.setChecked(value == selected_action)
                actions[action] = ("set_completion_action", (value,))

        if kind == "queue":
            add_action(
                "transfer.process_queue",
                "Process queue",
                "process_queue",
                enabled=running or active or pending,
            )
            add_action(
                "transfer.stop_remove_all",
                "Stop and remove all",
                "cancel_all",
                enabled=running or active or pending,
            )
            menu.addSeparator()
            add_action(
                "transfer.remove_selected",
                "Remove selected",
                "remove_pending_items",
                selected,
            )
            add_disabled_action(
                "transfer.default_file_exists_action",
                "Default file exists action...",
                "transfer.unavailable_file_exists",
            )
            add_priority_menu()
            add_completion_menu()
            add_disabled_action(
                "transfer.export",
                "Export...",
                "transfer.unavailable_export",
            )
        elif kind == "failed":
            add_action(
                "transfer.retry_selected",
                "Retry selected",
                "retry_failed_items",
                selected,
            )
            add_action(
                "transfer.retry_failed",
                "Retry failed",
                "retry_all_errors",
                enabled=failed,
            )
            menu.addSeparator()
            add_action(
                "transfer.remove_selected",
                "Remove selected",
                "remove_failed_items",
                selected,
            )
            add_action(
                "transfer.clear_failed",
                "Clear failed",
                "clear_failed",
                enabled=failed,
            )
        else:
            add_action(
                "transfer.remove_selected",
                "Remove selected",
                "remove_completed_items",
                selected,
            )
            add_action(
                "transfer.clear_completed",
                "Clear completed",
                "clear_completed",
                enabled=completed,
            )

        chosen = menu.exec(view.viewport().mapToGlobal(pos))
        if chosen in actions and chosen.isEnabled():
            method, args = actions[chosen]
            if method == "set_completion_action":
                self._set_completion_action(*args)
            else:
                self._call_controller(method, *args)

    def _set_completion_action(self, action: str) -> None:
        selected = set_transfer_completion_action(action)
        observable = {"none", "notification", "attention", "play_sound"}
        if selected == "play_sound":
            QApplication.beep()
        if selected in observable:
            text = _tr(
                "transfer.completion_action_saved",
                "Completion action saved: {action}",
            ).format(action=selected)
        else:
            text = _tr(
                "transfer.completion_action_unsupported",
                "This completion action was saved but needs confirmation and is not executed.",
            )
        self._set_status_text(text)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.btn_stop.setEnabled(enabled)
        self.btn_cancel.setEnabled(enabled)
        self.btn_clear_pending.setEnabled(enabled)

    def _update_controls(self) -> None:
        if not self._controllers:
            self._set_controls_enabled(False)
            return
        pending = any(
            bool(getattr(controller, "_pending", []) or [])
            for controller in self._controllers
        )
        active = any(
            bool(
                getattr(controller, "_active_items", [])
                or getattr(controller, "_active_item", None)
            )
            for controller in self._controllers
        )
        running = any(
            bool(getattr(controller, "_running", False))
            for controller in self._controllers
        )
        self.btn_stop.setEnabled(running or active or pending)
        self.btn_cancel.setEnabled(running or active or pending)
        self.btn_clear_pending.setEnabled(pending)


class FtpWidget(QWidget):
    _ACTIVATION_DEBOUNCE_SECONDS = 1.0

    defaultPathsRequested = Signal(str, str)
    openFileRequested = Signal(str)
    submitRequested = Signal(str)
    runShellRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.session = None
        self._scratch_path = ""
        self._home_path = ""
        self._recent_activation_transfers: dict[tuple[str, str, str], float] = {}
        state = get_ftp_state()

        self.local_panel = LocalDirPanel(state["local_dir"])
        self.panel_scratch = RemoteDirPanel()
        self.panel_home = RemoteDirPanel()
        self.panel_scratch.set_transfer_mode_provider(self.current_transfer_mode)
        self.panel_home.set_transfer_mode_provider(self.current_transfer_mode)
        self.panel_scratch.set_transfer_dialog_visible(False)
        self.panel_home.set_transfer_dialog_visible(False)
        self.transfer_activity = TransferActivityPanel()
        self.panel_scratch.set_transfer_activity_callback(
            self.transfer_activity.record
        )
        self.panel_home.set_transfer_activity_callback(self.transfer_activity.record)
        self.panel_scratch.open_file.connect(self.openFileRequested)
        self.panel_home.open_file.connect(self.openFileRequested)
        self.panel_scratch.file_activated.connect(self._download_remote_path)
        self.panel_home.file_activated.connect(self._download_remote_path)
        self.panel_scratch.submit_requested.connect(self.submitRequested)
        self.panel_home.submit_requested.connect(self.submitRequested)
        self.panel_scratch.run_shell_requested.connect(self.runShellRequested)
        self.panel_home.run_shell_requested.connect(self.runShellRequested)
        self.panel_scratch.default_location_label = t("ftp.set_scratch_default")
        self.panel_home.default_location_label = t("ftp.set_home_default")
        self.panel_scratch.set_default_requested.connect(
            lambda: self.set_current_as_default("scratch")
        )
        self.panel_home.set_default_requested.connect(
            lambda: self.set_current_as_default("home")
        )
        for key, panel in (
            ("scratch", self.panel_scratch),
            ("home", self.panel_home),
        ):
            panel.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            panel.customContextMenuRequested.connect(
                lambda pos, selected=key, target=panel: self._show_default_menu(
                    selected, target, pos
                )
            )

        self.accordion = RemoteAccordion(
            [
                ("scratch", t("ftp.scratch"), self.panel_scratch),
                ("home", t("ftp.home"), self.panel_home),
            ]
        )
        self.accordion.set_active(state["active_remote"], emit=False)

        self.splitter = QSplitter()
        self.splitter.addWidget(self.local_panel)
        self.splitter.addWidget(self.accordion)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        QTimer.singleShot(0, lambda: self.splitter.setSizes(state["splitter_sizes"]))

        self.transfer_splitter = QSplitter(Qt.Orientation.Vertical)
        self.transfer_splitter.addWidget(self.splitter)
        self.transfer_splitter.addWidget(self.transfer_activity)
        self.transfer_splitter.setStretchFactor(0, 4)
        self.transfer_splitter.setStretchFactor(1, 1)

        self.mode_label = QLabel(t("ftp.transfer_type"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(t("ftp.mode_auto"), AUTO)
        self.mode_combo.addItem(t("ftp.mode_binary"), BINARY)
        self.mode_combo.addItem(t("ftp.mode_ascii"), ASCII)
        self.apply_settings()
        self.effective_label = QLabel()
        self.btn_upload = QPushButton(t("ftp.upload_selected"))
        self.btn_download = QPushButton(t("ftp.download_selected"))

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.mode_label)
        toolbar.addWidget(self.mode_combo)
        toolbar.addWidget(self.effective_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_upload)
        toolbar.addWidget(self.btn_download)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.transfer_splitter)

        self.btn_upload.clicked.connect(self.upload_selected)
        self.btn_download.clicked.connect(self.download_selected)
        self.mode_combo.currentIndexChanged.connect(self._update_effective_label)
        self.local_panel.selectionChanged.connect(self._update_effective_label)
        self.local_panel.fileActivated.connect(self._upload_local_path)
        self.local_panel.uploadRequested.connect(self._upload_local_paths)
        self.local_panel.remotePathsDropped.connect(self._download_dropped_paths)
        self.local_panel.remoteClipboardPasteRequested.connect(
            self._download_remote_clipboard_paths
        )
        self.local_panel.directoryChanged.connect(
            lambda path: update_ftp_state(local_dir=path)
        )
        self.accordion.activeChanged.connect(
            lambda key: update_ftp_state(active_remote=key)
        )
        self.splitter.splitterMoved.connect(
            lambda _position, _index: update_ftp_state(
                splitter_sizes=self.splitter.sizes()
            )
        )
        self._update_effective_label()

    def current_transfer_mode(self, _path: str = "") -> str:
        return str(self.mode_combo.currentData() or AUTO)

    def active_remote_panel(self) -> RemoteDirPanel:
        return (
            self.panel_home
            if self.accordion.active_key == "home"
            else self.panel_scratch
        )

    @staticmethod
    def _selected_remote_paths(panel: RemoteDirPanel) -> list[str]:
        current = panel.tabs.currentWidget()
        for key, view in panel.views.items():
            if view is current:
                return panel.selected_paths(key)
        return panel.selected_paths()

    def _update_effective_label(self) -> None:
        requested = self.current_transfer_mode()
        paths = self.local_panel.selected_paths()
        sample_path = paths[0] if len(paths) == 1 else ""
        try:
            effective = resolve_transfer_mode(sample_path, requested)
        except ValueError:
            effective = BINARY
        label = {
            AUTO: t("ftp.mode_auto"),
            BINARY: t("ftp.mode_binary"),
            ASCII: t("ftp.mode_ascii"),
        }.get(effective, effective)
        self.effective_label.setText(t("ftp.effective_type").format(mode=label))

    def apply_settings(self) -> None:
        mode = get_ftp_transfer_type()
        index = self.mode_combo.findData(mode)
        self.mode_combo.setCurrentIndex(max(0, index))
        if hasattr(self, "effective_label"):
            self._update_effective_label()

    def _update_remote_titles(self) -> None:
        scratch_title = t("ftp.scratch")
        home_title = t("ftp.home")
        if self._scratch_path:
            scratch_title += f" — {self._scratch_path}"
        if self._home_path:
            home_title += f" — {self._home_path}"
        self.accordion.set_title("scratch", scratch_title)
        self.accordion.set_title("home", home_title)

    def _show_default_menu(self, key: str, panel: RemoteDirPanel, pos) -> None:
        if not self.session or not self.session.get("profile_name"):
            return
        menu = QMenu(self)
        action = menu.addAction(
            t("ftp.set_scratch_default")
            if key == "scratch"
            else t("ftp.set_home_default")
        )
        chosen = menu.exec(panel.mapToGlobal(pos))
        if chosen != action or not panel.current_dir:
            return
        self.set_current_as_default(key)

    def set_current_as_default(self, key: str) -> bool:
        panel = self.panel_scratch if key == "scratch" else self.panel_home
        if (
            key not in {"scratch", "home"}
            or not self.session
            or not self.session.get("profile_name")
            or not panel.current_dir
        ):
            return False
        scratch = panel.current_dir if key == "scratch" else self._scratch_path
        home = panel.current_dir if key == "home" else self._home_path
        self.defaultPathsRequested.emit(scratch, home)
        return True

    def set_session(self, session) -> None:
        self.session = session
        self.panel_scratch.set_session(session)
        self.panel_home.set_session(session)
        if not session or not session.get("connected"):
            return
        cfg = session.get("cfg")
        user = getattr(cfg, "username", "") or "user"
        system = normalize_system_settings(getattr(cfg, "system_settings", None))
        scratch = format_remote_path(system["scratch_dir"], user)
        home = format_remote_path(system["home_dir"], user)
        self._scratch_path = scratch
        self._home_path = home
        self.panel_scratch.title = scratch
        self.panel_scratch.lbl.setText(scratch)
        self.panel_home.title = home
        self.panel_home.lbl.setText(home)
        self._update_remote_titles()
        self.panel_scratch.set_dir(scratch)
        self.panel_home.set_dir(home)

    def upload_selected(self) -> bool:
        paths = self.local_panel.selected_paths()
        panel = self.active_remote_panel()
        if not paths:
            QMessageBox.information(self, t("common.info"), t("ftp.no_local_selection"))
            return False
        if not self.session or not self.session.get("connected") or not panel.current_dir:
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return False
        try:
            return panel._apply_local_upload_incremental(paths, panel.current_dir)
        finally:
            self.apply_settings()

    def _upload_local_path(self, path: str) -> None:
        panel = self.active_remote_panel()
        if self._is_repeated_activation_transfer("upload", path, panel.current_dir):
            return
        self._upload_local_paths([path])

    def _upload_local_paths(self, paths: list[str]) -> None:
        panel = self.active_remote_panel()
        clean_paths = [path for path in paths if path]
        if not clean_paths or not self.session or not self.session.get("connected") or not panel.current_dir:
            return
        try:
            panel._apply_local_upload_incremental(clean_paths, panel.current_dir)
        finally:
            self.apply_settings()

    def download_selected(self) -> bool:
        panel = self.active_remote_panel()
        paths = self._selected_remote_paths(panel)
        if not paths:
            QMessageBox.information(self, t("common.info"), t("ftp.no_remote_selection"))
            return False
        if not self.session or not self.session.get("connected"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return False
        try:
            return panel._apply_remote_download_incremental(
                paths,
                self.local_panel.current_dir,
            )
        finally:
            self.apply_settings()

    def _download_remote_path(self, path: str) -> None:
        panel = self.active_remote_panel()
        if not path or not self.session or not self.session.get("connected"):
            return
        if self._is_repeated_activation_transfer("download", path, self.local_panel.current_dir):
            return
        try:
            panel._apply_remote_download_incremental(
                [path],
                self.local_panel.current_dir,
            )
        finally:
            self.apply_settings()

    def _is_repeated_activation_transfer(
        self,
        op: str,
        src: str,
        dst_dir: str,
    ) -> bool:
        key = (op, str(src or ""), str(dst_dir or ""))
        now = monotonic()
        cutoff = now - self._ACTIVATION_DEBOUNCE_SECONDS
        self._recent_activation_transfers = {
            recent_key: timestamp
            for recent_key, timestamp in self._recent_activation_transfers.items()
            if timestamp >= cutoff
        }
        previous = self._recent_activation_transfers.get(key)
        self._recent_activation_transfers[key] = now
        return previous is not None and now - previous < self._ACTIVATION_DEBOUNCE_SECONDS

    def _download_dropped_paths(self, paths: list[str], source_panel_id: str) -> None:
        panel = RemoteDirPanel._instances.get(source_panel_id)
        if panel is None or panel not in (self.panel_scratch, self.panel_home):
            QMessageBox.warning(self, t("common.error"), t("ftp.invalid_drop"))
            return
        panel._apply_remote_download_incremental(
            paths,
            self.local_panel.current_dir,
        )

    def _download_remote_clipboard_paths(
        self,
        paths: list[str],
        target_dir: str,
    ) -> None:
        panel = self.active_remote_panel()
        clean_paths = [path for path in paths if path]
        if not clean_paths or not self.session or not self.session.get("connected"):
            return
        try:
            panel._apply_remote_download_incremental(clean_paths, target_dir)
        finally:
            self.apply_settings()

    def retranslate_ui(self) -> None:
        self.local_panel.retranslate_ui()
        self.mode_label.setText(t("ftp.transfer_type"))
        for index, key in enumerate(("mode_auto", "mode_binary", "mode_ascii")):
            self.mode_combo.setItemText(index, t(f"ftp.{key}"))
        self.btn_upload.setText(t("ftp.upload_selected"))
        self.btn_download.setText(t("ftp.download_selected"))
        self.transfer_activity.retranslate_ui()
        self._update_remote_titles()
        self.panel_scratch.retranslate_ui()
        self.panel_home.retranslate_ui()
        self.panel_scratch.default_location_label = t("ftp.set_scratch_default")
        self.panel_home.default_location_label = t("ftp.set_home_default")
        self._update_effective_label()

    def shutdown(self) -> None:
        self.panel_scratch.shutdown()
        self.panel_home.shutdown()
