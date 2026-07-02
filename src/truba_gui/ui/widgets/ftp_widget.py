from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
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
    get_ftp_state,
    get_ftp_transfer_type,
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
        self.queue_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_list.customContextMenuRequested.connect(self._show_queue_menu)

        self.btn_stop = QPushButton(_tr("transfer.stop", "Stop"))
        self.btn_cancel = QPushButton(_tr("transfer.cancel", "Cancel"))
        self.btn_clear_pending = QPushButton(_tr("transfer.clear_pending", "Clear queued"))
        self.btn_stop.clicked.connect(lambda: self._call_controller("stop_after_current"))
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
            "Normal",
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
            visible_items = self._visible_transfer_items(items)
            for item in visible_items:
                self._add_transfer_row(self.queue_list, item, "Queued")
            self._update_summary(visible_items)
            self.retranslate_ui()
            self.tabs.setCurrentWidget(self.queue_list)
            return
        if event == "completed":
            self.queue_list.clear()
            for item in self._visible_transfer_items(items):
                self._add_transfer_row(self.completed_list, item, "Successful")
            self._update_summary([])
            self.retranslate_ui()
            self.tabs.setCurrentWidget(self.completed_list)
            return
        if event == "failed":
            self.queue_list.clear()
            for item in self._visible_transfer_items(items):
                self._add_transfer_row(self.failed_list, item, "Failed", title)
            self._update_summary([])
            self.retranslate_ui()
            self.tabs.setCurrentWidget(self.failed_list)

    def attach_controller(self, controller) -> None:
        self._controller = controller
        self._set_controls_enabled(True)
        try:
            controller.transferStatsChanged.connect(self._set_status_text)
            controller.transferListsChanged.connect(self._sync_lists)
            controller.transferProgressChanged.connect(self._set_item_progress)
            controller.finished.connect(lambda _result: self._set_controls_enabled(False))
        except Exception:
            pass

    def _set_status_text(self, text: str) -> None:
        self._last_status_text = text or ""
        self.status_label.setText(self._last_status_text)
        self._sync_lists_from_controller()

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
        self._sync_lists_from_controller()

    def _sync_lists_from_controller(self) -> None:
        if self._controller is None:
            return
        pending = list(getattr(self._controller, "_pending", []) or [])
        errors = list(getattr(self._controller, "_errors", []) or [])
        completed = list(getattr(self._controller, "_completed", []) or [])
        self._sync_lists(pending, errors, completed)

    def _sync_lists(self, pending, errors, completed) -> None:
        self.queue_list.clear()
        active_items = list(getattr(self._controller, "_active_items", []) or [])
        legacy_active = getattr(self._controller, "_active_item", None)
        if not active_items and legacy_active is not None:
            active_items = [legacy_active]
        queue_items = []
        for active in self._visible_transfer_items(active_items):
            queue_items.append(active)
            self._add_transfer_row(
                self.queue_list,
                active,
                "Transferring",
                self._last_status_text,
            )
        for item in self._visible_transfer_items(pending):
            queue_items.append(item)
            self._add_transfer_row(self.queue_list, item, "Queued")
        self.failed_list.clear()
        for item, err in errors:
            if getattr(item, "op", "") in {"upload", "download"}:
                self._add_transfer_row(self.failed_list, item, "Failed", str(err))
        self.completed_list.clear()
        for item in self._visible_transfer_items(completed):
            self._add_transfer_row(self.completed_list, item, "Successful")
        self._update_summary(queue_items)
        self.retranslate_ui()

    def _call_controller(self, method: str) -> None:
        if self._controller is None:
            return
        action = getattr(self._controller, method, None)
        if callable(action):
            action()

    def _show_queue_menu(self, pos) -> None:
        menu = QMenu(self)
        act_process = menu.addAction("Process Queue")
        act_process.setCheckable(True)
        act_process.setChecked(bool(self._controller))
        act_stop_remove = menu.addAction("Stop and remove all")
        menu.addSeparator()
        act_remove_selected = menu.addAction("Remove selected")
        act_default_exists = menu.addAction("Default file exists action...")
        act_priority = menu.addMenu("Set Priority")
        act_priority.addAction("Highest").setEnabled(False)
        act_priority.addAction("High").setEnabled(False)
        act_priority.addAction("Normal").setEnabled(False)
        act_priority.addAction("Low").setEnabled(False)
        act_after = menu.addMenu("Action after queue completion")
        act_after.addAction("None").setEnabled(False)
        act_export = menu.addAction("Export...")
        act_default_exists.setEnabled(False)
        act_export.setEnabled(False)
        chosen = menu.exec(self.queue_list.viewport().mapToGlobal(pos))
        if chosen == act_stop_remove:
            self._call_controller("cancel_all")
        elif chosen == act_remove_selected:
            self._call_controller("clear_pending")

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.btn_stop.setEnabled(enabled)
        self.btn_cancel.setEnabled(enabled)
        self.btn_clear_pending.setEnabled(enabled)


class FtpWidget(QWidget):
    _ACTIVATION_DEBOUNCE_SECONDS = 1.0

    defaultPathsRequested = Signal(str, str)
    openFileRequested = Signal(str)
    submitRequested = Signal(str)

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
            return panel._apply_local_upload(paths, panel.current_dir)
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
            panel._apply_local_upload(clean_paths, panel.current_dir)
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
            return panel._apply_remote_download(paths, self.local_panel.current_dir)
        finally:
            self.apply_settings()

    def _download_remote_path(self, path: str) -> None:
        panel = self.active_remote_panel()
        if not path or not self.session or not self.session.get("connected"):
            return
        if self._is_repeated_activation_transfer("download", path, self.local_panel.current_dir):
            return
        try:
            panel._apply_remote_download([path], self.local_panel.current_dir)
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
        panel._apply_remote_download(paths, self.local_panel.current_dir)

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
            panel._apply_remote_download(clean_paths, target_dir)
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
