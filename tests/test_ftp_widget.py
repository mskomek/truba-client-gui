from __future__ import annotations

import os
import stat
import tempfile
import threading
import time
import unittest
import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit, QMessageBox

from truba_gui.services.files_mock import MockFilesBackend
from truba_gui.services.transfer_mode import (
    ASCII,
    AUTO,
    BINARY,
    _ascii_bytes_for_local,
    _ascii_bytes_for_remote,
    download_with_mode,
    resolve_transfer_mode,
    upload_with_mode,
)
from truba_gui.config.system_profile import (
    TRUBA_SYSTEM_DEFAULTS,
    save_user_system_template,
)
from truba_gui.ui.dialogs.connection_dialog import ConnectionDialog
from truba_gui.ui.dialogs.transfer_conflict_dialog import (
    TransferConflictDecision,
    TransferConflictDialog,
    TransferConflictInfo,
)
from truba_gui.ui.dialogs.transfer_dialog import (
    TransferDialog,
    TransferItem,
    TransferPreflightDialog,
)
from truba_gui.ui.dialogs.settings_dialog import SettingsDialog
from truba_gui.ui.main_window import MainWindow
from truba_gui.ui.widgets.directories_widget import DirectoriesWidget, _ShellRunWorker
from truba_gui.ui.widgets.ftp_widget import FtpWidget
from truba_gui.ui.widgets.local_dir_panel import LOCAL_CONTEXT_MENU_LABELS
from truba_gui.ui.widgets.login_widget import (
    FTP_TEST_MODE_ENV,
    LoginWidget,
    is_ftp_mock_host,
    is_ftp_test_mode_enabled,
)
from truba_gui.ui.widgets.remote_dir_panel import (
    DIRECTORY_CACHE_TTL_SECONDS,
    MIME_REMOTE_PATHS,
    REMOTE_CONTEXT_MENU_LABELS,
    RemoteDirPanel,
    _DragPayload,
    _PlannedOp,
    _PermissionsDialog,
    _encode_payload,
)
from truba_gui.services.files_base import RemoteEntry
from truba_gui.services.files_ssh import SSHFilesBackend
from truba_gui.core.i18n import load_language


class _Files:
    def __init__(self) -> None:
        self.remote: dict[str, bytes] = {}

    def listdir_entries(self, _path: str):
        return [
            RemoteEntry(
                name=Path(path).name,
                path=path,
                is_dir=False,
                size=len(data),
                mtime=1,
            )
            for path, data in self.remote.items()
        ]

    def exists(self, path: str) -> bool:
        return path in self.remote

    def is_dir(self, _path: str) -> bool:
        return False

    def upload(self, local_path: str, remote_path: str) -> None:
        self.remote[remote_path] = Path(local_path).read_bytes()

    def download(self, remote_path: str, local_path: str) -> None:
        Path(local_path).write_bytes(self.remote[remote_path])

    def stat(self, remote_path: str):
        data = self.remote.get(remote_path, b"")
        return len(data), 1

    def rename(self, old_path: str, new_path: str) -> None:
        self.remote[new_path] = self.remote.pop(old_path, b"")


class _CountingFiles:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.dirs = {"/remote", "/remote/child"}
        self.entries = {
            "/remote": [
                RemoteEntry("child", "/remote/child", True, 0, 1),
                RemoteEntry("root.txt", "/remote/root.txt", False, 4, 1),
            ],
            "/remote/child": [
                RemoteEntry("nested.txt", "/remote/child/nested.txt", False, 6, 1),
            ],
        }

    def listdir_entries(self, path: str):
        key = (path or "/").rstrip("/") or "/"
        self.calls.append(key)
        return list(self.entries.get(key, []))

    def exists(self, path: str) -> bool:
        key = (path or "/").rstrip("/") or "/"
        return key in self.dirs

    def is_dir(self, path: str) -> bool:
        key = (path or "/").rstrip("/") or "/"
        return key in self.dirs


class _ResumableFiles:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls: list[str] = []

    def download(self, _remote_path: str, local_path: str, progress_cb=None) -> None:
        self.calls.append(local_path)
        existing = Path(local_path).read_bytes() if Path(local_path).exists() else b""
        Path(local_path).write_bytes(existing + self.data[len(existing):])
        if progress_cb is not None:
            progress_cb(len(self.data), len(self.data))


class _ProgressUploadFiles:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def upload(self, local_path: str, remote_path: str, progress_cb=None) -> None:
        self.calls.append((local_path, remote_path))
        size = Path(local_path).stat().st_size
        if progress_cb is not None:
            progress_cb(size, size)


class _DropPosition:
    def toPoint(self) -> QPoint:
        return QPoint(0, 0)


class _FakeDropEvent:
    def __init__(self, mime: QMimeData, pos: QPoint | None = None) -> None:
        self._mime = mime
        self._pos = pos or QPoint(0, 0)
        self.accepted = False
        self.ignored = False

    def mimeData(self) -> QMimeData:
        return self._mime

    def position(self) -> _DropPosition:
        return _DropPosition()

    def pos(self) -> QPoint:
        return self._pos

    def acceptProposedAction(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class FtpWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        load_language("en")

    def setUp(self) -> None:
        self.state_patch = patch(
            "truba_gui.ui.widgets.ftp_widget.get_ftp_state",
            return_value={
                "local_dir": os.getcwd(),
                "active_remote": "scratch",
                "splitter_sizes": [500, 500],
            },
        )
        self.type_patch = patch(
            "truba_gui.ui.widgets.ftp_widget.get_ftp_transfer_type",
            return_value=AUTO,
        )
        self.update_patch = patch(
            "truba_gui.ui.widgets.ftp_widget.update_ftp_state",
            return_value={},
        )
        self.state_patch.start()
        self.type_patch.start()
        self.update_patch.start()
        self.widget = FtpWidget()

    @staticmethod
    def _run_plan_synchronously(
        panel: RemoteDirPanel,
        plan,
        _title: str,
        after_finished=None,
        *,
        confirm_before_start: bool = False,
    ) -> bool:
        for item in plan:
            panel._execute_transfer_item(
                SimpleNamespace(
                    op=item.op,
                    src=item.src,
                    dst=item.dst,
                    recursive=item.recursive,
                )
            )
        if after_finished is not None:
            after_finished()
        return True

    def tearDown(self) -> None:
        from truba_gui.services.file_clipboard import get_file_clipboard

        QApplication.processEvents()
        self.widget.shutdown()
        get_file_clipboard().clear()
        self.widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
        self.update_patch.stop()
        self.type_patch.stop()
        self.state_patch.stop()

    def test_layout_and_exclusive_remote_sections(self) -> None:
        self.assertEqual(self.widget.splitter.count(), 2)
        self.assertEqual(self.widget.accordion.active_key, "scratch")
        self.widget.accordion.set_active("home")
        self.assertEqual(self.widget.active_remote_panel(), self.widget.panel_home)
        self.assertFalse(self.widget.panel_scratch.isVisible())

    def test_bottom_transfer_activity_tabs_are_visible(self) -> None:
        tabs = self.widget.transfer_activity.tabs
        self.assertEqual(tabs.tabPosition(), tabs.TabPosition.South)
        self.assertEqual(
            [tabs.tabText(index) for index in range(tabs.count())],
            ["Queued files (0)", "Failed transfers (0)", "Successful transfers (0)"],
        )
        self.assertEqual(
            [
                self.widget.transfer_activity.queue_list.headerItem().text(index)
                for index in range(self.widget.transfer_activity.queue_list.columnCount())
            ],
            [
                "Server/Local file",
                "Direction",
                "Remote file",
                "Size",
                "Progress",
                "Priority",
                "Status",
            ],
        )

    def test_transfer_activity_records_queue_failed_and_completed(self) -> None:
        item = SimpleNamespace(op="upload", src="a.txt", dst="/remote/a.txt")

        self.widget.transfer_activity.record("queued", [item], "Upload")
        self.assertEqual(self.widget.transfer_activity.queue_list.topLevelItemCount(), 1)
        self.assertEqual(
            self.widget.transfer_activity.queue_list.topLevelItem(0).text(1),
            "-->",
        )

        self.widget.transfer_activity.record("failed", [item], "Upload")
        self.assertEqual(self.widget.transfer_activity.failed_list.topLevelItemCount(), 1)

        self.widget.transfer_activity.record("completed", [item], "Upload")
        self.assertEqual(self.widget.transfer_activity.completed_list.topLevelItemCount(), 1)

    def test_multi_folder_download_queue_caps_rows_without_truncating_plan(self) -> None:
        items = [
            TransferItem(
                "download",
                f"/remote/folder-{index % 2}/file-{index}.bin",
                f"file-{index}.bin",
            )
            for index in range(5)
        ]
        dialog = TransferDialog(
            title="Download",
            items=items,
            run_item=lambda _item, _progress=None: None,
        )
        try:
            with patch.object(
                self.widget.transfer_activity,
                "_MAX_VISIBLE_TRANSFER_ROWS",
                3,
            ):
                self.widget.transfer_activity.record(
                    "controller",
                    [dialog],
                    "Download",
                )

            self.assertEqual(len(dialog._items), 5)
            self.assertEqual(len(dialog._pending), 5)
            self.assertEqual(
                self.widget.transfer_activity.queue_list.topLevelItemCount(),
                4,
            )
            info_row = self.widget.transfer_activity.queue_list.topLevelItem(3)
            self.assertEqual(info_row.text(2), "Remaining: 2")
            self.assertIsNone(
                self.widget.transfer_activity.queue_list.itemWidget(info_row, 4)
            )
            self.assertIn(
                "5 files.",
                self.widget.transfer_activity.summary_label.text(),
            )
        finally:
            dialog.deleteLater()

    def test_transfer_activity_attaches_controller_without_popup(self) -> None:
        dialog = TransferDialog(
            title="Download",
            items=[TransferItem("download", "/remote/a.txt", "a.txt")],
            run_item=lambda _item, _progress=None: None,
        )
        try:
            self.widget.transfer_activity.record("controller", [dialog], "Download")
            self.assertTrue(self.widget.transfer_activity.btn_cancel.isEnabled())
            dialog.transferStatsChanged.emit("speed 1 KB/s remaining 0:10")
            self.assertEqual(
                self.widget.transfer_activity.status_label.text(),
                "speed 1 KB/s remaining 0:10",
            )
            dialog.transferListsChanged.emit(
                [TransferItem("download", "/remote/a.txt", "a.txt")],
                [],
                [],
            )
            self.assertEqual(self.widget.transfer_activity.queue_list.topLevelItemCount(), 1)
            with patch.object(dialog, "clear_pending") as clear_pending:
                self.widget.transfer_activity.btn_clear_pending.click()
            clear_pending.assert_called_once()
        finally:
            dialog.deleteLater()

    def test_transfer_activity_buttons_route_to_live_controller(self) -> None:
        dialog = TransferDialog(
            title="Download",
            items=[TransferItem("download", "/remote/a.txt", "a.txt")],
            run_item=lambda _item, _progress=None: None,
        )
        try:
            dialog._running = True
            self.widget.transfer_activity.attach_controller(dialog)
            with patch.object(dialog, "cancel_all") as cancel:
                self.widget.transfer_activity.btn_stop.click()
                self.widget.transfer_activity.btn_cancel.click()
            with patch.object(dialog, "clear_pending") as clear:
                self.widget.transfer_activity.btn_clear_pending.click()
            self.assertEqual(cancel.call_count, 2)
            clear.assert_called_once()
        finally:
            dialog.deleteLater()

    def test_transfer_dialog_process_queue_starts_only_when_no_worker_is_active(self) -> None:
        dialog = TransferDialog(
            title="Download",
            items=[TransferItem("download", "/remote/a.txt", "a.txt")],
            run_item=lambda _item, _progress=None: None,
        )
        try:
            dialog._running = True
            with patch.object(dialog, "start") as start:
                self.assertFalse(dialog.process_queue())
            start.assert_not_called()

            dialog._running = False
            dialog._active_items = []
            dialog._active_item = None
            dialog._stopped = True
            dialog._cancelled = True
            with patch.object(dialog, "start") as start:
                self.assertTrue(dialog.process_queue())
            start.assert_called_once()
            self.assertFalse(dialog._stopped)
            self.assertFalse(dialog._cancelled)
        finally:
            dialog.deleteLater()

    def test_transfer_activity_process_queue_context_routes_to_controller(self) -> None:
        dialog = TransferDialog(
            title="Download",
            items=[TransferItem("download", "/remote/a.txt", "a.txt")],
            run_item=lambda _item, _progress=None: None,
        )

        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

            def isEnabled(self) -> bool:
                return self.enabled

            def setCheckable(self, _checked: bool) -> None:
                pass

            def setChecked(self, _checked: bool) -> None:
                pass

        class FakeMenu:
            def __init__(self, _parent=None) -> None:
                self.actions = []

            def addAction(self, text: str):
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                pass

            def addMenu(self, _text: str):
                return self

            def exec(self, _pos):
                return self.actions[0]

        try:
            panel = self.widget.transfer_activity
            panel.attach_controller(dialog)
            with patch.object(dialog, "process_queue") as process, patch(
                "truba_gui.ui.widgets.ftp_widget.QMenu",
                FakeMenu,
            ):
                panel._show_queue_menu(QPoint(0, 0))
            process.assert_called_once()
        finally:
            dialog.deleteLater()

    def test_transfer_activity_queue_context_removes_only_selected_row(self) -> None:
        items = [
            TransferItem("download", f"/remote/{name}.txt", f"{name}.txt")
            for name in ("a", "b", "c")
        ]
        dialog = TransferDialog(
            title="Download",
            items=items,
            run_item=lambda _item, _progress=None: None,
        )

        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

            def isEnabled(self) -> bool:
                return self.enabled

            def setCheckable(self, _checked: bool) -> None:
                pass

            def setChecked(self, _checked: bool) -> None:
                pass

        class FakeMenu:
            def __init__(self, _parent=None) -> None:
                self.actions = []

            def addAction(self, text: str):
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                pass

            def addMenu(self, _text: str):
                return self

            def exec(self, _pos):
                return self.actions[2]

        try:
            panel = self.widget.transfer_activity
            panel.attach_controller(dialog)
            panel.queue_list.topLevelItem(1).setSelected(True)
            with patch("truba_gui.ui.widgets.ftp_widget.QMenu", FakeMenu):
                panel._show_queue_menu(QPoint(0, 0))

            self.assertEqual(dialog._pending, [items[0], items[2]])
            self.assertEqual(panel.queue_list.topLevelItemCount(), 2)
        finally:
            dialog.deleteLater()

    def test_transfer_queue_menu_matches_filezilla_structure(self) -> None:
        load_language("en")
        dialog = TransferDialog(
            title="Download",
            items=[TransferItem("download", "/remote/a.txt", "a.txt")],
            run_item=lambda _item, _progress=None: None,
        )

        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True
                self.tooltip = ""

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

            def isEnabled(self) -> bool:
                return self.enabled

            def setToolTip(self, tooltip: str) -> None:
                self.tooltip = tooltip

            def setCheckable(self, _value: bool) -> None:
                pass

            def setChecked(self, _value: bool) -> None:
                pass

        class FakeMenu:
            instance = None

            def __init__(self, _parent=None, text: str = "") -> None:
                self.text = text
                self.entries = []
                if FakeMenu.instance is None:
                    FakeMenu.instance = self

            def addAction(self, text: str):
                action = FakeAction(text)
                self.entries.append(("action", action))
                return action

            def addSeparator(self) -> None:
                self.entries.append(("separator", None))

            def addMenu(self, text: str):
                submenu = FakeMenu(text=text)
                self.entries.append(("menu", submenu))
                return submenu

            def exec(self, _pos):
                return None

        try:
            panel = self.widget.transfer_activity
            panel.attach_controller(dialog)
            with patch("truba_gui.ui.widgets.ftp_widget.QMenu", FakeMenu):
                panel._show_queue_menu(QPoint(0, 0))
            root = FakeMenu.instance
            self.assertEqual(
                [
                    kind if kind == "separator" else value.text
                    for kind, value in root.entries
                ],
                [
                    "Process Queue",
                    "Stop and remove all",
                    "separator",
                    "Remove selected",
                    "Default file exists action...",
                    "Set Priority",
                    "Action after queue completion",
                    "Export...",
                ],
            )
            self.assertEqual(
                [action.text for kind, action in root.entries[5][1].entries if kind == "action"],
                ["Highest", "High", "Normal", "Low", "Lowest"],
            )
        finally:
            dialog.deleteLater()

    def test_stop_button_cancels_immediately_and_clears_paused_queue(self) -> None:
        items = [
            TransferItem("download", "/remote/a.txt", "a.txt"),
            TransferItem("download", "/remote/b.txt", "b.txt"),
        ]
        dialog = TransferDialog(
            title="Download",
            items=items,
            run_item=lambda _item, _progress=None: None,
        )
        try:
            panel = self.widget.transfer_activity
            panel.attach_controller(dialog)
            self.assertTrue(panel.btn_stop.isEnabled())
            panel.btn_stop.click()
            self.assertTrue(dialog._cancelled)
            self.assertEqual(dialog._pending, [])
        finally:
            dialog.deleteLater()

    def test_priority_reorders_pending_execution_and_priority_column(self) -> None:
        items = [
            TransferItem("download", "/remote/low", "low"),
            TransferItem("download", "/remote/normal", "normal"),
            TransferItem("download", "/remote/high", "high"),
        ]
        started: list[str] = []
        dialog = TransferDialog(
            title="Download",
            items=items,
            run_item=lambda item, _progress=None: started.append(item.src),
            parallel_limit=1,
        )
        try:
            self.assertEqual(dialog.set_pending_priority([items[0]], "Lowest"), 1)
            self.assertEqual(dialog.set_pending_priority([items[2]], "Highest"), 1)
            panel = self.widget.transfer_activity
            panel.attach_controller(dialog)
            self.assertEqual(panel.queue_list.topLevelItem(0).text(5), "Highest")
            dialog.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not dialog.finished_cleanly():
                QApplication.processEvents()
                time.sleep(0.01)
            self.assertTrue(dialog.finished_cleanly())
            self.assertEqual(started, ["/remote/high", "/remote/normal", "/remote/low"])
        finally:
            dialog.cancel_all()
            dialog.deleteLater()

    def test_completion_action_persists_and_never_runs_system_action(self) -> None:
        panel = self.widget.transfer_activity
        with patch(
            "truba_gui.ui.widgets.ftp_widget.set_transfer_completion_action",
            return_value="play_sound",
        ) as save, patch("truba_gui.ui.widgets.ftp_widget.QApplication.beep") as beep:
            panel._set_completion_action("play_sound")
        save.assert_called_once_with("play_sound")
        beep.assert_called_once()
        self.assertIn("play_sound", panel.status_label.text())

        with patch(
            "truba_gui.ui.widgets.ftp_widget.set_transfer_completion_action",
            return_value="shutdown_once",
        ) as save:
            panel._set_completion_action("shutdown_once")
        save.assert_called_once_with("shutdown_once")
        self.assertIn("not executed", panel.status_label.text())

    def test_transfer_activity_failed_and_completed_context_actions_work(self) -> None:
        failed = TransferItem("upload", "failed.txt", "/remote/failed.txt")
        completed = TransferItem("download", "/remote/done.txt", "done.txt")
        dialog = TransferDialog(
            title="Transfers",
            items=[],
            run_item=lambda _item, _progress=None: None,
        )

        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

            def isEnabled(self) -> bool:
                return self.enabled

        chosen_index = [0]

        class FakeMenu:
            def __init__(self, _parent=None) -> None:
                self.actions = []

            def addAction(self, text: str):
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                pass

            def exec(self, _pos):
                return self.actions[chosen_index[0]]

        try:
            dialog._errors = [(failed, "network")]
            dialog._completed = [completed]
            dialog._running = True
            panel = self.widget.transfer_activity
            panel.attach_controller(dialog)
            panel.failed_list.topLevelItem(0).setSelected(True)
            with patch("truba_gui.ui.widgets.ftp_widget.QMenu", FakeMenu):
                panel._show_transfer_menu(panel.failed_list, QPoint(0, 0), "failed")
            self.assertEqual(dialog._errors, [])
            self.assertEqual(dialog._pending, [failed])

            chosen_index[0] = 1
            with patch("truba_gui.ui.widgets.ftp_widget.QMenu", FakeMenu):
                panel._show_transfer_menu(
                    panel.completed_list,
                    QPoint(0, 0),
                    "completed",
                )
            self.assertEqual(dialog._completed, [])
        finally:
            dialog.deleteLater()

    def test_transfer_activity_keeps_overlapping_controllers_visible(self) -> None:
        first_item = TransferItem("download", "/remote/a", "a")
        second_item = TransferItem("download", "/remote/b", "b")
        first = TransferDialog(
            title="First",
            items=[first_item],
            run_item=lambda _item, _progress=None: None,
        )
        second = TransferDialog(
            title="Second",
            items=[second_item],
            run_item=lambda _item, _progress=None: None,
        )
        try:
            panel = self.widget.transfer_activity
            panel.attach_controller(first)
            panel.attach_controller(second)
            self.assertEqual(panel.queue_list.topLevelItemCount(), 2)

            first.transferStatsChanged.emit("first still transferring")
            self.assertEqual(panel.status_label.text(), "first still transferring")

            with (
                patch.object(first, "cancel_all") as cancel_first,
                patch.object(second, "cancel_all") as cancel_second,
            ):
                panel._call_controller("cancel_all")
            cancel_first.assert_called_once_with()
            cancel_second.assert_called_once_with()

            first._pending = []
            first._completed = [first_item]
            first.finished.emit(0)
            self.assertIs(panel._controller, second)
            self.assertEqual(panel.queue_list.topLevelItemCount(), 1)
            self.assertEqual(panel.completed_list.topLevelItemCount(), 1)
            self.assertTrue(panel.btn_cancel.isEnabled())

            second.finished.emit(0)
            self.assertIsNone(panel._controller)
            self.assertFalse(panel.btn_stop.isEnabled())
            self.assertFalse(panel.btn_cancel.isEnabled())
            self.assertFalse(panel.btn_clear_pending.isEnabled())
        finally:
            first.deleteLater()
            second.deleteLater()

    def test_clean_accept_keeps_one_clearable_completed_history_row(self) -> None:
        completed = TransferItem("download", "/remote/done.txt", "done.txt")
        dialog = TransferDialog(
            title="Download",
            items=[completed],
            run_item=lambda _item, _progress=None: None,
        )
        dialog._pending = []
        dialog._completed = [completed]

        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

            def isEnabled(self) -> bool:
                return self.enabled

        class FakeMenu:
            def __init__(self, _parent=None) -> None:
                self.actions = []

            def addAction(self, text: str):
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                pass

            def exec(self, _pos):
                return self.actions[1]

        try:
            panel = self.widget.transfer_activity
            panel.attach_controller(dialog)
            dialog.finished.connect(
                lambda _result: panel.record("completed", [completed], "Download")
            )

            dialog.accept()

            self.assertIsNone(panel._controller)
            self.assertEqual(panel.completed_list.topLevelItemCount(), 1)
            with patch("truba_gui.ui.widgets.ftp_widget.QMenu", FakeMenu):
                panel._show_transfer_menu(
                    panel.completed_list,
                    QPoint(0, 0),
                    "completed",
                )
            self.assertEqual(panel.completed_list.topLevelItemCount(), 0)
        finally:
            dialog.deleteLater()

    def test_transfer_activity_renders_active_progress_child_row(self) -> None:
        item = TransferItem("upload", "local.bin", "/remote/local.bin")
        dialog = TransferDialog(
            title="Upload",
            items=[item],
            run_item=lambda _item, _progress=None: None,
        )
        try:
            dialog._active_item = item
            dialog._pending = []
            self.widget.transfer_activity.record("controller", [dialog], "Upload")
            dialog.transferStatsChanged.emit("00:00:05 elapsed    00:11:19 left    1.3%")

            row = self.widget.transfer_activity.queue_list.topLevelItem(0)
            self.assertEqual(row.text(6), "Transferring")
            self.assertEqual(row.childCount(), 1)
            self.assertIn("1.3%", row.child(0).text(2))
        finally:
            dialog.deleteLater()

    def test_transfer_activity_shows_progress_bar_percentage(self) -> None:
        item = TransferItem("download", "/remote/a.bin", "a.bin")
        dialog = TransferDialog(
            title="Download",
            items=[item],
            run_item=lambda _item, _progress=None: None,
        )
        try:
            dialog._active_item = item
            dialog._pending = []
            self.widget.transfer_activity.record("controller", [dialog], "Download")

            dialog.transferProgressChanged.emit(item, 25, 100)

            row = self.widget.transfer_activity.queue_list.topLevelItem(0)
            bar = self.widget.transfer_activity.queue_list.itemWidget(row, 4)
            self.assertIsNotNone(bar)
            self.assertEqual(bar.value(), 25)
            self.assertEqual(bar.text(), "25%")
        finally:
            dialog.deleteLater()

    def test_transfer_activity_hides_local_housekeeping_rows(self) -> None:
        items = [
            TransferItem("mkdir_local", "", r"D:\target\folder"),
            TransferItem("download", "/remote/folder/a.txt", r"D:\target\folder\a.txt"),
            TransferItem("delete_local", "", r"D:\target\old.txt"),
        ]

        self.widget.transfer_activity.record("queued", items, "Download")

        self.assertEqual(self.widget.transfer_activity.queue_list.topLevelItemCount(), 1)
        row = self.widget.transfer_activity.queue_list.topLevelItem(0)
        self.assertEqual(row.text(1), "<--")
        self.assertEqual(row.text(2), "/remote/folder/a.txt")

    def test_remote_delete_uses_modeless_worker_plan_without_gui_probe(self) -> None:
        class SlowDeleteFiles:
            supports_parallel_transfers = False

            def __init__(self) -> None:
                self.started = threading.Event()
                self.calls: list[tuple[str, bool]] = []
                self.thread_id = None

            def remove(self, path: str, recursive: bool = False) -> None:
                self.thread_id = threading.get_ident()
                self.calls.append((path, recursive))
                self.started.set()
                time.sleep(0.05)

            def is_dir(self, _path: str) -> bool:
                raise AssertionError("directory metadata should avoid GUI type probes")

        files = SlowDeleteFiles()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.current_dir = "/remote"
        panel._show_transfer_dialog = False
        paths = ["/remote/file.txt", "/remote/folder"]
        started_at = time.monotonic()
        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.assertTrue(panel._delete_paths(paths, [(paths[0], False), (paths[1], True)]))
        self.assertLess(time.monotonic() - started_at, 0.2)
        self.assertTrue(files.started.wait(1))
        self.assertNotEqual(files.thread_id, threading.get_ident())
        self.assertEqual(files.calls[0], ("/remote/file.txt", False))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and len(files.calls) < 2:
            QApplication.processEvents()
            time.sleep(0.01)
        self.assertEqual(files.calls, [("/remote/file.txt", False), ("/remote/folder", True)])

    def test_transfer_activity_renders_multiple_active_transfers(self) -> None:
        items = [
            TransferItem("download", "/remote/a.bin", "a.bin"),
            TransferItem("download", "/remote/b.bin", "b.bin"),
        ]
        dialog = TransferDialog(
            title="Download",
            items=items,
            run_item=lambda _item, _progress=None: None,
            parallel_limit=2,
        )
        try:
            dialog._active_items = list(items)
            dialog._pending = []
            self.widget.transfer_activity.record("controller", [dialog], "Download")
            dialog.transferListsChanged.emit([], [], [])

            self.assertEqual(self.widget.transfer_activity.queue_list.topLevelItemCount(), 2)
            self.assertEqual(
                [
                    self.widget.transfer_activity.queue_list.topLevelItem(index).text(5)
                    for index in range(2)
                ],
                ["Normal", "Normal"],
            )
            self.assertEqual(
                [
                    self.widget.transfer_activity.queue_list.topLevelItem(index).text(6)
                    for index in range(2)
                ],
                ["Transferring", "Transferring"],
            )
        finally:
            dialog.deleteLater()

    def test_transfer_dialog_is_modeless_and_reports_progress(self) -> None:
        transfer_item = TransferItem("download", "/remote/big.bin", "big.bin")
        dialog = TransferDialog(
            title="Download",
            items=[transfer_item, TransferItem("download", "/remote/next.bin", "next.bin")],
            run_item=lambda _item, _progress=None: None,
        )
        try:
            self.assertFalse(dialog.isModal())
            self.assertEqual(dialog.queue_list.count(), 0)
            dialog._refresh()
            self.assertEqual(dialog.queue_list.count(), 2)

            dialog.clear_pending()
            self.assertEqual(dialog.queue_list.count(), 0)

            dialog._started_at = 1.0
            with patch("truba_gui.ui.dialogs.transfer_dialog.time.monotonic", return_value=3.0):
                dialog._on_transfer_progress(transfer_item, 2048, 4096)
            detail = dialog.lbl_transfer_stats.text()
            self.assertIn("2.0 KB/4.0 KB", detail)
            self.assertIn("/s", detail)

            dialog._on_transfer_progress(transfer_item, 5 * 1024 ** 3, 8 * 1024 ** 3)
            self.assertIn("5.0 GB/8.0 GB", dialog.lbl_transfer_stats.text())
        finally:
            dialog.deleteLater()

    def test_transfer_dialog_bounds_and_coalesces_large_queue_publication(self) -> None:
        items = [
            TransferItem("download", f"/remote/{index}.bin", f"{index}.bin")
            for index in range(5)
        ]
        dialog = TransferDialog(
            title="Download",
            items=items,
            run_item=lambda _item, _progress=None: None,
        )
        try:
            published = []
            dialog.transferListsChanged.connect(
                lambda pending, _errors, _completed: published.append(pending)
            )
            with patch.object(dialog, "_MAX_VISIBLE_LIST_ITEMS", 3):
                dialog._refresh()
                self.assertEqual(dialog.queue_list.count(), 4)
                self.assertEqual(dialog.queue_list.item(3).text(), "Remaining: 2")
                self.assertEqual(len(published[-1]), 5)

                dialog._refresh_scheduled = False
                with patch(
                    "truba_gui.ui.dialogs.transfer_dialog.QTimer.singleShot"
                ) as single_shot:
                    dialog._schedule_refresh()
                    dialog._schedule_refresh()
                single_shot.assert_called_once()
        finally:
            dialog.deleteLater()

    def test_transfer_dialog_runs_up_to_parallel_limit(self) -> None:
        started: list[str] = []
        finished: list[str] = []
        release = threading.Event()
        lock = threading.Lock()
        items = [
            TransferItem("download", "/remote/a.bin", "a.bin"),
            TransferItem("download", "/remote/b.bin", "b.bin"),
            TransferItem("download", "/remote/c.bin", "c.bin"),
        ]

        def run_item(item, _progress=None):
            with lock:
                started.append(item.src)
            release.wait(5)
            with lock:
                finished.append(item.src)

        dialog = TransferDialog(
            title="Download",
            items=items,
            run_item=run_item,
            parallel_limit=2,
        )
        try:
            dialog.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                QApplication.processEvents()
                with lock:
                    if len(started) >= 2:
                        break
                time.sleep(0.01)
            with lock:
                self.assertEqual(len(started), 2)
                self.assertEqual(finished, [])

            release.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not dialog.finished_cleanly():
                QApplication.processEvents()
                time.sleep(0.01)
            self.assertTrue(dialog.finished_cleanly())
            with lock:
                self.assertCountEqual(started, [item.src for item in items])
                self.assertCountEqual(finished, [item.src for item in items])
        finally:
            dialog.cancel_all()
            dialog.deleteLater()

    def test_transfer_dialog_finishes_mkdir_before_parallel_transfer_batch(self) -> None:
        prepared = threading.Event()
        started_uploads: list[str] = []
        lock = threading.Lock()
        items = [
            TransferItem("mkdir_remote", "", "/remote/folder"),
            TransferItem("upload", "first.bin", "/remote/folder/first.bin"),
            TransferItem("upload", "second.bin", "/remote/folder/second.bin"),
        ]

        def run_item(item, _progress=None):
            if item.op == "mkdir_remote":
                time.sleep(0.03)
                prepared.set()
                return
            self.assertTrue(prepared.is_set())
            with lock:
                started_uploads.append(item.src)

        dialog = TransferDialog(
            title="Upload",
            items=items,
            run_item=run_item,
            parallel_limit=2,
        )
        try:
            dialog.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not dialog.finished_cleanly():
                QApplication.processEvents()
                time.sleep(0.01)
            self.assertTrue(dialog.finished_cleanly())
            self.assertCountEqual(started_uploads, ["first.bin", "second.bin"])
        finally:
            dialog.cancel_all()
            dialog.deleteLater()

    def test_recursive_plan_prepares_all_mkdirs_before_parallel_upload_phase(self) -> None:
        prepared: list[str] = []
        started: list[str] = []
        release = threading.Event()
        lock = threading.Lock()
        items = [
            TransferItem("mkdir_remote", "", "/remote/root"),
            TransferItem("mkdir_remote", "", "/remote/root/one"),
            TransferItem("upload", "one.bin", "/remote/root/one/one.bin"),
            TransferItem("mkdir_remote", "", "/remote/root/two"),
            TransferItem("upload", "two.bin", "/remote/root/two/two.bin"),
            TransferItem("upload", "root.bin", "/remote/root/root.bin"),
        ]

        def run_item(item, _progress=None):
            if item.op == "mkdir_remote":
                prepared.append(item.dst)
                return
            self.assertEqual(len(prepared), 3)
            with lock:
                started.append(item.src)
            release.wait(3)

        dialog = TransferDialog(
            title="Upload",
            items=items,
            run_item=run_item,
            parallel_limit=3,
        )
        try:
            dialog.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with lock:
                    if len(started) >= 2:
                        break
                QApplication.processEvents()
                time.sleep(0.01)
            self.assertEqual(prepared, ["/remote/root", "/remote/root/one", "/remote/root/two"])
            with lock:
                self.assertGreaterEqual(len(started), 2)
            release.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not dialog.finished_cleanly():
                QApplication.processEvents()
                time.sleep(0.01)
            self.assertTrue(dialog.finished_cleanly())
        finally:
            release.set()
            dialog.cancel_all()
            dialog.deleteLater()

    def test_mixed_mutation_plan_keeps_original_order(self) -> None:
        items = [
            TransferItem("mkdir_remote", "", "/remote/root"),
            TransferItem("upload", "one.bin", "/remote/root/one.bin"),
            TransferItem("delete", "", "/remote/old.bin"),
            TransferItem("upload", "two.bin", "/remote/root/two.bin"),
        ]
        worker = __import__(
            "truba_gui.ui.dialogs.transfer_dialog",
            fromlist=["_WorkerThread"],
        )._WorkerThread(items, lambda _item, _progress=None: None, parallel_limit=3)
        self.assertEqual(worker._items, items)

    def test_transfer_dialog_never_exceeds_backend_safe_cap(self) -> None:
        dialog = TransferDialog(
            title="Upload",
            items=[],
            run_item=lambda _item, _progress=None: None,
            parallel_limit=5,
            max_parallel_limit=1,
        )
        try:
            self.assertEqual(dialog._parallel_limit, 1)
            self.assertEqual(dialog.set_parallel_limit(5), 1)
            self.assertEqual(dialog._parallel_limit, 1)
            self.assertIn("1", dialog.lbl_parallel_hint.text())
        finally:
            dialog.deleteLater()

    def test_resumed_transfer_speed_uses_only_session_bytes(self) -> None:
        transfer_item = TransferItem("upload", "big.bin", "/remote/big.bin")
        dialog = TransferDialog(
            title="Upload",
            items=[transfer_item],
            run_item=lambda _item, _progress=None: None,
        )
        try:
            dialog._on_item_started(0, transfer_item)
            with patch(
                "truba_gui.ui.dialogs.transfer_dialog.time.monotonic",
                side_effect=[100.0, 102.0],
            ):
                dialog._on_transfer_progress(transfer_item, 8_000_000, 10_000_000)
                self.assertIn("0 B/s", dialog.lbl_transfer_stats.text())
                dialog._on_transfer_progress(transfer_item, 9_000_000, 10_000_000)

            detail = dialog.lbl_transfer_stats.text()
            self.assertIn("488.3 KB/s", detail)
            self.assertIn("remaining 0:02", detail)
            self.assertEqual(
                dialog._item_progress_baselines[id(transfer_item)],
                (8_000_000.0, 100.0),
            )

            dialog._on_item_finished(transfer_item, False, "")
            self.assertNotIn(id(transfer_item), dialog._item_progress_baselines)
        finally:
            dialog.deleteLater()

    def test_parallel_capable_backend_uses_configured_parallelism_for_new_plan(self) -> None:
        class ParallelFiles:
            supports_parallel_transfers = True

            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def download(self, _remote_path: str, local_path: str, progress_cb=None) -> None:
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.03)
                Path(local_path).write_bytes(b"content")
                if progress_cb is not None:
                    progress_cb(7, 7)
                with self.lock:
                    self.active -= 1

        panel = self.widget.panel_scratch
        files = ParallelFiles()
        panel.session = {"connected": True, "files": files}
        controllers: list[TransferDialog] = []
        completed = threading.Event()

        def activity(event, items, _title):
            if event == "controller":
                controllers.extend(items)
            elif event == "completed":
                completed.set()

        panel.set_transfer_activity_callback(activity)
        with tempfile.TemporaryDirectory() as tmp:
            plan = [
                _PlannedOp(
                    "download",
                    f"/remote/{index}.txt",
                    str(Path(tmp) / f"local-{index}.txt"),
                )
                for index in range(4)
            ]

            with patch(
                "truba_gui.ui.widgets.remote_dir_panel.get_transfer_parallelism",
                return_value=3,
            ):
                self.assertTrue(panel._run_plan_with_progress(plan, "Download"))

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not completed.is_set():
                QApplication.processEvents()
                time.sleep(0.01)

        self.assertEqual(len(controllers), 1)
        self.assertEqual(controllers[0]._parallel_limit, 3)
        self.assertEqual(controllers[0]._max_parallel_limit, 3)
        self.assertTrue(completed.is_set())
        self.assertGreaterEqual(files.max_active, 2)

    def test_ssh_backend_parallel_uploads_use_isolated_closed_channels(self) -> None:
        class FakeWriter:
            def __init__(self, channel) -> None:
                self.channel = channel

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def write(self, _data: bytes) -> None:
                with self.channel.owner.lock:
                    self.channel.did_write = True
                    self.channel.owner.active += 1
                    self.channel.owner.max_active = max(
                        self.channel.owner.max_active,
                        self.channel.owner.active,
                    )
                    self.channel.owner.started.set()
                self.channel.owner.release.wait(3)
                with self.channel.owner.lock:
                    self.channel.owner.active -= 1

        class FakeTransferChannel:
            def __init__(self, owner) -> None:
                self.owner = owner
                self.closed = False
                self.did_write = False

            def stat(self, _path: str):
                return SimpleNamespace(st_size=0)

            def open(self, _path: str, mode: str):
                self.owner.assert_modes.append(mode)
                return FakeWriter(self)

            def close(self) -> None:
                self.closed = True

        class FakeSSH:
            sftp = object()

            def __init__(self) -> None:
                self.channels: list[FakeTransferChannel] = []
                self.lock = threading.Lock()
                self.started = threading.Event()
                self.release = threading.Event()
                self.active = 0
                self.max_active = 0
                self.assert_modes: list[str] = []

            def open_transfer_sftp(self):
                channel = FakeTransferChannel(self)
                self.channels.append(channel)
                return channel

            def supports_transfer_sftp_channels(self) -> bool:
                probe = self.open_transfer_sftp()
                probe.close()
                return True

        ssh = FakeSSH()
        backend = SSHFilesBackend(ssh)
        self.assertTrue(backend.supports_parallel_transfers)
        items: list[TransferItem] = []
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(3):
                source = Path(tmp) / f"source-{index}.bin"
                source.write_bytes(b"payload")
                items.append(TransferItem("upload", str(source), f"/remote/{index}.bin"))
            panel = self.widget.panel_scratch
            panel.session = {"connected": True, "files": backend}
            try:
                with patch(
                    "truba_gui.ui.widgets.remote_dir_panel.get_transfer_parallelism",
                    return_value=3,
                ):
                    self.assertTrue(
                        panel._run_plan_with_progress(
                            [
                                _PlannedOp(item.op, item.src, item.dst)
                                for item in items
                            ],
                            "Upload",
                        )
                    )
                dialog = panel._transfer_dialogs[-1]
                self.assertEqual(dialog._parallel_limit, 3)
                self.assertEqual(dialog._max_parallel_limit, 3)
                self.assertTrue(ssh.started.wait(2))
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    with ssh.lock:
                        if ssh.max_active >= 2:
                            break
                    time.sleep(0.01)
                with ssh.lock:
                    self.assertGreaterEqual(ssh.max_active, 2)
                ssh.release.set()
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline and not dialog.finished_cleanly():
                    QApplication.processEvents()
                    time.sleep(0.01)
                self.assertTrue(dialog.finished_cleanly())
            finally:
                ssh.release.set()
                dialog.cancel_all()
                dialog.deleteLater()

        transfer_channels = [channel for channel in ssh.channels if channel.did_write]
        self.assertEqual(len(transfer_channels), 3)
        self.assertEqual(len({id(channel) for channel in transfer_channels}), 3)
        self.assertTrue(all(channel.closed for channel in transfer_channels))
        self.assertEqual(ssh.assert_modes, ["wb", "wb", "wb"])

    def test_ssh_backend_without_transfer_channel_capability_clamps_parallelism(self) -> None:
        class UnavailableSSH:
            sftp = object()

            def supports_transfer_sftp_channels(self) -> bool:
                return False

            def open_transfer_sftp(self):
                raise AssertionError("unavailable capability must not open a transfer channel")

        backend = SSHFilesBackend(UnavailableSSH())
        self.assertFalse(backend.supports_parallel_transfers)
        dialog = TransferDialog(
            title="Upload",
            items=[],
            run_item=lambda _item, _progress=None: None,
            parallel_limit=3,
            max_parallel_limit=(3 if backend.supports_parallel_transfers else 1),
        )
        try:
            self.assertEqual(dialog._parallel_limit, 1)
            self.assertEqual(dialog._max_parallel_limit, 1)
        finally:
            dialog.deleteLater()

    def test_ssh_resumed_upload_reports_existing_offset_before_copy(self) -> None:
        class RemoteWriter:
            def __init__(self) -> None:
                self.data = bytearray(b"abc")

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def write(self, data: bytes) -> None:
                self.data.extend(data)

        class TransferChannel:
            def __init__(self) -> None:
                self.writer = RemoteWriter()
                self.closed = False

            def stat(self, _path: str):
                return SimpleNamespace(st_size=3)

            def open(self, _path: str, mode: str):
                self.assert_mode = mode
                return self.writer

            def close(self) -> None:
                self.closed = True

        channel = TransferChannel()
        ssh = SimpleNamespace(sftp=object(), open_transfer_sftp=lambda: channel)
        backend = SSHFilesBackend(ssh)
        progress: list[tuple[int, int]] = []
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "resume.bin"
            source.write_bytes(b"abcdefgh")
            backend.upload(
                str(source),
                "/remote/resume.bin",
                progress_cb=lambda done, total: progress.append((done, total)),
            )

        self.assertEqual(progress, [(3, 8), (8, 8)])
        self.assertEqual(channel.assert_mode, "ab")
        self.assertEqual(bytes(channel.writer.data), b"abcdefgh")
        self.assertTrue(channel.closed)

    def test_upload_preflight_shows_counts_and_source_destination_rows(self) -> None:
        items = [
            TransferItem("mkdir_remote", "", "/remote/folder"),
            TransferItem("upload", "C:/local/a.txt", "/remote/folder/a.txt"),
            TransferItem("upload", "C:/local/b.txt", "/remote/folder/b.txt"),
        ]
        dialog = TransferPreflightDialog(
            title="Upload",
            items=items,
            parallel_limit=2,
        )
        try:
            self.assertIn("2 files", dialog.lbl_summary.text())
            self.assertIn("1 folder", dialog.lbl_summary.text())
            self.assertIn("3 total steps", dialog.lbl_summary.text())
            self.assertIn("2 transfers", dialog.lbl_summary.text())
            self.assertEqual(dialog.plan_list.topLevelItemCount(), 3)
            upload_row = dialog.plan_list.topLevelItem(1)
            self.assertEqual(upload_row.text(1), "C:/local/a.txt")
            self.assertEqual(upload_row.text(2), "/remote/folder/a.txt")
            self.assertEqual(dialog.btn_start.text(), "Start transfer")
            self.assertEqual(dialog.cb_dont_ask_again.text(), "Don't ask again")
            self.assertFalse(dialog.cb_dont_ask_again.isChecked())
        finally:
            dialog.deleteLater()

    def test_upload_preflight_dont_ask_persists_only_when_accepted(self) -> None:
        panel = self.widget.panel_scratch
        item = TransferItem("upload", "C:/local/a.txt", "/remote/a.txt")

        class FakeCheckBox:
            def isChecked(self) -> bool:
                return True

        class FakePreflightDialog:
            result = QDialog.DialogCode.Accepted

            def __init__(self, *_args, **_kwargs) -> None:
                self.cb_dont_ask_again = FakeCheckBox()

            def exec(self):
                return self.result

            def deleteLater(self) -> None:
                pass

        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.get_upload_preflight_confirmation_enabled",
            return_value=True,
        ), patch(
            "truba_gui.ui.widgets.remote_dir_panel.TransferPreflightDialog",
            FakePreflightDialog,
        ), patch(
            "truba_gui.ui.widgets.remote_dir_panel.set_upload_preflight_confirmation_enabled"
        ) as persist:
            self.assertTrue(panel._confirm_transfer_plan([item], "Upload", 1))
        persist.assert_called_once_with(False)

        FakePreflightDialog.result = QDialog.DialogCode.Rejected
        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.get_upload_preflight_confirmation_enabled",
            return_value=True,
        ), patch(
            "truba_gui.ui.widgets.remote_dir_panel.TransferPreflightDialog",
            FakePreflightDialog,
        ), patch(
            "truba_gui.ui.widgets.remote_dir_panel.set_upload_preflight_confirmation_enabled"
        ) as persist:
            self.assertFalse(panel._confirm_transfer_plan([item], "Upload", 1))
        persist.assert_not_called()

    def test_disabled_upload_preflight_skips_dialog(self) -> None:
        panel = self.widget.panel_scratch
        item = TransferItem("mkdir_remote", "", "/remote/empty")
        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.get_upload_preflight_confirmation_enabled",
            return_value=False,
        ), patch(
            "truba_gui.ui.widgets.remote_dir_panel.TransferPreflightDialog"
        ) as dialog:
            self.assertTrue(panel._confirm_transfer_plan([item], "Upload", 1))
        dialog.assert_not_called()

    def test_disabled_upload_preflight_still_executes_local_upload(self) -> None:
        class Files:
            supports_parallel_transfers = False

            def __init__(self) -> None:
                self.created: list[str] = []

            def exists(self, _path: str) -> bool:
                return False

            def mkdir(self, path: str) -> None:
                self.created.append(path)

            def listdir_entries(self, _path: str):
                return []

        files = Files()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        completed = threading.Event()
        panel.set_transfer_activity_callback(
            lambda event, _items, _title: completed.set()
            if event == "completed"
            else None
        )

        with tempfile.TemporaryDirectory() as tmp:
            empty_folder = Path(tmp) / "empty"
            empty_folder.mkdir()
            with patch(
                "truba_gui.ui.widgets.remote_dir_panel.get_upload_preflight_confirmation_enabled",
                return_value=False,
            ), patch(
                "truba_gui.ui.widgets.remote_dir_panel.TransferPreflightDialog"
            ) as dialog:
                self.assertTrue(
                    panel._apply_local_upload([str(empty_folder)], "/remote")
                )
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not completed.is_set():
                    QApplication.processEvents()
                    time.sleep(0.01)

        dialog.assert_not_called()
        self.assertTrue(completed.is_set())
        self.assertEqual(files.created, ["/remote/empty"])

    def test_upload_preflight_cancel_starts_no_worker_or_activity(self) -> None:
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": _Files()}
        source = str(Path(__file__).resolve())
        destination = "/remote/test_ftp_widget.py"
        events = []
        panel.set_transfer_activity_callback(
            lambda event, items, title: events.append((event, items, title))
        )

        with patch.object(
            panel,
            "_confirm_transfer_plan",
            return_value=False,
        ) as confirm, patch.object(TransferDialog, "start") as start:
            self.assertFalse(
                panel._run_plan_with_progress(
                    [_PlannedOp("upload", source, destination)],
                    "Upload",
                    confirm_before_start=True,
                )
            )

        confirm.assert_called_once()
        start.assert_not_called()
        self.assertEqual(events, [])
        self.assertNotIn(
            ("upload", source, destination),
            panel._active_transfer_keys,
        )

    def test_empty_folder_upload_requires_preflight_before_mkdir_worker(self) -> None:
        class EmptyFolderFiles:
            supports_parallel_transfers = False

            def __init__(self) -> None:
                self.created: list[str] = []

            def exists(self, _path: str) -> bool:
                return False

            def mkdir(self, _path: str) -> None:
                self.created.append(_path)

            def listdir_entries(self, _path: str):
                return []

        panel = self.widget.panel_scratch
        files = EmptyFolderFiles()
        panel.session = {"connected": True, "files": files}
        controllers: list[TransferDialog] = []
        completed = threading.Event()

        def record_activity(event, items, _title):
            if event == "controller":
                controllers.extend(items)
            elif event == "completed":
                completed.set()

        panel.set_transfer_activity_callback(record_activity)

        with tempfile.TemporaryDirectory() as tmp:
            empty_folder = Path(tmp) / "empty"
            empty_folder.mkdir()

            with patch.object(
                panel,
                "_confirm_transfer_plan",
                return_value=False,
            ) as confirm, patch.object(TransferDialog, "start") as start:
                self.assertFalse(
                    panel._apply_local_upload([str(empty_folder)], "/remote")
                )
            confirm_items = confirm.call_args.args[0]
            self.assertEqual(
                [(item.op, item.src, item.dst) for item in confirm_items],
                [("mkdir_remote", "", "/remote/empty")],
            )
            start.assert_not_called()
            self.assertEqual(controllers, [])

            with patch.object(
                panel,
                "_confirm_transfer_plan",
                return_value=True,
            ) as confirm:
                self.assertTrue(
                    panel._apply_local_upload([str(empty_folder)], "/remote")
                )
                confirm.assert_called_once()
                self.assertEqual(len(controllers), 1)
                controller = controllers[0]
                self.assertEqual(
                    [(item.op, item.src, item.dst) for item in controller._items],
                    [("mkdir_remote", "", "/remote/empty")],
                )
                self.assertEqual(controller._parallel_limit, 1)

                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not completed.is_set():
                    QApplication.processEvents()
                    time.sleep(0.01)

        self.assertTrue(completed.is_set())
        self.assertEqual(files.created, ["/remote/empty"])

    def test_single_connection_multi_folder_upload_runs_sequentially(self) -> None:
        class SingleConnectionFiles:
            supports_parallel_transfers = False

            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self.uploaded: list[str] = []
                self.lock = threading.Lock()

            def exists(self, _path: str) -> bool:
                return False

            def is_dir(self, _path: str) -> bool:
                return False

            def listdir_entries(self, _path: str):
                return []

            def mkdir(self, _path: str) -> None:
                self._run_operation()

            def upload(self, _local_path: str, remote_path: str, progress_cb=None) -> None:
                self._run_operation()
                self.uploaded.append(remote_path)
                if progress_cb is not None:
                    progress_cb(1, 1)

            def _run_operation(self) -> None:
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.01)
                with self.lock:
                    self.active -= 1

        files = SingleConnectionFiles()
        panel = self.widget.panel_scratch
        panel.set_session({"connected": True, "files": files})
        controllers: list[TransferDialog] = []
        completed = threading.Event()

        def record_activity(event, items, _title):
            if event == "controller":
                controllers.extend(items)
            elif event == "completed":
                completed.set()

        panel.set_transfer_activity_callback(record_activity)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "truba_gui.ui.widgets.remote_dir_panel.get_transfer_parallelism",
            return_value=5,
        ), patch.object(panel, "_confirm_transfer_plan", return_value=True) as confirm:
            roots = []
            for name in ("first", "second"):
                root = Path(tmp) / name
                root.mkdir()
                (root / "input.txt").write_text(name, encoding="utf-8")
                roots.append(str(root))

            self.assertTrue(panel._apply_local_upload(roots, "/remote"))
            confirm.assert_called_once()
            self.assertEqual(len(controllers), 1)
            self.assertEqual(controllers[0]._parallel_limit, 1)

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not completed.is_set():
                QApplication.processEvents()
                time.sleep(0.01)

        self.assertTrue(completed.is_set())
        self.assertEqual(files.max_active, 1)
        self.assertCountEqual(
            files.uploaded,
            ["/remote/first/input.txt", "/remote/second/input.txt"],
        )

    def test_ftp_transfers_use_embedded_activity_without_showing_popup(self) -> None:
        self.assertFalse(self.widget.panel_scratch._show_transfer_dialog)
        self.assertFalse(self.widget.panel_home._show_transfer_dialog)

    def test_conflict_dialog_exposes_requested_actions_and_checks(self) -> None:
        dialog = TransferConflictDialog(
            source=TransferConflictInfo("/source/file.txt", size=10, mtime=2),
            target=TransferConflictInfo("/target/file.txt", size=5, mtime=1),
        )
        try:
            self.assertEqual(
                set(dialog.action_buttons),
                {
                    "overwrite",
                    "overwrite_if_newer",
                    "overwrite_if_size_differs",
                    "overwrite_if_size_differs_or_newer",
                    "resume",
                    "rename",
                    "skip",
                },
            )
            dialog.action_buttons["skip"].setChecked(True)
            dialog.cb_always.setChecked(True)
            decision = dialog.decision()
            self.assertEqual(decision.action, "skip")
            self.assertTrue(decision.always_use)
            self.assertEqual(dialog.windowTitle(), "Target file already exists")
            local_ts = int(datetime.datetime(2025, 11, 16, 11, 26, 39).timestamp())
            self.assertEqual(
                TransferConflictDialog._format_time(local_ts),
                "11/16/2025 11:26:39 AM",
            )
        finally:
            dialog.deleteLater()

    def test_conditional_conflict_actions_are_resolved_safely(self) -> None:
        source = TransferConflictInfo("/source", size=10, mtime=20)
        target = TransferConflictInfo("/target", size=10, mtime=10)
        self.assertEqual(
            RemoteDirPanel._normalize_conflict_decision(
                TransferConflictDecision("overwrite_if_newer"),
                source,
                target,
            ),
            "overwrite",
        )
        self.assertEqual(
            RemoteDirPanel._normalize_conflict_decision(
                TransferConflictDecision("overwrite_if_size_differs"),
                source,
                target,
            ),
            "skip",
        )
        self.assertEqual(
            RemoteDirPanel._normalize_conflict_decision(
                TransferConflictDecision("resume"),
                source,
                target,
            ),
            "resume",
        )

    def test_both_remote_panels_forward_open_and_submit_signals(self) -> None:
        opened = []
        submitted = []
        shell_runs = []
        self.widget.openFileRequested.connect(opened.append)
        self.widget.submitRequested.connect(submitted.append)
        self.widget.runShellRequested.connect(shell_runs.append)

        self.widget.panel_scratch.open_file.emit("/scratch/readme.txt")
        self.widget.panel_home.open_file.emit("/home/script.slurm")
        self.widget.panel_scratch.submit_requested.emit("/scratch/a.slurm")
        self.widget.panel_home.submit_requested.emit("/home/b.sbatch")
        self.widget.panel_scratch.run_shell_requested.emit("/scratch/run.sh")

        self.assertEqual(
            opened,
            ["/scratch/readme.txt", "/home/script.slurm"],
        )
        self.assertEqual(
            submitted,
            ["/scratch/a.slurm", "/home/b.sbatch"],
        )
        self.assertEqual(shell_runs, ["/scratch/run.sh"])

    def test_submit_candidate_requires_one_slurm_file(self) -> None:
        self.assertEqual(
            RemoteDirPanel._submit_candidate(
                [("/arf/scratch/alice/job.slurm", False)]
            ),
            "/arf/scratch/alice/job.slurm",
        )
        self.assertEqual(
            RemoteDirPanel._submit_candidate(
                [("/arf/home/alice/job.sbatch", False)]
            ),
            "/arf/home/alice/job.sbatch",
        )
        self.assertEqual(
            RemoteDirPanel._submit_candidate(
                [
                    ("/arf/scratch/alice/a.slurm", False),
                    ("/arf/scratch/alice/b.slurm", False),
                ]
            ),
            "",
        )
        self.assertEqual(
            RemoteDirPanel._submit_candidate(
                [("/arf/scratch/alice/folder.slurm", True)]
            ),
            "",
        )
        self.assertEqual(
            RemoteDirPanel._submit_candidate(
                [("/arf/scratch/alice/run.sh", False)]
            ),
            "",
        )

    def test_shell_run_candidate_requires_one_shell_file(self) -> None:
        self.assertEqual(
            RemoteDirPanel._shell_run_candidate(
                [("/arf/scratch/alice/run.sh", False)]
            ),
            "/arf/scratch/alice/run.sh",
        )
        self.assertEqual(
            RemoteDirPanel._shell_run_candidate(
                [("/arf/scratch/alice/job.slurm", False)]
            ),
            "",
        )
        self.assertEqual(
            RemoteDirPanel._shell_run_candidate(
                [
                    ("/arf/scratch/alice/a.sh", False),
                    ("/arf/scratch/alice/b.sh", False),
                ]
            ),
            "",
        )
        self.assertEqual(
            RemoteDirPanel._shell_run_candidate(
                [("/arf/scratch/alice/folder.sh", True)]
            ),
            "",
        )

    def test_shell_run_worker_quotes_script_command(self) -> None:
        self.assertEqual(
            _ShellRunWorker.command_for("/arf/scratch/alice/my script.sh"),
            "cd /arf/scratch/alice && bash './my script.sh'",
        )

    def test_shell_run_result_dialog_is_scrollable_and_screen_bounded(self) -> None:
        widget = DirectoriesWidget()
        dialog = None
        try:
            output = "\n".join(f"line {index}" for index in range(2000))
            dialog = widget._create_shell_run_result_dialog(
                "/remote/very-long-script.sh",
                "Script completed in terminal.",
                output,
            )
            output_view = dialog.findChild(QPlainTextEdit, "shellRunOutput")
            self.assertIsNotNone(output_view)
            self.assertTrue(output_view.isReadOnly())
            self.assertEqual(
                output_view.lineWrapMode(),
                QPlainTextEdit.LineWrapMode.NoWrap,
            )
            self.assertEqual(output_view.toPlainText(), output)
            available = widget.screen().availableGeometry()
            self.assertLessEqual(
                dialog.maximumHeight(),
                max(240, int(available.height() * 0.85)),
            )
            dialog.show()
            self.app.processEvents()
            self.assertGreater(output_view.verticalScrollBar().maximum(), 0)
        finally:
            if dialog is not None:
                dialog.close()
                dialog.deleteLater()
            widget.shutdown()
            widget.deleteLater()

    def test_main_window_routes_ftp_actions_to_existing_directories_handlers(self) -> None:
        opened = []
        submitted = []

        def record_open(_self, path):
            opened.append(path)

        def record_submit(_self, path):
            submitted.append(path)

        def record_shell_run(_self, path):
            shell_runs.append(path)

        shell_runs = []

        with (
            patch("truba_gui.ui.main_window.QTimer.singleShot"),
            patch.object(DirectoriesWidget, "on_open_file", record_open),
            patch.object(DirectoriesWidget, "submit_script", record_submit),
            patch.object(DirectoriesWidget, "run_shell_script", record_shell_run),
        ):
            window = MainWindow()
            try:
                window.ftp.panel_scratch.open_file.emit("/scratch/file.txt")
                window.ftp.panel_home.submit_requested.emit("/home/job.slurm")
                window.ftp.panel_home.run_shell_requested.emit("/home/run.sh")

                self.assertEqual(opened, ["/scratch/file.txt"])
                self.assertEqual(submitted, ["/home/job.slurm"])
                self.assertEqual(shell_runs, ["/home/run.sh"])
            finally:
                window.graceful_shutdown()
                window.deleteLater()

    def test_main_window_contains_top_level_ftp_tab(self) -> None:
        with patch("truba_gui.ui.main_window.QTimer.singleShot"):
            window = MainWindow()
        try:
            labels = [
                window.tabs.tabText(index)
                for index in range(window.tabs.count())
            ]
            self.assertIn("FTP", labels)
            self.assertIs(window.ftp, window.tabs.widget(labels.index("FTP")))
        finally:
            window.graceful_shutdown()
            window.deleteLater()

    def test_submission_follow_modes_route_to_the_requested_destination(self) -> None:
        with patch("truba_gui.ui.main_window.QTimer.singleShot"):
            window = MainWindow()
        try:
            for mode, shows_jobs_page in {
                "none": False,
                "outputs_tab": True,
                "new_tabs_split": True,
                "new_window_combined": False,
                "new_windows_split": False,
            }.items():
                window.tabs.setCurrentWidget(window.ftp)
                with patch.object(window.jobs_outputs, "focus_job") as focus, patch(
                    "truba_gui.ui.main_window.get_sbatch_follow_mode",
                    return_value=mode,
                ):
                    window.on_script_submitted("123", "/remote/job.sbatch")
                self.assertIs(
                    window.tabs.currentWidget(),
                    window.jobs_outputs if shows_jobs_page else window.ftp,
                )
                focus.assert_called_once_with(
                    "123",
                    "/remote/job.sbatch",
                    switch_to_outputs=shows_jobs_page,
                    follow_mode=mode,
                )
        finally:
            window.graceful_shutdown()
            window.deleteLater()

    def test_focus_job_none_still_refreshes_and_binds_script(self) -> None:
        from truba_gui.ui.widgets.jobs_outputs_widget import JobsOutputsWidget
        jobs_widget = JobsOutputsWidget()
        try:
            jobs_widget.section_tabs.setCurrentWidget(jobs_widget.details_tab)
            with patch.object(jobs_widget, "refresh_jobs") as refresh_jobs, patch.object(
                jobs_widget, "refresh_sacct"
            ) as refresh_sacct, patch.object(
                jobs_widget, "_activate_slurm_script"
            ) as activate:
                jobs_widget.focus_job(
                    "123",
                    "/remote/job.sbatch",
                    switch_to_outputs=False,
                    follow_mode="none",
                )
            refresh_jobs.assert_called_once()
            refresh_sacct.assert_called_once()
            activate.assert_called_once_with(
                "/remote/job.sbatch",
                switch_to_outputs=False,
                follow_mode="none",
            )
            self.assertIs(jobs_widget.section_tabs.currentWidget(), jobs_widget.details_tab)
        finally:
            jobs_widget.deleteLater()

    def test_sbatch_follow_modes_use_existing_follower_helpers(self) -> None:
        from truba_gui.ui.widgets.jobs_outputs_widget import JobsOutputsWidget

        class ScriptFiles:
            def read_text(self, _path: str) -> str:
                return "#SBATCH --output=job.out\n#SBATCH --error=job.err\n"

        jobs_widget = JobsOutputsWidget()
        # _activate_slurm_script only needs the file backend; avoid a connected
        # session here because it would also start unrelated directory polling.
        jobs_widget.session = {"files": ScriptFiles()}
        try:
            with (
                patch.object(jobs_widget, "open_in_output_slot") as output_slot,
                patch.object(jobs_widget, "open_output_pair_tab") as pair_tab,
                patch.object(jobs_widget, "open_output_pair_window") as pair_window,
                patch.object(jobs_widget, "open_in_output_window") as output_window,
                patch.object(jobs_widget, "open_file_follow_window") as file_window,
                patch.object(jobs_widget, "_poll_live") as poll_live,
            ):
                for mode in ("none", "outputs_tab", "new_tabs_split", "new_window_combined", "new_windows_split"):
                    output_slot.reset_mock()
                    pair_tab.reset_mock()
                    pair_window.reset_mock()
                    output_window.reset_mock()
                    file_window.reset_mock()
                    poll_live.reset_mock()
                    jobs_widget._activate_slurm_script(
                        "/remote/job.sbatch",
                        switch_to_outputs=False,
                        follow_mode=mode,
                    )
                    if mode == "none":
                        output_slot.assert_not_called()
                        pair_tab.assert_not_called()
                        pair_window.assert_not_called()
                        output_window.assert_not_called()
                    elif mode == "outputs_tab":
                        self.assertEqual(output_slot.call_count, 2)
                        poll_live.assert_called_once()
                    elif mode == "new_tabs_split":
                        pair_tab.assert_called_once_with("/remote/job.out", "/remote/job.err")
                    elif mode == "new_window_combined":
                        pair_window.assert_called_once_with("/remote/job.out", "/remote/job.err")
                    else:
                        output_window.assert_not_called()
                        self.assertEqual(file_window.call_count, 2)
                        self.assertEqual(
                            [entry.args[0] for entry in file_window.call_args_list],
                            ["/remote/job.out", "/remote/job.err"],
                        )
        finally:
            jobs_widget.shutdown()
            jobs_widget.deleteLater()

    def test_generic_new_window_follower_is_one_single_file_window(self) -> None:
        from truba_gui.ui.widgets.jobs_outputs_widget import (
            JobsOutputsWidget,
            _SingleFileFollowerWidget,
        )

        jobs_widget = JobsOutputsWidget()
        try:
            window = jobs_widget.open_file_follow_window("/remote/run.log")
            self.assertIsNotNone(window)
            self.assertEqual(len(jobs_widget._single_file_follow_windows), 1)
            self.assertEqual(len(jobs_widget._follow_windows), 0)
            self.assertIsInstance(window.centralWidget(), _SingleFileFollowerWidget)
            self.assertIn("run.log", window.windowTitle())
            self.assertNotIn("Output 1", window.windowTitle())
            self.assertNotIn("Output 2", window.windowTitle())
            follower = window.centralWidget()
            self.assertFalse(follower.err_box.isVisible())
            self.assertEqual(follower.out_box.title(), "run.log")
            self.assertNotIn("Output 1", follower.out_box.title())
            self.assertNotIn("Output 2", follower.out_box.title())
        finally:
            jobs_widget.shutdown()
            jobs_widget.deleteLater()

    def test_combined_sbatch_follower_uses_one_clear_output_error_window(self) -> None:
        from truba_gui.ui.widgets.jobs_outputs_widget import JobsOutputsWidget

        class ScriptFiles:
            def read_text(self, _path: str) -> str:
                return "#SBATCH --output=job.out\n#SBATCH --error=job.err\n"

        jobs_widget = JobsOutputsWidget()
        jobs_widget.session = {"files": ScriptFiles()}
        try:
            jobs_widget._activate_slurm_script(
                "/remote/job.sbatch",
                follow_mode="new_window_combined",
            )
            self.assertEqual(len(jobs_widget._follow_windows), 1)
            self.assertEqual(len(jobs_widget._single_file_follow_windows), 0)
            window = jobs_widget._follow_windows[0]
            self.assertIn("Output: job.out", window.windowTitle())
            self.assertIn("Error: job.err", window.windowTitle())
            self.assertNotIn("Output 1", window.windowTitle())
            self.assertNotIn("Output 2", window.windowTitle())
            follower = window.centralWidget()
            self.assertEqual(follower.out_box.title(), "Output")
            self.assertEqual(follower.err_box.title(), "Error")
            self.assertNotIn("Output 1", follower.out_box.title())
            self.assertNotIn("Output 2", follower.err_box.title())
        finally:
            jobs_widget.shutdown()
            jobs_widget.deleteLater()

    def test_sbatch_follow_mode_settings_migrate_and_persist(self) -> None:
        from truba_gui.config import storage

        with patch.object(storage, "load_settings", return_value={
            "focus_jobs_outputs_after_submission_enabled": False,
        }):
            self.assertEqual(storage.get_sbatch_follow_mode(), "none")
        with patch.object(storage, "load_settings", return_value={
            "focus_jobs_outputs_after_submission_enabled": True,
        }):
            self.assertEqual(storage.get_sbatch_follow_mode(), "outputs_tab")
        with patch.object(storage, "load_settings", return_value={}):
            self.assertEqual(storage.get_sbatch_follow_mode(), "outputs_tab")
        with patch.object(storage, "update_settings") as update:
            self.assertEqual(storage.set_sbatch_follow_mode("new_tabs_split"), "new_tabs_split")
            update.assert_called_once_with({"sbatch_follow_mode": "new_tabs_split"})

    def test_sbatch_follow_mode_settings_have_all_tooltips(self) -> None:
        with patch(
            "truba_gui.ui.dialogs.settings_dialog.get_sbatch_follow_mode",
            return_value="outputs_tab",
        ):
            dialog = SettingsDialog()
        try:
            expected_modes = {
                "none",
                "outputs_tab",
                "new_tabs_split",
                "new_window_combined",
                "new_windows_split",
            }
            self.assertEqual(
                {
                    dialog.cb_sbatch_follow_mode.itemData(index)
                    for index in range(dialog.cb_sbatch_follow_mode.count())
                },
                expected_modes,
            )
            for index in range(dialog.cb_sbatch_follow_mode.count()):
                self.assertTrue(
                    dialog.cb_sbatch_follow_mode.itemData(
                        index, Qt.ItemDataRole.ToolTipRole
                    ).strip()
                )
            with patch(
                "truba_gui.ui.dialogs.settings_dialog.update_settings"
            ) as update:
                dialog.cb_sbatch_follow_mode.setCurrentIndex(
                    dialog.cb_sbatch_follow_mode.findData("new_windows_split")
                )
                dialog.btn_apply.click()
            self.assertEqual(
                update.call_args.args[0]["sbatch_follow_mode"],
                "new_windows_split",
            )
        finally:
            dialog.deleteLater()

    def test_session_uses_configured_scratch_and_home_roots(self) -> None:
        files = _Files()
        cfg = SimpleNamespace(
            username="alice",
            system_settings={
                "scratch_dir": "/arf/scratch/{user}",
                "home_dir": "/arf/home/{user}",
            },
        )
        self.widget.set_session(
            {"connected": True, "files": files, "cfg": cfg}
        )
        self.assertEqual(self.widget.panel_scratch.current_dir, "/arf/scratch/alice")
        self.assertEqual(self.widget.panel_home.current_dir, "/arf/home/alice")

    def test_context_menu_can_set_current_scratch_as_profile_default(self) -> None:
        cfg = SimpleNamespace(
            username="alice",
            system_settings={
                "scratch_dir": "/arf/scratch/{user}",
                "home_dir": "/arf/home/{user}",
            },
        )
        self.widget.set_session(
            {
                "connected": True,
                "files": _Files(),
                "cfg": cfg,
                "profile_name": "alice@truba",
            }
        )
        self.widget.panel_scratch.current_dir = "/arf/scratch/alice/project"
        emitted = []
        self.widget.defaultPathsRequested.connect(
            lambda scratch, home: emitted.append((scratch, home))
        )

        self.widget.panel_scratch.set_default_requested.emit()

        self.assertEqual(
            emitted,
            [("/arf/scratch/alice/project", "/arf/home/alice")],
        )

    def test_settings_edit_and_reset_profile_remote_defaults(self) -> None:
        cfg = SimpleNamespace(
            username="alice",
            system_settings={
                "scratch_dir": "/custom/scratch/{user}",
                "home_dir": "/custom/home/{user}",
            },
        )
        updates = []
        dialog = SettingsDialog(
            session={
                "connected": True,
                "profile_name": "alice@truba",
                "cfg": cfg,
            },
            update_remote_defaults=lambda scratch, home: updates.append(
                (scratch, home)
            ),
        )
        try:
            self.assertTrue(dialog.ftp_scratch_dir.isEnabled())
            self.assertEqual(
                dialog.ftp_scratch_dir.text(),
                "/custom/scratch/{user}",
            )
            dialog._reset_ftp_defaults()
            self.assertEqual(updates, [])
            self.assertEqual(
                dialog.ftp_home_dir.text(),
                "/arf/home/{user}",
            )
            with patch(
                "truba_gui.ui.dialogs.settings_dialog.update_settings"
            ):
                dialog.btn_apply.click()
            self.assertEqual(
                updates,
                [("/arf/scratch/{user}", "/arf/home/{user}")],
            )
        finally:
            dialog.deleteLater()

    def test_settings_apply_persists_without_closing_and_close_rejects(self) -> None:
        dialog = SettingsDialog()
        try:
            dialog.show()
            QApplication.processEvents()
            dialog.sp_transfer_parallelism.setValue(2)
            with patch(
                "truba_gui.ui.dialogs.settings_dialog.update_settings"
            ) as update:
                dialog.btn_apply.click()

            update.assert_called_once()
            self.assertEqual(update.call_args.args[0]["transfer_parallelism"], 2)
            self.assertTrue(dialog.isVisible())
            self.assertEqual(dialog.btn_apply.text(), "Apply")
            self.assertEqual(dialog.btn_close.text(), "Close")

            dialog.btn_close.click()
            self.assertFalse(dialog.isVisible())
            self.assertEqual(dialog.result(), SettingsDialog.DialogCode.Rejected)
        finally:
            dialog.deleteLater()

    def test_settings_controls_upload_preflight_confirmation(self) -> None:
        with patch(
            "truba_gui.ui.dialogs.settings_dialog.get_upload_preflight_confirmation_enabled",
            return_value=True,
        ):
            dialog = SettingsDialog()
        try:
            self.assertTrue(dialog.cb_upload_preflight_confirmation.isChecked())
            self.assertEqual(
                dialog.cb_upload_preflight_confirmation.text(),
                "Show upload plan confirmation",
            )
            with patch(
                "truba_gui.ui.dialogs.settings_dialog.update_settings"
            ) as update:
                dialog.cb_upload_preflight_confirmation.setChecked(False)
                dialog.btn_apply.click()
                self.assertFalse(
                    update.call_args.args[0]["upload_preflight_confirmation_enabled"]
                )

                dialog.cb_upload_preflight_confirmation.setChecked(True)
                dialog.btn_apply.click()
                self.assertTrue(
                    update.call_args.args[0]["upload_preflight_confirmation_enabled"]
                )
        finally:
            dialog.deleteLater()

    def test_profile_remote_controls_disabled_without_active_profile(self) -> None:
        dialog = SettingsDialog()
        try:
            self.assertFalse(dialog.ftp_scratch_dir.isEnabled())
            self.assertFalse(dialog.ftp_home_dir.isEnabled())
            self.assertFalse(dialog.btn_ftp_reset_defaults.isEnabled())
        finally:
            dialog.deleteLater()

    def test_profile_update_preserves_other_fields_and_refreshes_session(self) -> None:
        login = LoginWidget()
        cfg = SimpleNamespace(
            system_settings={
                "scratch_dir": "/old/scratch",
                "home_dir": "/old/home",
            }
        )
        login._session = {
            "connected": True,
            "profile_name": "alice@truba",
            "cfg": cfg,
        }
        original = {
            "name": "alice@truba",
            "host": "arf.truba.gov.tr",
            "password_dpapi": "protected-secret",
            "system": {
                "scratch_dir": "/old/scratch",
                "home_dir": "/old/home",
                "status_command": "lssrv-custom",
            },
        }
        emitted = []
        login.session_changed.connect(lambda session: emitted.append(session))
        try:
            with (
                patch.object(
                    login,
                    "_load_profile_by_name",
                    return_value=original,
                ),
                patch.object(login, "refresh_profiles"),
                patch(
                    "truba_gui.ui.widgets.login_widget.upsert_profile"
                ) as save_profile,
            ):
                self.assertTrue(
                    login.update_active_profile_remote_defaults(
                        "/new/scratch",
                        "/new/home",
                    )
                )
            saved = save_profile.call_args.args[0]
            self.assertEqual(saved["password_dpapi"], "protected-secret")
            self.assertEqual(saved["system"]["status_command"], "lssrv-custom")
            self.assertEqual(saved["system"]["scratch_dir"], "/new/scratch")
            self.assertEqual(cfg.system_settings["home_dir"], "/new/home")
            self.assertEqual(emitted[-1], login._session)
        finally:
            login.deleteLater()

    def test_upload_and_download_route_to_active_remote_panel(self) -> None:
        local_file = Path(__file__).resolve()
        self.widget.panel_scratch.current_dir = "/remote"
        self.widget.session = {"connected": True}
        with (
            patch.object(
                self.widget.local_panel,
                "selected_paths",
                return_value=[str(local_file)],
            ),
            patch.object(
                self.widget.panel_scratch,
                "_apply_local_upload_incremental",
                return_value=True,
            ) as upload,
        ):
            self.assertTrue(self.widget.upload_selected())
        upload.assert_called_once_with([str(local_file)], "/remote")

        with (
            patch.object(
                self.widget, "_selected_remote_paths", return_value=["/remote/out.txt"]
            ),
            patch.object(
                self.widget.panel_scratch,
                "_apply_remote_download_incremental",
                return_value=True,
            ) as download,
        ):
            self.assertTrue(self.widget.download_selected())
        download.assert_called_once_with(["/remote/out.txt"], self.widget.local_panel.current_dir)

    def test_local_context_upload_routes_selected_folder_to_incremental_planner(self) -> None:
        self.widget.panel_scratch.current_dir = "/remote"
        self.widget.session = {"connected": True}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, "folder")
            folder.mkdir()
            with patch.object(
                self.widget.panel_scratch,
                "_apply_local_upload_incremental",
                return_value=True,
            ) as incremental, patch.object(
                self.widget.panel_scratch,
                "_apply_local_upload",
                return_value=True,
            ) as synchronous:
                self.widget.local_panel.uploadRequested.emit([str(folder)])

        incremental.assert_called_once_with([str(folder)], "/remote")
        synchronous.assert_not_called()
        RemoteDirPanel._instances.pop(self.widget.panel_scratch.panel_id, None)
        RemoteDirPanel._instances.pop(self.widget.panel_home.panel_id, None)

    def test_local_context_folder_upload_attaches_embedded_controller_after_preflight(self) -> None:
        class Files:
            supports_parallel_transfers = False

            def exists(self, _path: str) -> bool:
                return False

        class FakeSignal:
            def __init__(self) -> None:
                self.slots = []

            def connect(self, slot) -> None:
                self.slots.append(slot)

            def disconnect(self, slot) -> None:
                if slot in self.slots:
                    self.slots.remove(slot)

            def emit(self, *args) -> None:
                for slot in list(self.slots):
                    slot(*args)

        class FakeController:
            def __init__(self, _parent=None, *, items, **_kwargs) -> None:
                self._items = list(items)
                self._pending = list(items)
                self._errors = []
                self._completed = []
                self._active_items = []
                self._active_item = None
                self._running = False
                self.transferStatsChanged = FakeSignal()
                self.transferListsChanged = FakeSignal()
                self.transferProgressChanged = FakeSignal()
                self.finished = FakeSignal()
                self.started = False

            def start(self) -> None:
                self.started = True

            def finished_cleanly(self) -> bool:
                return False

            def deleteLater(self) -> None:
                pass

        files = Files()
        panel = self.widget.panel_scratch
        session = {"connected": True, "files": files}
        self.widget.session = session
        panel.set_session(session)
        panel.current_dir = "/remote"
        controller = None
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, "folder")
            folder.mkdir()
            (folder / "input.txt").write_text("input", encoding="utf-8")

            with patch.object(
                panel,
                "_confirm_transfer_plan",
                return_value=True,
            ) as confirm, patch.object(
                panel,
                "_apply_local_upload",
                return_value=True,
            ) as synchronous, patch(
                "truba_gui.ui.widgets.remote_dir_panel.TransferDialog",
                FakeController,
            ):
                self.widget.local_panel.uploadRequested.emit([str(folder)])
                self.assertIsNone(self.widget.transfer_activity._controller)
                self.assertTrue(panel._planning_jobs)

                deadline = time.monotonic() + 3
                while (
                    time.monotonic() < deadline
                    and self.widget.transfer_activity._controller is None
                ):
                    self.app.processEvents()
                    time.sleep(0.01)

                controller = self.widget.transfer_activity._controller
                self.assertIsNotNone(controller)
                confirm.assert_called_once()
                synchronous.assert_not_called()
                self.assertEqual(
                    self.widget.transfer_activity.queue_list.topLevelItemCount(),
                    1,
                )
                self.assertEqual(
                    [item.op for item in controller._items],
                    ["mkdir_remote", "upload"],
                )
                self.assertTrue(controller.started)

        if controller is not None:
            controller.finished.emit(0)
        RemoteDirPanel._instances.pop(self.widget.panel_scratch.panel_id, None)
        RemoteDirPanel._instances.pop(self.widget.panel_home.panel_id, None)

    def test_remote_folder_download_returns_before_planning_finishes(self) -> None:
        files = _CountingFiles()
        panel = self.widget.panel_scratch
        session = {"connected": True, "files": files}
        self.widget.session = session
        panel.session = session
        self.widget.panel_scratch.current_dir = "/remote"

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            self.widget,
            "_selected_remote_paths",
            return_value=["/remote"],
        ), patch.object(
            panel,
            "_apply_remote_download",
            return_value=True,
        ) as synchronous, patch.object(
            panel,
            "_run_plan_with_progress",
            return_value=True,
        ) as run_plan:
            self.widget.local_panel.current_dir = tmp

            self.assertTrue(self.widget.download_selected())
            self.assertTrue(panel._planning_jobs)
            run_plan.assert_not_called()
            synchronous.assert_not_called()

            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not run_plan.called:
                self.app.processEvents()
                time.sleep(0.01)

            self.assertTrue(run_plan.called)
            plan = run_plan.call_args.args[0]
            self.assertEqual(files.calls, ["/remote", "/remote/child"])
            self.assertEqual(
                [item.op for item in plan],
                [
                    "mkdir_local",
                    "mkdir_local",
                    "download",
                    "download",
                ],
            )

    def test_upload_planning_uses_worker_and_returns_before_slow_probe(self) -> None:
        class SlowFiles:
            supports_parallel_transfers = False

            def __init__(self) -> None:
                self.started = threading.Event()
                self.release = threading.Event()
                self.thread_id = None

            def exists(self, _path: str) -> bool:
                self.thread_id = threading.get_ident()
                self.started.set()
                self.release.wait(3)
                return False

        files = SlowFiles()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            panel,
            "_run_plan_with_progress",
            return_value=True,
        ) as run_plan:
            local_file = Path(tmp, "input.bin")
            local_file.write_bytes(b"input")
            started_at = time.monotonic()
            self.assertTrue(
                panel._apply_local_upload_incremental(
                    [str(local_file)],
                    "/remote",
                )
            )
            elapsed = time.monotonic() - started_at

            self.assertLess(elapsed, 0.2)
            self.assertTrue(files.started.wait(1))
            self.assertNotEqual(files.thread_id, threading.get_ident())
            run_plan.assert_not_called()

            files.release.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not run_plan.called:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertTrue(run_plan.called)

    def test_download_planning_uses_worker_and_returns_before_slow_probe(self) -> None:
        class SlowFiles:
            supports_parallel_transfers = False

            def __init__(self) -> None:
                self.started = threading.Event()
                self.release = threading.Event()
                self.thread_id = None

            def is_dir(self, _path: str) -> bool:
                self.thread_id = threading.get_ident()
                self.started.set()
                self.release.wait(3)
                return False

        files = SlowFiles()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            panel,
            "_run_plan_with_progress",
            return_value=True,
        ) as run_plan:
            started_at = time.monotonic()
            self.assertTrue(
                panel._apply_remote_download_incremental(
                    ["/remote/output.bin"],
                    tmp,
                )
            )
            elapsed = time.monotonic() - started_at

            self.assertLess(elapsed, 0.2)
            self.assertTrue(files.started.wait(1))
            self.assertNotEqual(files.thread_id, threading.get_ident())
            run_plan.assert_not_called()

            files.release.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not run_plan.called:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertTrue(run_plan.called)

    def test_remote_multi_folder_download_pipeline_stays_off_gui_thread(self) -> None:
        class PipelineFiles:
            supports_parallel_transfers = True

            def __init__(self) -> None:
                self.discovery_threads: list[int] = []
                self.download_threads: list[int] = []
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()
                self.parallel_started = threading.Event()
                self.release = threading.Event()

            def is_dir(self, _path: str) -> bool:
                self.discovery_threads.append(threading.get_ident())
                return True

            def listdir_entries(self, path: str):
                self.discovery_threads.append(threading.get_ident())
                return [
                    RemoteEntry(
                        name="payload.bin",
                        path=f"{path}/payload.bin",
                        is_dir=False,
                        size=7,
                        mtime=0,
                    )
                ]

            def download(self, _remote_path, local_path, progress_cb=None) -> None:
                self.download_threads.append(threading.get_ident())
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                    if self.active >= 2:
                        self.parallel_started.set()
                self.release.wait(3)
                Path(local_path).write_bytes(b"payload")
                if progress_cb is not None:
                    progress_cb(7, 7)
                with self.lock:
                    self.active -= 1

        files = PipelineFiles()
        panel = self.widget.panel_scratch
        session = {"connected": True, "files": files}
        panel.session = session
        panel._show_transfer_dialog = False
        gui_thread = threading.get_ident()
        dialog = None
        try:
            with tempfile.TemporaryDirectory() as tmp, patch(
                "truba_gui.ui.widgets.remote_dir_panel.get_transfer_parallelism",
                return_value=2,
            ):
                started_at = time.monotonic()
                self.assertTrue(
                    panel._apply_remote_download_incremental(
                        ["/remote/folder-a", "/remote/folder-b"],
                        tmp,
                    )
                )
                self.assertLess(time.monotonic() - started_at, 0.2)

                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    QApplication.processEvents()
                    if panel._transfer_dialogs:
                        dialog = panel._transfer_dialogs[-1]
                    if files.parallel_started.is_set():
                        break
                    time.sleep(0.01)

                self.assertIsNotNone(dialog)
                self.assertTrue(files.parallel_started.is_set())
                self.assertEqual(dialog._parallel_limit, 2)
                self.assertTrue(files.discovery_threads)
                self.assertTrue(files.download_threads)
                self.assertTrue(
                    all(thread_id != gui_thread for thread_id in files.discovery_threads)
                )
                self.assertTrue(
                    all(thread_id != gui_thread for thread_id in files.download_threads)
                )
                self.assertGreaterEqual(files.max_active, 2)

                files.release.set()
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline and not dialog.finished_cleanly():
                    QApplication.processEvents()
                    time.sleep(0.01)
                self.assertTrue(dialog.finished_cleanly())
        finally:
            files.release.set()
            if dialog is not None:
                dialog.cancel_all()
                dialog.deleteLater()

    def test_transfer_completion_invalidates_upload_target_and_download_sources(self) -> None:
        class Files:
            supports_parallel_transfers = False

            @staticmethod
            def exists(_path: str) -> bool:
                return False

            @staticmethod
            def is_dir(_path: str) -> bool:
                return True

            @staticmethod
            def listdir_entries(_path: str):
                return []

        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": Files()}
        callbacks = []

        def capture(_plan, _title, after_finished=None, **_kwargs):
            callbacks.append(after_finished)
            return True

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            panel,
            "_run_plan_with_progress",
            side_effect=capture,
        ):
            local_file = Path(tmp, "upload.bin")
            local_file.write_bytes(b"data")
            self.assertTrue(
                panel._apply_local_upload_incremental(
                    [str(local_file)],
                    "/remote/target",
                )
            )
            self.assertTrue(
                panel._apply_remote_download_incremental(
                    ["/remote/source/folder"],
                    tmp,
                )
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and len(callbacks) < 2:
                self.app.processEvents()
                time.sleep(0.01)

        self.assertEqual(len(callbacks), 2)
        for key in (
            "/remote/target",
            "/remote/source",
            "/remote/source/folder",
        ):
            panel._directory_cache[key] = (0.0, [])
        for callback in callbacks:
            self.assertIsNotNone(callback)
            callback()
        self.assertNotIn("/remote/target", panel._directory_cache)
        self.assertNotIn("/remote/source", panel._directory_cache)
        self.assertNotIn("/remote/source/folder", panel._directory_cache)

    def test_ftp_transfer_area_is_resizable_with_directory_area(self) -> None:
        self.assertIs(self.widget.transfer_splitter.widget(0), self.widget.splitter)
        self.assertIs(self.widget.transfer_splitter.widget(1), self.widget.transfer_activity)
        self.assertEqual(self.widget.transfer_splitter.orientation(), Qt.Orientation.Vertical)

    def test_double_click_activation_routes_to_transfer_targets(self) -> None:
        local_file = Path(__file__).resolve()
        self.widget.panel_scratch.current_dir = "/remote"
        self.widget.session = {"connected": True}

        with patch.object(
            self.widget.panel_scratch,
            "_apply_local_upload_incremental",
            return_value=True,
        ) as upload:
            self.widget.local_panel.fileActivated.emit(str(local_file))
        upload.assert_called_once_with([str(local_file)], "/remote")

        with patch.object(
            self.widget.panel_scratch,
            "_apply_remote_download_incremental",
            return_value=True,
        ) as download:
            self.widget.panel_scratch.file_activated.emit("/remote/out.txt")
        download.assert_called_once_with(["/remote/out.txt"], self.widget.local_panel.current_dir)

    def test_double_click_activation_does_not_start_duplicate_upload(self) -> None:
        local_file = Path(__file__).resolve()
        self.widget.panel_scratch.current_dir = "/remote"
        self.widget.session = {"connected": True}

        with (
            patch(
                "truba_gui.ui.widgets.ftp_widget.monotonic",
                side_effect=[10.0, 10.1, 11.2],
            ),
            patch.object(
                self.widget.panel_scratch,
                "_apply_local_upload_incremental",
                return_value=True,
            ) as upload,
        ):
            self.widget.local_panel.fileActivated.emit(str(local_file))
            self.widget.local_panel.fileActivated.emit(str(local_file))
            self.widget.local_panel.fileActivated.emit(str(local_file))

        self.assertEqual(upload.call_count, 2)
        upload.assert_called_with([str(local_file)], "/remote")

    def test_active_upload_plan_is_not_queued_twice(self) -> None:
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": _Files()}
        source = str(Path(__file__).resolve())
        target = "/remote/test_ftp_widget.py"
        panel._active_transfer_keys.add(("upload", source, target))
        events = []
        panel.set_transfer_activity_callback(
            lambda event, items, title: events.append((event, items, title))
        )

        self.assertTrue(
            panel._run_plan_with_progress(
                [_PlannedOp("upload", source, target)],
                "Yükleniyor...",
            )
        )

        self.assertEqual(events, [])

    def test_settings_offer_exact_transfer_modes_and_default_auto(self) -> None:
        with patch(
            "truba_gui.ui.dialogs.settings_dialog.get_ftp_transfer_type",
            return_value=AUTO,
        ):
            dialog = SettingsDialog()
            try:
                self.assertEqual(
                    [
                        dialog.cb_ftp_transfer_type.itemData(index)
                        for index in range(dialog.cb_ftp_transfer_type.count())
                    ],
                    [AUTO, BINARY, ASCII],
                )
                self.assertEqual(dialog.cb_ftp_transfer_type.currentData(), AUTO)
            finally:
                dialog.deleteLater()

    def test_connection_dialog_applies_truba_system_template_from_menu(self) -> None:
        dialog = ConnectionDialog()
        try:
            dialog.scratch_dir.setText("/custom/scratch")
            dialog.home_dir.setText("/custom/home")

            root_menu = dialog.btn_system_templates.menu()
            self.assertIsNotNone(root_menu)
            truba_menu = root_menu.actions()[0].menu()
            self.assertIsNotNone(truba_menu)
            self.assertEqual(root_menu.actions()[0].text(), "TRUBA")
            truba_menu.actions()[0].trigger()

            self.assertEqual(dialog.system_name.text(), "TRUBA")
            self.assertEqual(dialog.scratch_dir.text(), TRUBA_SYSTEM_DEFAULTS["scratch_dir"])
            self.assertEqual(dialog.home_dir.text(), TRUBA_SYSTEM_DEFAULTS["home_dir"])
        finally:
            dialog.deleteLater()

    def test_connection_dialog_saves_current_system_as_user_template(self) -> None:
        dialog = ConnectionDialog()
        try:
            dialog.system_name.setText("My Cluster")
            dialog.scratch_dir.setText("/work/{user}")
            dialog.home_dir.setText("/home/{user}")
            with (
                patch(
                    "truba_gui.ui.dialogs.connection_dialog.QInputDialog.getText",
                    return_value=("My Cluster", True),
                ),
                patch(
                    "truba_gui.ui.dialogs.connection_dialog.save_user_system_template",
                    return_value=dict(TRUBA_SYSTEM_DEFAULTS, name="My Cluster"),
                ) as save_template,
                patch(
                    "truba_gui.ui.dialogs.connection_dialog.load_user_system_templates",
                    return_value=[],
                ),
            ):
                dialog._save_current_system_template()

            save_template.assert_called_once()
            name, values = save_template.call_args.args
            self.assertEqual(name, "My Cluster")
            self.assertEqual(values["scratch_dir"], "/work/{user}")
            self.assertEqual(values["home_dir"], "/home/{user}")
        finally:
            dialog.deleteLater()

    def test_user_system_template_persists_by_name(self) -> None:
        saved_settings = {"system_templates": []}

        def fake_update(patch_data):
            saved_settings.update(patch_data)
            return saved_settings

        with (
            patch(
                "truba_gui.config.system_profile.load_settings",
                side_effect=lambda: saved_settings,
            ),
            patch(
                "truba_gui.config.system_profile.update_settings",
                side_effect=fake_update,
            ) as update,
        ):
            first = save_user_system_template(
                "My Cluster",
                {
                    "name": "ignored",
                    "scratch_dir": "/work/{user}",
                    "home_dir": "/home/{user}",
                },
            )
            second = save_user_system_template(
                "my cluster",
                {
                    "scratch_dir": "/new/work",
                    "home_dir": "/new/home",
                },
            )

        self.assertEqual(first["name"], "My Cluster")
        self.assertEqual(second["name"], "my cluster")
        self.assertEqual(len(saved_settings["system_templates"]), 1)
        self.assertEqual(saved_settings["system_templates"][0]["scratch_dir"], "/new/work")
        self.assertGreaterEqual(update.call_count, 2)

    def test_transfer_mode_policy_and_conversion(self) -> None:
        self.assertEqual(resolve_transfer_mode("notes.txt", AUTO), ASCII)
        self.assertEqual(resolve_transfer_mode("archive", AUTO), BINARY)
        self.assertEqual(resolve_transfer_mode("image.bin", AUTO, b"\x00x"), BINARY)
        with self.assertRaises(ValueError):
            resolve_transfer_mode("image.bin", ASCII, b"\x00x")

        self.assertEqual(_ascii_bytes_for_remote(b"a\r\nb\r\n"), b"a\nb\n")
        self.assertEqual(
            _ascii_bytes_for_local(b"x\ny\n").decode("utf-8").splitlines(),
            ["x", "y"],
        )

    def test_download_with_mode_uses_final_file_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp, "large.bin")
            destination.write_bytes(b"partial-")
            files = _ResumableFiles(b"partial-complete")

            effective = download_with_mode(
                files,
                "/remote/large.bin",
                str(destination),
                BINARY,
            )

            self.assertEqual(effective, BINARY)
            self.assertEqual(files.calls, [str(destination)])
            self.assertEqual(destination.read_bytes(), b"partial-complete")

    def test_upload_with_mode_forwards_progress_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "payload.bin")
            source.write_bytes(b"\x00" + b"x" * 4096)
            files = _ProgressUploadFiles()
            progress = []

            effective = upload_with_mode(
                files,
                str(source),
                "/remote/payload.bin",
                BINARY,
                progress_cb=lambda done, total: progress.append((done, total)),
            )

            self.assertEqual(effective, BINARY)
            self.assertEqual(files.calls, [(str(source), "/remote/payload.bin")])
            self.assertEqual(progress[-1], (source.stat().st_size, source.stat().st_size))

    def test_local_file_drop_on_remote_panel_uploads_to_current_remote_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "drop-me.txt")
            source.write_text("drop", encoding="utf-8")
            panel = self.widget.panel_scratch
            panel.current_dir = "/remote/target"
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(source))])
            event = _FakeDropEvent(mime)

            with patch.object(panel, "_apply_local_upload_incremental", return_value=True) as upload:
                panel.views["all"].dropEvent(event)

                upload.assert_not_called()
                self.app.processEvents()

            upload.assert_called_once()
            uploaded_paths, target_dir = upload.call_args.args
            self.assertEqual([Path(path) for path in uploaded_paths], [source])
            self.assertEqual(target_dir, "/remote/target")
            self.assertTrue(event.accepted)
            self.assertFalse(event.ignored)

    def test_directories_widget_accepts_local_file_drop_for_remote_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "drop-dir.txt")
            source.write_text("drop", encoding="utf-8")
            widget = DirectoriesWidget()
            try:
                widget.panel_scratch.current_dir = "/scratch/drop-target"
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(source))])
                event = _FakeDropEvent(mime)

                with patch.object(
                    widget.panel_scratch,
                    "_apply_local_upload",
                    return_value=True,
                ) as upload:
                    widget.dropEvent(event)

                    upload.assert_not_called()
                    self.app.processEvents()

                upload.assert_called_once()
                uploaded_paths, target_dir = upload.call_args.args
                self.assertEqual([Path(path) for path in uploaded_paths], [source])
                self.assertEqual(target_dir, "/scratch/drop-target")
                self.assertTrue(event.accepted)
                self.assertFalse(event.ignored)
            finally:
                widget.shutdown()
                widget.deleteLater()

    def test_remote_panel_accepts_local_file_drop_on_panel_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "panel-drop.txt")
            source.write_text("drop", encoding="utf-8")
            panel = self.widget.panel_scratch
            panel.current_dir = "/remote/body-target"
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(source))])
            event = _FakeDropEvent(mime)

            with patch.object(panel, "_apply_local_upload_incremental", return_value=True) as upload:
                panel.dropEvent(event)

                upload.assert_not_called()
                self.app.processEvents()

            upload.assert_called_once()
            uploaded_paths, target_dir = upload.call_args.args
            self.assertEqual([Path(path) for path in uploaded_paths], [source])
            self.assertEqual(target_dir, "/remote/body-target")
            self.assertTrue(event.accepted)
            self.assertFalse(event.ignored)

    def test_remote_panel_drop_upload_planning_yields_before_transfer_start(self) -> None:
        class Files:
            supports_parallel_transfers = True

            def exists(self, _path: str) -> bool:
                return False

        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": Files()}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, "folder")
            folder.mkdir()
            for index in range(30):
                (folder / f"file-{index}.txt").write_text("x", encoding="utf-8")

            with patch.object(panel, "_run_plan_with_progress", return_value=True) as run_plan:
                self.assertTrue(
                    panel._apply_local_upload_incremental([str(folder)], "/remote")
                )
                run_plan.assert_not_called()

                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not run_plan.called:
                    self.app.processEvents()
                    time.sleep(0.01)

            self.assertTrue(run_plan.called)
            plan = run_plan.call_args.args[0]
            self.assertEqual(
                len([item for item in plan if item.op == "upload"]),
                30,
            )

    def test_remote_file_drop_on_local_panel_downloads_after_drop_event(self) -> None:
        panel = self.widget.panel_scratch
        panel.current_dir = "/remote"
        remote_path = "/remote/result.txt"
        mime = QMimeData()
        mime.setData(
            MIME_REMOTE_PATHS,
            _encode_payload(_DragPayload(paths=[remote_path], src_panel_id=panel.panel_id)),
        )
        event = _FakeDropEvent(mime)

        with patch.object(
            panel,
            "_apply_remote_download_incremental",
            return_value=True,
        ) as download:
            self.widget.local_panel.tree.dropEvent(event)

            download.assert_not_called()
            self.app.processEvents()

        download.assert_called_once_with([remote_path], self.widget.local_panel.current_dir)
        self.assertTrue(event.accepted)
        self.assertFalse(event.ignored)

    def test_jobs_files_context_menu_restores_output_follow_actions(self) -> None:
        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

        class FakeMenu:
            instances: list["FakeMenu"] = []
            choose_text = "Follow in Output 2"

            def __init__(self, _parent=None) -> None:
                self.actions: list[FakeAction | None] = []
                FakeMenu.instances.append(self)

            def addAction(self, text: str) -> FakeAction:
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                self.actions.append(None)

            def exec(self, _pos):
                for action in self.actions:
                    if action is not None and action.text == self.choose_text:
                        return action
                return None

        files = _Files()
        files.remote["/remote/out.log"] = b"out"
        panel = RemoteDirPanel()
        seen: list[tuple[int, str]] = []
        assigned: list[tuple[str, int, str]] = []
        try:
            panel.enable_output_menu = True
            panel.set_output_target_provider(
                lambda: [("window:1", "Follow window 1")]
            )
            panel.open_in_slot.connect(lambda slot, path: seen.append((slot, path)))
            panel.open_in_existing_follower.connect(
                lambda target, slot, path: assigned.append(
                    (target, slot, path)
                )
            )
            panel.set_session({"connected": True, "files": files})
            panel.set_dir("/remote")
            view = panel.views["all"]
            for index in range(view.topLevelItemCount()):
                item = view.topLevelItem(index)
                if item.text(0) == "out.log":
                    item.setSelected(True)
                    break

            with patch("truba_gui.ui.widgets.remote_dir_panel.QMenu", FakeMenu):
                panel._on_context_menu(view, QPoint(0, 0))
                FakeMenu.choose_text = "Assign to Follow window 1 Output 2"
                panel._on_context_menu(view, QPoint(0, 0))

            labels = [
                action.text
                for action in FakeMenu.instances[-1].actions
                if action is not None
            ]
            self.assertIn("Follow in Output 1", labels)
            self.assertIn("Follow in Output 2", labels)
            self.assertIn("Follow file in new window", labels)
            self.assertIn("Follow in Output 1 in new window", labels)
            self.assertIn("Follow in Output 2 in new window", labels)
            self.assertIn("Follow in Output 1 in new tab", labels)
            self.assertIn("Follow in Output 2 in new tab", labels)
            self.assertIn("Assign to Follow window 1 Output 1", labels)
            self.assertIn("Assign to Follow window 1 Output 2", labels)
            self.assertEqual(seen, [(1, "/remote/out.log")])
            self.assertEqual(
                assigned,
                [("window:1", 1, "/remote/out.log")],
            )
        finally:
            FakeMenu.choose_text = "Follow in Output 2"
            panel.deleteLater()

    def test_remote_context_menu_restores_sbatch_submit_action(self) -> None:
        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

        class FakeMenu:
            def __init__(self, _parent=None) -> None:
                self.actions: list[FakeAction | None] = []

            def addAction(self, text: str) -> FakeAction:
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                self.actions.append(None)

            def exec(self, _pos):
                for action in self.actions:
                    if action is not None and action.text == "Submit with sbatch":
                        return action
                return None

        files = _Files()
        files.remote["/remote/job.slurm"] = b"#!/bin/bash\n#SBATCH -J demo\n"
        panel = RemoteDirPanel()
        submitted: list[str] = []
        try:
            panel.submit_requested.connect(submitted.append)
            panel.set_session({"connected": True, "files": files})
            panel.set_dir("/remote")
            view = panel.views["all"]
            for index in range(view.topLevelItemCount()):
                item = view.topLevelItem(index)
                if item.text(0) == "job.slurm":
                    item.setSelected(True)
                    break

            with patch("truba_gui.ui.widgets.remote_dir_panel.QMenu", FakeMenu):
                panel._on_context_menu(view, QPoint(0, 0))

            self.assertEqual(submitted, ["/remote/job.slurm"])
        finally:
            panel.deleteLater()

    def test_remote_context_menu_runs_shell_script_action(self) -> None:
        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

        class FakeMenu:
            instances: list["FakeMenu"] = []

            def __init__(self, _parent=None) -> None:
                self.actions: list[FakeAction | None] = []
                FakeMenu.instances.append(self)

            def addAction(self, text: str) -> FakeAction:
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                self.actions.append(None)

            def exec(self, _pos):
                for action in self.actions:
                    if action is not None and action.text == "Run in terminal":
                        return action
                return None

        files = _Files()
        files.remote["/remote/run.sh"] = b"#!/bin/bash\necho ok\n"
        panel = RemoteDirPanel()
        shell_runs: list[str] = []
        try:
            panel.run_shell_requested.connect(shell_runs.append)
            panel.set_session({"connected": True, "files": files})
            panel.set_dir("/remote")
            view = panel.views["all"]
            for index in range(view.topLevelItemCount()):
                item = view.topLevelItem(index)
                if item.text(0) == "run.sh":
                    item.setSelected(True)
                    break

            with patch("truba_gui.ui.widgets.remote_dir_panel.QMenu", FakeMenu):
                panel._on_context_menu(view, QPoint(0, 0))

            labels = [
                action.text
                for action in FakeMenu.instances[-1].actions
                if action is not None
            ]
            self.assertIn("Run in terminal", labels)
            self.assertEqual(shell_runs, ["/remote/run.sh"])
        finally:
            panel.deleteLater()

    def test_remote_context_menu_restores_clipboard_actions(self) -> None:
        from truba_gui.services.file_clipboard import get_file_clipboard

        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

        class FakeMenu:
            instances: list["FakeMenu"] = []

            def __init__(self, _parent=None) -> None:
                self.actions: list[FakeAction | None] = []
                FakeMenu.instances.append(self)

            def addAction(self, text: str) -> FakeAction:
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                self.actions.append(None)

            def exec(self, _pos):
                return None

        files = _Files()
        files.remote["/remote/out.txt"] = b"out"
        panel = RemoteDirPanel()
        clipboard = get_file_clipboard()
        try:
            clipboard.set("copy", ["/remote/old.txt"])
            panel.set_session({"connected": True, "files": files})
            panel.set_dir("/remote")
            view = panel.views["all"]
            for index in range(view.topLevelItemCount()):
                item = view.topLevelItem(index)
                if item.text(0) == "out.txt":
                    item.setSelected(True)
                    break

            with patch("truba_gui.ui.widgets.remote_dir_panel.QMenu", FakeMenu):
                panel._on_context_menu(view, QPoint(0, 0))

            labels = [
                action.text
                for action in FakeMenu.instances[-1].actions
                if action is not None
            ]
            self.assertIn("Paste", labels)
            self.assertIn("Paste to local (download)", labels)
            self.assertIn("Copy", labels)
            self.assertIn("Move", labels)
        finally:
            clipboard.clear()
            panel.deleteLater()

    def test_remote_ctrl_c_and_ctrl_x_store_selected_paths(self) -> None:
        from truba_gui.services.file_clipboard import get_file_clipboard

        files = _Files()
        files.remote["/remote/out.txt"] = b"out"
        panel = RemoteDirPanel()
        clipboard = get_file_clipboard()
        try:
            panel.set_session({"connected": True, "files": files})
            panel.set_dir("/remote")
            view = panel.views["all"]
            for index in range(view.topLevelItemCount()):
                item = view.topLevelItem(index)
                if item.text(0) == "out.txt":
                    item.setSelected(True)
                    break

            copy_event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_C,
                Qt.KeyboardModifier.ControlModifier,
            )
            QApplication.sendEvent(view, copy_event)
            clip = clipboard.get()
            self.assertIsNotNone(clip)
            self.assertEqual(clip.op, "copy")
            self.assertEqual(clip.paths, ["/remote/out.txt"])

            cut_event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_X,
                Qt.KeyboardModifier.ControlModifier,
            )
            QApplication.sendEvent(view, cut_event)
            clip = clipboard.get()
            self.assertIsNotNone(clip)
            self.assertEqual(clip.op, "move")
            self.assertEqual(clip.paths, ["/remote/out.txt"])
        finally:
            clipboard.clear()
            panel.deleteLater()

    def test_local_ctrl_v_downloads_remote_clipboard_to_current_local_dir(self) -> None:
        from truba_gui.services.file_clipboard import get_file_clipboard

        clipboard = get_file_clipboard()
        try:
            clipboard.set("copy", ["/remote/out.txt"])
            self.widget.session = {"connected": True}
            with patch.object(
                self.widget.panel_scratch,
                "_apply_remote_download_incremental",
                return_value=True,
            ) as download:
                paste_event = QKeyEvent(
                    QEvent.Type.KeyPress,
                    Qt.Key.Key_V,
                    Qt.KeyboardModifier.ControlModifier,
                )
                QApplication.sendEvent(self.widget.local_panel.tree, paste_event)
            download.assert_called_once_with(
                ["/remote/out.txt"],
                self.widget.local_panel.current_dir,
            )
        finally:
            clipboard.clear()

    def test_mock_backend_exercises_remote_file_operations(self) -> None:
        files = MockFilesBackend()

        self.assertTrue(files.exists("/arf/scratch/user/example.txt"))
        self.assertFalse(files.is_dir("/arf/scratch/user/example.txt"))
        self.assertTrue(files.is_dir("/arf/scratch/user/project"))

        files.mkdir("/arf/scratch/user/newdir/sub")
        files.write_text("/arf/scratch/user/newdir/sub/a.txt", "alpha")
        self.assertIn("sub", files.listdir("/arf/scratch/user/newdir"))
        self.assertEqual(files.read_text("/arf/scratch/user/newdir/sub/a.txt"), "alpha")

        files.copy(
            "/arf/scratch/user/newdir",
            "/arf/scratch/user/copied",
            recursive=True,
        )
        self.assertEqual(files.read_text("/arf/scratch/user/copied/sub/a.txt"), "alpha")

        files.rename("/arf/scratch/user/copied/sub/a.txt", "/arf/scratch/user/copied/sub/b.txt")
        self.assertFalse(files.exists("/arf/scratch/user/copied/sub/a.txt"))
        self.assertTrue(files.exists("/arf/scratch/user/copied/sub/b.txt"))

        files.move("/arf/scratch/user/copied", "/arf/home/user/moved")
        self.assertFalse(files.exists("/arf/scratch/user/copied"))
        self.assertTrue(files.exists("/arf/home/user/moved/sub/b.txt"))

        files.remove("/arf/home/user/moved", recursive=True)
        self.assertFalse(files.exists("/arf/home/user/moved"))

    def test_local_panel_has_parent_entry_not_selected_for_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            child = Path(tmp, "child")
            child.mkdir()
            local = self.widget.local_panel
            self.assertTrue(local.set_dir(str(child)))

            parent_item = local.tree.topLevelItem(0)
            self.assertEqual(parent_item.text(0), "..")
            parent_item.setSelected(True)
            self.assertEqual(local.selected_paths(), [])

            local._open_item(parent_item, 0)
            self.assertEqual(Path(local.current_dir), Path(tmp))

    def test_local_panel_f2_renames_single_selected_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "old.txt")
            src.write_text("data", encoding="utf-8")
            local = self.widget.local_panel
            self.assertTrue(local.set_dir(tmp))
            for index in range(local.tree.topLevelItemCount()):
                item = local.tree.topLevelItem(index)
                if item.text(0) == "old.txt":
                    item.setSelected(True)
                    break
            with patch(
                "truba_gui.ui.widgets.local_dir_panel.QInputDialog.getText",
                return_value=("new.txt", True),
            ):
                event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F2, Qt.KeyboardModifier.NoModifier)
                local.tree.keyPressEvent(event)
            self.assertFalse(src.exists())
            self.assertTrue(Path(tmp, "new.txt").exists())

    def test_remote_panel_f2_uses_rename_action_for_single_selection(self) -> None:
        files = _Files()
        files.remote["/remote/old.txt"] = b"data"
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.current_dir = "/remote"
        panel.refresh()
        item = None
        for index in range(panel.views["all"].topLevelItemCount()):
            candidate = panel.views["all"].topLevelItem(index)
            if candidate.text(0) == "old.txt":
                item = candidate
                break
        self.assertIsNotNone(item)
        item.setSelected(True)
        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.QInputDialog.getText",
            return_value=("new.txt", True),
        ):
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F2, Qt.KeyboardModifier.NoModifier)
            self.assertTrue(panel.eventFilter(panel.views["all"], event))
        self.assertNotIn("/remote/old.txt", files.remote)
        self.assertIn("/remote/new.txt", files.remote)

    def test_remote_path_field_enter_navigates_and_backspace_goes_parent(self) -> None:
        files = _CountingFiles()
        panel = RemoteDirPanel()
        try:
            panel.set_session({"connected": True, "files": files})
            panel.set_dir("/remote")

            self.assertFalse(panel.path.isReadOnly())
            panel.path.setText("/remote/child")
            panel.path.returnPressed.emit()
            self.assertEqual(panel.current_dir, "/remote/child")
            self.assertEqual(panel.path.text(), "/remote/child")

            event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Backspace,
                Qt.KeyboardModifier.NoModifier,
            )
            self.assertTrue(panel.eventFilter(panel.views["all"], event))
            self.assertEqual(panel.current_dir, "/remote")
            self.assertEqual(panel.path.text(), "/remote")
        finally:
            panel.deleteLater()

    def test_local_context_menu_matches_requested_layout(self) -> None:
        self.assertEqual(
            LOCAL_CONTEXT_MENU_LABELS,
            [
                "Upload",
                "Add files to queue",
                "---",
                "Open",
                "Open with...",
                "Open in new tab",
                "Edit",
                "---",
                "Create directory",
                "Create directory and enter it",
                "Refresh",
                "---",
                "Delete",
                "Rename",
            ],
        )

    def test_local_context_open_uses_file_explorer_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "old.txt")
            src.write_text("data", encoding="utf-8")
            local = self.widget.local_panel
            self.assertTrue(local.set_dir(tmp))
            for index in range(local.tree.topLevelItemCount()):
                item = local.tree.topLevelItem(index)
                if item.text(0) == "old.txt":
                    item.setSelected(True)
                    break
            with patch("truba_gui.ui.widgets.local_dir_panel.subprocess.Popen") as popen:
                self.assertTrue(local.open_selected_in_file_explorer())
            popen.assert_called_once_with(["explorer", str(Path(tmp))])

    def test_local_open_with_chooses_program_and_saves_association(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "job.slurm")
            src.write_text("echo ok", encoding="utf-8")
            program = Path(tmp, "editor.exe")
            program.write_text("", encoding="utf-8")
            local = self.widget.local_panel
            self.assertTrue(local.set_dir(tmp))
            for index in range(local.tree.topLevelItemCount()):
                item = local.tree.topLevelItem(index)
                if item.text(0) == "job.slurm":
                    item.setSelected(True)
                    break
            with patch(
                "truba_gui.ui.widgets.local_dir_panel.get_file_association",
                return_value="",
            ), patch(
                "truba_gui.ui.widgets.local_dir_panel.QFileDialog.getOpenFileName",
                return_value=(str(program), ""),
            ), patch(
                "truba_gui.ui.widgets.local_dir_panel.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ), patch(
                "truba_gui.ui.widgets.local_dir_panel.set_file_association"
            ) as set_assoc, patch(
                "truba_gui.ui.widgets.local_dir_panel.subprocess.Popen"
            ) as popen:
                self.assertTrue(local.open_selected_with_program())

            set_assoc.assert_called_once_with(".slurm", str(program))
            popen.assert_called_once_with([str(program), str(src)])

    def test_settings_lists_and_clears_file_associations(self) -> None:
        with patch(
            "truba_gui.ui.dialogs.settings_dialog.get_file_associations",
            return_value={".slurm": r"C:\Tools\editor.exe"},
        ):
            dialog = SettingsDialog()
        try:
            self.assertEqual(dialog.file_associations_list.count(), 1)
            self.assertIn(".slurm", dialog.file_associations_list.item(0).text())
            dialog.file_associations_list.setCurrentRow(0)
            with patch(
                "truba_gui.ui.dialogs.settings_dialog.clear_file_association",
                return_value={},
            ) as clear_assoc:
                dialog._clear_selected_file_association()
            clear_assoc.assert_called_once_with(".slurm")
            self.assertEqual(dialog.file_associations_list.count(), 0)
        finally:
            dialog.deleteLater()

    def test_local_context_menu_opens_directory_in_new_tab(self) -> None:
        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

        class FakeMenu:
            def __init__(self, _parent=None) -> None:
                self.actions: list[FakeAction | None] = []

            def addAction(self, text: str) -> FakeAction:
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                self.actions.append(None)

            def exec(self, _pos):
                for action in self.actions:
                    if action is not None and action.text == "Open in new tab":
                        return action
                return None

        with tempfile.TemporaryDirectory() as tmp:
            child = Path(tmp, "child")
            child.mkdir()
            local = self.widget.local_panel
            self.assertTrue(local.set_dir(tmp))
            target_item = None
            for index in range(local.tree.topLevelItemCount()):
                item = local.tree.topLevelItem(index)
                if item.text(0) == "child":
                    target_item = item
                    item.setSelected(True)
                    break
            self.assertIsNotNone(target_item)

            with patch("truba_gui.ui.widgets.local_dir_panel.QMenu", FakeMenu):
                local._on_context_menu(local.tree.visualItemRect(target_item).center())

            self.assertEqual(local.tabs.count(), 2)
            self.assertEqual(Path(local.current_dir), child)

    def test_local_create_directory_and_enter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local = self.widget.local_panel
            self.assertTrue(local.set_dir(tmp))
            with patch(
                "truba_gui.ui.widgets.local_dir_panel.QInputDialog.getText",
                return_value=("child", True),
            ):
                self.assertTrue(local.create_directory(enter=True))
            self.assertEqual(Path(local.current_dir), Path(tmp, "child"))

    def test_remote_context_menu_matches_requested_layout(self) -> None:
        self.assertEqual(
            REMOTE_CONTEXT_MENU_LABELS,
            [
                "Download",
                "Add files to queue",
                "View/Edit",
                "Open in new tab",
                "---",
                "Create directory",
                "Create directory and enter it",
                "Create new file",
                "Refresh",
                "---",
                "Delete",
                "Rename",
                "Copy URL(s) to clipboard",
                "File permissions...",
            ],
        )

    def test_remote_create_directory_and_enter(self) -> None:
        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.current_dir = "/arf/scratch/user"
        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.QInputDialog.getText",
            return_value=("new-job", True),
        ):
            self.assertTrue(panel.create_new_folder_and_enter())
        self.assertEqual(panel.current_dir, "/arf/scratch/user/new-job")
        self.assertTrue(files.is_dir("/arf/scratch/user/new-job"))

    def test_remote_context_menu_opens_directory_in_new_tab(self) -> None:
        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

        class FakeMenu:
            def __init__(self, _parent=None) -> None:
                self.actions: list[FakeAction | None] = []

            def addAction(self, text: str) -> FakeAction:
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                self.actions.append(None)

            def exec(self, _pos):
                for action in self.actions:
                    if action is not None and action.text == "Open in new tab":
                        return action
                return None

        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.set_dir("/arf/scratch/user")
        view = panel.views["all"]
        for index in range(view.topLevelItemCount()):
            item = view.topLevelItem(index)
            if item.text(0) == "project":
                item.setSelected(True)
                break

        with patch("truba_gui.ui.widgets.remote_dir_panel.QMenu", FakeMenu):
            panel._on_context_menu(view, QPoint(0, 0))

        self.assertEqual(panel.tabs.count(), 7)
        self.assertEqual(panel.directory_tabs.count(), 2)
        self.assertEqual(panel.current_dir, "/arf/scratch/user/project")
        opened = panel.views["all"]
        self.assertTrue(
            any(
                opened.topLevelItem(i).text(0) == "input.dat"
                for i in range(opened.topLevelItemCount())
            )
        )

    def test_remote_context_menu_changes_file_permissions(self) -> None:
        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

        class FakeMenu:
            instances: list["FakeMenu"] = []

            def __init__(self, _parent=None) -> None:
                self.actions: list[FakeAction | None] = []
                FakeMenu.instances.append(self)

            def addAction(self, text: str) -> FakeAction:
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self) -> None:
                self.actions.append(None)

            def exec(self, _pos):
                for action in self.actions:
                    if action is not None and action.text == "File permissions...":
                        self.selected_action = action
                        return action
                return None

        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.set_dir("/arf/scratch/user")
        view = panel.views["all"]
        for index in range(view.topLevelItemCount()):
            item = view.topLevelItem(index)
            if item.text(0) == "example.txt":
                item.setSelected(True)
                break

        class FakePermissionsDialog:
            def __init__(self, _parent, initial_mode, target_name=""):
                self.initial_mode = initial_mode
                self.target_name = target_name

            def exec(self):
                return _PermissionsDialog.DialogCode.Accepted

            def selected_mode(self):
                return 0o600

        with patch("truba_gui.ui.widgets.remote_dir_panel.QMenu", FakeMenu), patch(
            "truba_gui.ui.widgets.remote_dir_panel._PermissionsDialog",
            FakePermissionsDialog,
        ):
            panel._on_context_menu(view, QPoint(0, 0))

        permission_action = getattr(FakeMenu.instances[-1], "selected_action")
        self.assertTrue(permission_action.enabled)
        entry = next(
            entry
            for entry in files.listdir_entries("/arf/scratch/user")
            if entry.name == "example.txt"
        )
        self.assertEqual(stat.S_IMODE(entry.mode), 0o600)

    def test_remote_change_permissions_rejects_invalid_mode(self) -> None:
        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.set_dir("/arf/scratch/user")
        view = panel.views["all"]
        for index in range(view.topLevelItemCount()):
            item = view.topLevelItem(index)
            if item.text(0) == "example.txt":
                item.setSelected(True)
                break

        class FakePermissionsDialog:
            def __init__(self, _parent, _initial_mode, _target_name=""):
                pass

            def exec(self):
                return _PermissionsDialog.DialogCode.Accepted

            def selected_mode(self):
                return None

        with patch(
            "truba_gui.ui.widgets.remote_dir_panel._PermissionsDialog",
            FakePermissionsDialog,
        ), patch("truba_gui.ui.widgets.remote_dir_panel.QMessageBox.warning") as warning:
            self.assertFalse(panel.change_permissions())

        warning.assert_called_once()
        entry = next(
            entry
            for entry in files.listdir_entries("/arf/scratch/user")
            if entry.name == "example.txt"
        )
        self.assertEqual(stat.S_IMODE(entry.mode), 0o644)

    def test_remote_change_permissions_accepts_four_digit_octal_mode(self) -> None:
        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.set_dir("/arf/scratch/user")
        view = panel.views["all"]
        for index in range(view.topLevelItemCount()):
            item = view.topLevelItem(index)
            if item.text(0) == "project":
                item.setSelected(True)
                break

        class FakePermissionsDialog:
            def __init__(self, _parent, _initial_mode, _target_name=""):
                pass

            def exec(self):
                return _PermissionsDialog.DialogCode.Accepted

            def selected_mode(self):
                return 0o1755

        with patch(
            "truba_gui.ui.widgets.remote_dir_panel._PermissionsDialog",
            FakePermissionsDialog,
        ):
            self.assertTrue(panel.change_permissions())

        entry = next(
            entry
            for entry in files.listdir_entries("/arf/scratch/user")
            if entry.name == "project"
        )
        self.assertEqual(stat.S_IMODE(entry.mode), 0o1755)

    def test_permissions_dialog_syncs_checkboxes_and_mode_field(self) -> None:
        dialog = _PermissionsDialog(self.widget, 0o640, "example.txt")
        try:
            self.assertEqual(dialog.windowTitle(), "Change file attributes")
            self.assertTrue(dialog._boxes[(0, 0)].isChecked())
            self.assertTrue(dialog._boxes[(1, 0)].isChecked())
            self.assertTrue(dialog._boxes[(0, 1)].isChecked())
            self.assertFalse(dialog._boxes[(2, 2)].isChecked())
            self.assertEqual(dialog.mode_edit.text(), "00640")

            dialog._boxes[(2, 2)].setChecked(True)
            self.assertEqual(dialog.mode_edit.text(), "00641")

            dialog._special_boxes[0o1000].setChecked(True)
            self.assertEqual(dialog.mode_edit.text(), "01641")

            dialog.mode_edit.setText("755")
            dialog._update_checks_from_code("755")
            self.assertTrue(dialog._boxes[(0, 0)].isChecked())
            self.assertTrue(dialog._boxes[(1, 0)].isChecked())
            self.assertTrue(dialog._boxes[(2, 0)].isChecked())
            self.assertTrue(dialog._boxes[(0, 1)].isChecked())
            self.assertFalse(dialog._boxes[(1, 1)].isChecked())
            self.assertTrue(dialog._boxes[(2, 2)].isChecked())
            self.assertEqual(dialog.selected_mode(), 0o755)

            dialog.mode_edit.setText("01755")
            dialog._update_checks_from_code("01755")
            self.assertTrue(dialog._special_boxes[0o1000].isChecked())
            self.assertEqual(dialog.selected_mode(), 0o1755)
        finally:
            dialog.deleteLater()

    def test_remote_directory_tabs_sit_above_filter_tabs(self) -> None:
        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.set_dir("/arf/scratch/user")

        self.assertTrue(panel.open_directory_in_new_tab("/arf/scratch/user/project"))
        self.assertEqual(panel.tabs.count(), 7)
        self.assertEqual(panel.directory_tabs.count(), 2)
        self.assertEqual(panel.current_dir, "/arf/scratch/user/project")

        panel.tabs.setCurrentWidget(panel.views["folders"])
        self.assertEqual(panel.current_dir, "/arf/scratch/user/project")
        self.assertEqual(panel.path.text(), "/arf/scratch/user/project")

        panel.directory_tabs.setCurrentIndex(0)
        self.assertEqual(panel.current_dir, "/arf/scratch/user")
        self.assertTrue(
            any(
                panel.views["all"].topLevelItem(index).text(0) == "project"
                for index in range(panel.views["all"].topLevelItemCount())
            )
        )

    def test_remote_folder_middle_click_opens_new_directory_tab(self) -> None:
        class FakePosition:
            @staticmethod
            def toPoint() -> QPoint:
                return QPoint(1, 1)

        class FakeMiddleRelease:
            accepted = False

            @staticmethod
            def button():
                return Qt.MouseButton.MiddleButton

            @staticmethod
            def position() -> FakePosition:
                return FakePosition()

            def accept(self) -> None:
                self.accepted = True

        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": MockFilesBackend()}
        panel.set_dir("/arf/scratch/user")
        view = panel.views["all"]
        folder = next(
            view.topLevelItem(index)
            for index in range(view.topLevelItemCount())
            if view.topLevelItem(index).text(0) == "project"
        )
        event = FakeMiddleRelease()

        with patch.object(
            view,
            "itemAt",
            return_value=folder,
        ), patch.object(
            panel,
            "open_directory_in_new_tab",
            return_value=True,
        ) as open_tab:
            view.mouseReleaseEvent(event)

        open_tab.assert_called_once_with("/arf/scratch/user/project")
        self.assertTrue(event.accepted)

    def test_remote_middle_click_ignores_file_parent_and_blank_space(self) -> None:
        class FakePosition:
            @staticmethod
            def toPoint() -> QPoint:
                return QPoint(1, 1)

        class FakeMiddleRelease:
            accepted = False

            @staticmethod
            def button():
                return Qt.MouseButton.MiddleButton

            @staticmethod
            def position() -> FakePosition:
                return FakePosition()

            def accept(self) -> None:
                self.accepted = True

        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": MockFilesBackend()}
        panel.set_dir("/arf/scratch/user")
        view = panel.views["all"]
        parent_item = next(
            view.topLevelItem(index)
            for index in range(view.topLevelItemCount())
            if view.topLevelItem(index).text(0) == ".."
        )
        file_item = next(
            view.topLevelItem(index)
            for index in range(view.topLevelItemCount())
            if not bool(
                view.topLevelItem(index).data(
                    0,
                    Qt.ItemDataRole.UserRole + 1,
                )
            )
        )

        with patch.object(
            panel,
            "open_directory_in_new_tab",
            return_value=True,
        ) as open_tab:
            for clicked_item in (file_item, parent_item, None):
                event = FakeMiddleRelease()
                with patch.object(view, "itemAt", return_value=clicked_item):
                    view.mouseReleaseEvent(event)
                self.assertTrue(event.accepted)

        open_tab.assert_not_called()

    def test_remote_directory_cache_reuses_recently_visited_directory(self) -> None:
        files = _CountingFiles()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}

        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.monotonic",
            side_effect=[0.0, 10.0, 20.0],
        ):
            panel.set_dir("/remote")
            panel.set_dir("/remote/child")
            panel.set_dir("/remote")

        self.assertEqual(files.calls, ["/remote", "/remote/child"])

    def test_remote_directory_cache_force_refresh_bypasses_cache(self) -> None:
        files = _CountingFiles()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}

        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.monotonic",
            side_effect=[0.0, 10.0, 20.0],
        ):
            panel.set_dir("/remote")
            panel.refresh()
            panel.refresh(force=True)

        self.assertEqual(files.calls, ["/remote", "/remote"])

    def test_remote_tree_f5_forces_refresh(self) -> None:
        panel = self.widget.panel_scratch
        view = panel.views["all"]
        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_F5,
            Qt.KeyboardModifier.NoModifier,
        )

        with patch.object(panel, "refresh") as refresh:
            QApplication.sendEvent(view, event)

        refresh.assert_called_once_with(force=True)

    def test_remote_directory_cache_expires_after_ttl(self) -> None:
        files = _CountingFiles()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}

        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.monotonic",
            side_effect=[0.0, 3601.0],
        ):
            panel.set_dir("/remote")
            panel.refresh()

        self.assertEqual(files.calls, ["/remote", "/remote"])

    def test_remote_directory_cache_lives_for_at_most_one_hour(self) -> None:
        files = _CountingFiles()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}

        self.assertEqual(DIRECTORY_CACHE_TTL_SECONDS, 3600.0)
        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.monotonic",
            side_effect=[0.0, 3599.0, 3601.0],
        ):
            panel.set_dir("/remote")
            panel.refresh()
            panel.refresh()

        self.assertEqual(files.calls, ["/remote", "/remote"])

    def test_remote_copy_move_refreshes_affected_cached_dirs_after_finish(self) -> None:
        files = _CountingFiles()
        source_panel = RemoteDirPanel()
        target_panel = self.widget.panel_scratch
        callbacks = []

        try:
            source_panel.session = {"connected": True, "files": files}
            target_panel.session = {"connected": True, "files": files}
            source_panel.set_dir("/remote")
            target_panel.set_dir("/remote/child")
            files.calls.clear()

            def fake_run(_plan, _title, after_finished=None):
                callbacks.append(after_finished)
                return True

            with patch.object(target_panel, "_run_plan_with_progress", side_effect=fake_run):
                self.assertTrue(
                    target_panel._apply_copy_move_with_conflicts(
                        "move",
                        ["/remote/root.txt"],
                        "/remote/child",
                    )
                )

            self.assertEqual(files.calls, [])
            self.assertEqual(len(callbacks), 1)
            self.assertIsNotNone(callbacks[0])

            callbacks[0]()

            self.assertCountEqual(files.calls, ["/remote", "/remote/child"])
        finally:
            source_panel.deleteLater()

    def test_remote_panel_shutdown_unregisters_idempotently_and_by_identity(self) -> None:
        panel = RemoteDirPanel()
        panel_id = panel.panel_id
        replacement = object()
        try:
            self.assertIs(RemoteDirPanel._instances.get(panel_id), panel)

            panel.shutdown()
            panel.shutdown()
            self.assertNotIn(panel_id, RemoteDirPanel._instances)

            RemoteDirPanel._instances[panel_id] = replacement
            panel.shutdown()
            self.assertIs(RemoteDirPanel._instances.get(panel_id), replacement)
        finally:
            if RemoteDirPanel._instances.get(panel_id) is replacement:
                RemoteDirPanel._instances.pop(panel_id, None)
            panel.deleteLater()

    def test_remote_panel_shutdown_waits_once_for_active_thread_without_planning_jobs(self) -> None:
        panel = RemoteDirPanel()

        class FakeThread:
            def __init__(self) -> None:
                self.quit_calls = 0
                self.wait_calls: list[int] = []

            def quit(self) -> None:
                self.quit_calls += 1

            def wait(self, timeout: int) -> None:
                self.wait_calls.append(timeout)

        active_thread = FakeThread()
        panel._active_thread = active_thread
        panel._planning_jobs.clear()
        try:
            panel.shutdown()

            self.assertEqual(active_thread.quit_calls, 1)
            self.assertEqual(active_thread.wait_calls, [1500])
        finally:
            panel.deleteLater()

    def test_remote_panel_shutdown_waits_once_for_active_and_each_planning_thread(self) -> None:
        panel = RemoteDirPanel()

        class FakeThread:
            def __init__(self) -> None:
                self.quit_calls = 0
                self.wait_calls: list[int] = []

            def quit(self) -> None:
                self.quit_calls += 1

            def wait(self, timeout: int) -> None:
                self.wait_calls.append(timeout)

        active_thread = FakeThread()
        planning_threads = [FakeThread(), FakeThread(), FakeThread()]
        planning_workers = [SimpleNamespace(cancelled=False) for _thread in planning_threads]
        panel._active_thread = active_thread
        panel._planning_jobs = {
            index: (thread, worker)
            for index, (thread, worker) in enumerate(zip(planning_threads, planning_workers))
        }
        try:
            panel.shutdown()

            self.assertEqual(active_thread.quit_calls, 1)
            self.assertEqual(active_thread.wait_calls, [1500])
            for thread in planning_threads:
                self.assertEqual(thread.quit_calls, 1)
                self.assertEqual(thread.wait_calls, [1500])
            self.assertTrue(all(worker.cancelled for worker in planning_workers))
        finally:
            panel.deleteLater()

    def test_remote_panel_deferred_delete_unregisters_instance(self) -> None:
        panel = RemoteDirPanel()
        panel_id = panel.panel_id
        try:
            self.assertIs(RemoteDirPanel._instances.get(panel_id), panel)
            panel.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            QApplication.processEvents()

            self.assertNotIn(panel_id, RemoteDirPanel._instances)
        finally:
            if RemoteDirPanel._instances.get(panel_id) is panel:
                RemoteDirPanel._instances.pop(panel_id, None)

    def test_remote_panel_deferred_delete_preserves_replacement_identity(self) -> None:
        panel = RemoteDirPanel()
        panel_id = panel.panel_id
        replacement = object()
        try:
            RemoteDirPanel._instances[panel_id] = replacement
            panel.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            QApplication.processEvents()

            self.assertIs(RemoteDirPanel._instances.get(panel_id), replacement)
        finally:
            if RemoteDirPanel._instances.get(panel_id) is replacement:
                RemoteDirPanel._instances.pop(panel_id, None)

    def test_remote_mutation_removes_panel_that_raises_deleted_qt_error(self) -> None:
        source = RemoteDirPanel()
        stale = RemoteDirPanel()
        stale.current_dir = "/remote"
        stale_id = stale.panel_id
        try:
            with patch.object(
                stale,
                "refresh",
                side_effect=RuntimeError(
                    "Internal C++ object (_RemoteTree) already deleted"
                ),
            ):
                source._finish_remote_directory_mutation(["/remote"])

            self.assertNotIn(stale_id, RemoteDirPanel._instances)
        finally:
            source.shutdown()
            stale.shutdown()
            source.deleteLater()
            stale.deleteLater()

    def test_mock_ftp_download_writes_selected_remote_file(self) -> None:
        files = MockFilesBackend()
        cfg = SimpleNamespace(
            username="user",
            system_settings={
                "scratch_dir": "/arf/scratch/{user}",
                "home_dir": "/arf/home/{user}",
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            self.widget.local_panel.current_dir = tmp
            self.widget.set_session({"connected": True, "files": files, "cfg": cfg})
            with (
                patch.object(
                    self.widget,
                    "_selected_remote_paths",
                    return_value=["/arf/scratch/user/example.txt"],
                ),
                patch.object(
                    RemoteDirPanel,
                    "_run_plan_with_progress",
                    self._run_plan_synchronously,
                ),
            ):
                self.assertTrue(self.widget.download_selected())
                target = Path(tmp, "example.txt")
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not target.exists():
                    self.app.processEvents()
                    time.sleep(0.01)

            self.assertEqual(
                Path(tmp, "example.txt").read_text(encoding="utf-8"),
                "Mock file content\nline2\n",
            )

    def test_download_existing_target_uses_conflict_dialog_decision(self) -> None:
        files = _Files()
        files.remote["/remote/existing.txt"] = b"remote"
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp, "existing.txt")
            target.write_text("local", encoding="utf-8")
            with (
                patch.object(panel, "_resolve_conflict", return_value="skip") as resolve,
                patch.object(panel, "_run_plan_with_progress") as run_plan,
            ):
                self.assertTrue(panel._apply_remote_download(["/remote/existing.txt"], tmp))
            resolve.assert_called_once()
            self.assertEqual(resolve.call_args.args[0], str(target))
            self.assertEqual(resolve.call_args.kwargs["src"], "/remote/existing.txt")
            self.assertFalse(run_plan.called)

    def test_download_resume_keeps_partial_target_and_plans_one_transfer(self) -> None:
        files = _Files()
        files.remote["/remote/existing.txt"] = b"remote"
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp, "existing.txt")
            target.write_text("part", encoding="utf-8")
            with (
                patch.object(panel, "_resolve_conflict", return_value="resume"),
                patch.object(panel, "_run_plan_with_progress", return_value=True) as run_plan,
            ):
                self.assertTrue(
                    panel._apply_remote_download(
                        ["/remote/existing.txt", "/remote/existing.txt"],
                        tmp,
                    )
                )

            plan = run_plan.call_args.args[0]
            self.assertEqual([(item.op, item.src, item.dst) for item in plan], [
                ("download", "/remote/existing.txt", str(target)),
            ])

    def test_upload_resume_keeps_remote_target_and_plans_one_transfer(self) -> None:
        files = _Files()
        files.remote["/remote/existing.txt"] = b"part"
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "existing.txt")
            source.write_text("remote", encoding="utf-8")
            with (
                patch.object(panel, "_resolve_conflict", return_value="resume"),
                patch.object(panel, "_run_plan_with_progress", return_value=True) as run_plan,
            ):
                self.assertTrue(
                    panel._apply_local_upload(
                        [str(source), str(source)],
                        "/remote",
                    )
                )

            plan = run_plan.call_args.args[0]
            self.assertEqual([(item.op, item.src, item.dst) for item in plan], [
                ("upload", str(source), "/remote/existing.txt"),
            ])

    def test_upload_folder_conflicts_ask_for_each_nested_file_without_apply_all(self) -> None:
        files = _Files()
        files.remote["/remote/folder/a.txt"] = b"old-a"
        files.remote["/remote/folder/b.txt"] = b"old-b"
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, "folder")
            folder.mkdir()
            (folder / "a.txt").write_text("new-a", encoding="utf-8")
            (folder / "b.txt").write_text("new-b", encoding="utf-8")

            with (
                patch.object(
                    panel,
                    "_resolve_conflict",
                    side_effect=["overwrite", "overwrite"],
                ) as resolve,
                patch.object(panel, "_run_plan_with_progress", return_value=True) as run_plan,
            ):
                self.assertTrue(panel._apply_local_upload([str(folder)], "/remote"))

        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in resolve.call_args_list],
            ["/remote/folder/a.txt", "/remote/folder/b.txt"],
        )
        plan = run_plan.call_args.args[0]
        self.assertEqual(
            [(item.op, item.dst) for item in plan if item.op == "delete"],
            [
                ("delete", "/remote/folder/a.txt"),
                ("delete", "/remote/folder/b.txt"),
            ],
        )

    def test_download_folder_conflicts_ask_for_each_nested_file_without_apply_all(self) -> None:
        class TreeFiles:
            def listdir_entries(self, path: str):
                if path.rstrip("/") == "/remote/folder":
                    return [
                        RemoteEntry("a.txt", "/remote/folder/a.txt", False, 5, 1),
                        RemoteEntry("b.txt", "/remote/folder/b.txt", False, 5, 1),
                    ]
                return []

            def exists(self, path: str) -> bool:
                return path.rstrip("/") == "/remote/folder"

            def is_dir(self, path: str) -> bool:
                return path.rstrip("/") == "/remote/folder"

            def stat(self, path: str):
                return (0, 1) if self.is_dir(path) else (5, 1)

        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": TreeFiles()}

        with tempfile.TemporaryDirectory() as tmp:
            local_folder = Path(tmp, "folder")
            local_folder.mkdir()
            (local_folder / "a.txt").write_text("old-a", encoding="utf-8")
            (local_folder / "b.txt").write_text("old-b", encoding="utf-8")

            with (
                patch.object(
                    panel,
                    "_resolve_conflict",
                    side_effect=["resume", "overwrite", "overwrite"],
                ) as resolve,
                patch.object(panel, "_run_plan_with_progress", return_value=True) as run_plan,
            ):
                self.assertTrue(panel._apply_remote_download(["/remote/folder"], tmp))

        self.assertEqual(resolve.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in resolve.call_args_list],
            [
                str(local_folder),
                str(local_folder / "a.txt"),
                str(local_folder / "b.txt"),
            ],
        )
        plan = run_plan.call_args.args[0]
        self.assertEqual(
            [(item.op, item.dst) for item in plan if item.op == "delete_local"],
            [
                ("delete_local", str(local_folder / "a.txt")),
                ("delete_local", str(local_folder / "b.txt")),
            ],
        )

    def test_active_download_plan_is_not_queued_twice(self) -> None:
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": _Files()}
        source = "/remote/existing.txt"
        target = str(Path(tempfile.gettempdir(), "existing.txt"))
        panel._active_transfer_keys.add(("download", source, target))
        events = []
        panel.set_transfer_activity_callback(
            lambda event, items, title: events.append((event, items, title))
        )

        self.assertTrue(
            panel._run_plan_with_progress(
                [_PlannedOp("download", source, target)],
                "İndiriliyor...",
            )
        )

        self.assertEqual(events, [])

    def test_mock_ftp_nested_directory_download_and_binary_upload(self) -> None:
        files = MockFilesBackend()
        cfg = SimpleNamespace(
            username="user",
            system_settings={
                "scratch_dir": "/arf/scratch/{user}",
                "home_dir": "/arf/home/{user}",
            },
        )
        self.widget.set_session({"connected": True, "files": files, "cfg": cfg})

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                RemoteDirPanel,
                "_run_plan_with_progress",
                self._run_plan_synchronously,
            ):
                self.assertTrue(
                    self.widget.panel_scratch._apply_remote_download(
                        ["/arf/scratch/user/project"],
                        tmp,
                    )
                )
            self.assertEqual(Path(tmp, "project", "input.dat").read_text(), "1 2 3\n")
            self.assertEqual(
                Path(tmp, "project", "nested", "result.bin").read_bytes(),
                b"\x00\x01\x02mock-binary",
            )

            local_bin = Path(tmp, "payload.bin")
            local_bin.write_bytes(b"\x00\xffraw")
            self.widget.panel_scratch.current_dir = "/arf/scratch/user/uploads"
            with patch.object(
                RemoteDirPanel,
                "_run_plan_with_progress",
                self._run_plan_synchronously,
            ):
                self.assertTrue(
                    self.widget.panel_scratch._apply_local_upload(
                        [str(local_bin)],
                        "/arf/scratch/user/uploads",
                    )
                )
            downloaded = Path(tmp, "roundtrip.bin")
            files.download("/arf/scratch/user/uploads/payload.bin", str(downloaded))
            self.assertEqual(downloaded.read_bytes(), b"\x00\xffraw")

    def test_ftp_mock_connection_is_environment_gated(self) -> None:
        with patch.dict(os.environ, {FTP_TEST_MODE_ENV: ""}):
            self.assertFalse(is_ftp_test_mode_enabled())
            self.assertTrue(is_ftp_mock_host("mock"))

        with patch.dict(os.environ, {FTP_TEST_MODE_ENV: "1"}):
            login = LoginWidget()
            try:
                login.host.setText("mock")
                login.username.setText("user")
                emitted = []
                login.session_changed.connect(lambda session: emitted.append(session))
                self.assertTrue(login.connect_clicked())
                self.assertTrue(emitted[-1]["connected"])
                self.assertIsInstance(emitted[-1]["files"], MockFilesBackend)
                self.assertTrue(emitted[-1]["cfg"].dry_run)
            finally:
                login.deleteLater()


if __name__ == "__main__":
    unittest.main()
