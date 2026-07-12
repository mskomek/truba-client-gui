from __future__ import annotations

import os
import json
import tempfile
import threading
import time
import unittest
import datetime
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QItemSelectionModel, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from truba_gui.core.i18n import load_language, t
from truba_gui.services.files_mock import MockFilesBackend
from truba_gui.services.files_ftp import FTPFilesBackend
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
from truba_gui.ui.dialogs.transfer_dialog import TransferDialog, TransferItem
from truba_gui.ui.dialogs.settings_dialog import SettingsDialog
from truba_gui.ui.main_window import MainWindow
from truba_gui.ui.widgets.directories_widget import DirectoriesWidget
from truba_gui.ui.widgets.ftp_widget import FtpWidget
from truba_gui.ui.widgets.local_dir_panel import LOCAL_CONTEXT_MENU_LABELS
from truba_gui.ui.widgets.login_widget import (
    FTP_TEST_MODE_ENV,
    LoginWidget,
    is_plain_ftp_target,
    is_ftp_mock_host,
    is_ftp_test_mode_enabled,
    normalize_plain_ftp_host,
)
from truba_gui.ui.widgets.remote_dir_panel import (
    MIME_REMOTE_PATHS,
    REMOTE_CONTEXT_MENU_LABELS,
    RemoteDirPanel,
    _PlannedOp,
)
from truba_gui.services.files_base import RemoteEntry


class _Files:
    supports_parallel_transfers = False

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

    def read_text(self, remote_path: str) -> str:
        return self.remote[remote_path].decode("utf-8")

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


class _FakeSignal:
    def connect(self, _callback) -> None:
        return None


class _FakeTransferDialog:
    captured_parallel_limits: list[int] = []
    captured_max_parallel_limits: list[int] = []

    def __init__(
        self,
        _parent=None,
        *,
        title: str,
        items: list[TransferItem],
        run_item,
        parallel_limit: int = 1,
        max_parallel_limit: int = 10,
    ) -> None:
        self.title = title
        self.items = items
        self.run_item = run_item
        self.parallel_limit = parallel_limit
        self.max_parallel_limit = max_parallel_limit
        self.finished = _FakeSignal()
        self.captured_parallel_limits.append(parallel_limit)
        self.captured_max_parallel_limits.append(max_parallel_limit)

    def start(self) -> None:
        return None

    def show(self) -> None:
        return None

    def finished_cleanly(self) -> bool:
        return True

    def deleteLater(self) -> None:
        return None


@contextmanager
def _local_ftp_server(root: Path, username: str = "user", password: str = "pass"):
    try:
        from pyftpdlib.authorizers import DummyAuthorizer
        from pyftpdlib.handlers import FTPHandler
        from pyftpdlib.servers import FTPServer
    except Exception as exc:  # pragma: no cover - environment dependent
        raise unittest.SkipTest(f"pyftpdlib is not available: {exc}") from exc

    authorizer = DummyAuthorizer()
    authorizer.add_user(username, password, str(root), perm="elradfmwMT")

    class Handler(FTPHandler):
        pass

    Handler.authorizer = authorizer
    Handler.banner = "TrubaGUI local FTP test server"
    server = FTPServer(("127.0.0.1", 0), Handler)
    port = int(server.socket.getsockname()[1])
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"timeout": 0.1, "blocking": True, "handle_exit": False},
        daemon=True,
    )
    thread.start()
    try:
        yield port
    finally:
        server.close_all()
        thread.join(timeout=2)


class FtpWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_language("en")
        cls.app = QApplication.instance() or QApplication([])

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
        self.widget.deleteLater()
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
            [
                f"{t('transfer.queued_files')} (0)",
                f"{t('transfer.failed_transfers')} (0)",
                f"{t('transfer.successful_transfers')} (0)",
            ],
        )
        self.assertEqual(
            [
                self.widget.transfer_activity.queue_list.headerItem().text(index)
                for index in range(self.widget.transfer_activity.queue_list.columnCount())
            ],
            [
                t("transfer.column_server_local_file"),
                t("transfer.column_direction"),
                t("transfer.column_remote_file"),
                t("transfer.column_size"),
                t("transfer.column_progress"),
                t("transfer.column_priority"),
                t("transfer.column_status"),
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

    def test_transfer_activity_failed_menu_retries_selected_errors(self) -> None:
        item = TransferItem("download", "/remote/a.txt", "a.txt")
        dialog = TransferDialog(
            title="Download",
            items=[item],
            run_item=lambda _item, _progress=None: None,
        )

        class FakeMenu:
            def __init__(self, _parent=None) -> None:
                self.action = None

            def addAction(self, _text):
                self.action = object()
                return self.action

            def exec(self, _pos):
                return self.action

        try:
            self.widget.transfer_activity.record("controller", [dialog], "Download")
            dialog.transferListsChanged.emit([], [(item, "boom")], [])
            row = self.widget.transfer_activity.failed_list.topLevelItem(0)
            self.widget.transfer_activity.failed_list.setCurrentItem(row)
            pos = self.widget.transfer_activity.failed_list.visualItemRect(row).center()
            with patch.object(dialog, "retry_selected_errors") as retry, patch(
                "truba_gui.ui.widgets.ftp_widget.QMenu",
                FakeMenu,
            ):
                self.widget.transfer_activity._show_failed_menu(pos)
            retry.assert_called_once()
        finally:
            dialog.deleteLater()

    def test_transfer_activity_queue_menu_removes_only_selected_transfer(self) -> None:
        selected = TransferItem("download", "/remote/a.txt", "a.txt")
        other = TransferItem("download", "/remote/b.txt", "b.txt")
        dialog = TransferDialog(
            title="Download",
            items=[selected, other],
            run_item=lambda _item, _progress=None: None,
        )

        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text

            def setCheckable(self, _checked: bool) -> None:
                return None

            def setChecked(self, _checked: bool) -> None:
                return None

            def setEnabled(self, _enabled: bool) -> None:
                return None

        class FakeMenu:
            def __init__(self, _parent=None) -> None:
                self.actions: list[FakeAction | None] = []

            def addAction(self, text: str) -> FakeAction:
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addMenu(self, text: str):
                submenu = FakeMenu()
                self.actions.append(FakeAction(text))
                return submenu

            def addSeparator(self) -> None:
                self.actions.append(None)

            def exec(self, _pos):
                for action in self.actions:
                    if action is not None and action.text == t("transfer.menu_remove_selected"):
                        return action
                return None

        try:
            self.widget.transfer_activity.record("controller", [dialog], "Download")
            dialog.transferListsChanged.emit([selected, other], [], [])
            row = self.widget.transfer_activity.queue_list.topLevelItem(0)
            self.widget.transfer_activity.queue_list.setCurrentItem(row)
            pos = self.widget.transfer_activity.queue_list.visualItemRect(row).center()
            with patch.object(dialog, "remove_pending_items") as remove_pending, patch.object(
                dialog, "clear_pending"
            ) as clear_pending, patch(
                "truba_gui.ui.widgets.ftp_widget.QMenu",
                FakeMenu,
            ):
                self.widget.transfer_activity._show_queue_menu(pos)

            remove_pending.assert_called_once()
            self.assertEqual(remove_pending.call_args.args[0], [selected])
            clear_pending.assert_not_called()
        finally:
            dialog.deleteLater()

    def test_transfer_dialog_remove_pending_items_keeps_unselected_items(self) -> None:
        selected = TransferItem("download", "/remote/a.txt", "a.txt")
        other = TransferItem("download", "/remote/b.txt", "b.txt")
        dialog = TransferDialog(
            title="Download",
            items=[selected, other],
            run_item=lambda _item, _progress=None: None,
        )
        try:
            dialog._refresh()
            dialog.remove_pending_items([selected])

            self.assertEqual(dialog._pending, [other])
            self.assertEqual(dialog.queue_list.count(), 1)
            self.assertEqual(
                dialog.queue_list.item(0).data(Qt.ItemDataRole.UserRole),
                other,
            )
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
            self.assertEqual(row.text(6), t("transfer.status_transferring"))
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

    def test_transfer_activity_uses_planned_remote_size_for_downloads(self) -> None:
        item = TransferItem(
            "download",
            "/remote/folder/a.txt",
            r"D:\target\folder\a.txt",
            size=4096,
        )

        self.widget.transfer_activity.record("queued", [item], "Download")

        row = self.widget.transfer_activity.queue_list.topLevelItem(0)
        self.assertEqual(row.text(3), "4.0 KB")
        self.assertIn(
            t("transfer.summary_total").format(count=1, size="4,096"),
            self.widget.transfer_activity.summary_label.text(),
        )

    def test_transfer_activity_does_not_show_zero_for_queued_folder_downloads(self) -> None:
        item = TransferItem(
            "download_tree",
            "/remote/folder",
            r"D:\target\folder",
            size=None,
        )

        self.widget.transfer_activity.record("queued", [item], "Download")

        row = self.widget.transfer_activity.queue_list.topLevelItem(0)
        self.assertEqual(row.text(1), "<--")
        self.assertEqual(row.text(3), "")
        self.assertIn(
            t("transfer.summary_calculating").format(count=1),
            self.widget.transfer_activity.summary_label.text(),
        )

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
                [t("transfer.priority_normal"), t("transfer.priority_normal")],
            )
            self.assertEqual(
                [
                    self.widget.transfer_activity.queue_list.topLevelItem(index).text(6)
                    for index in range(2)
                ],
                [t("transfer.status_transferring"), t("transfer.status_transferring")],
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

    def test_transfer_dialog_increases_parallel_limit_live(self) -> None:
        started: list[str] = []
        release = threading.Event()
        lock = threading.Lock()
        items = [
            TransferItem("download", f"/remote/{name}.bin", f"{name}.bin")
            for name in ("a", "b", "c")
        ]

        def run_item(item, _progress=None):
            with lock:
                started.append(item.src)
            release.wait(5)

        dialog = TransferDialog(
            title="Download",
            items=items,
            run_item=run_item,
            parallel_limit=1,
        )
        try:
            dialog.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                QApplication.processEvents()
                with lock:
                    if len(started) >= 1:
                        break
                time.sleep(0.01)
            with lock:
                self.assertEqual(len(started), 1)

            dialog.set_parallel_limit(3)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                QApplication.processEvents()
                with lock:
                    if len(started) >= 3:
                        break
                time.sleep(0.01)
            with lock:
                self.assertEqual(len(started), 3)
        finally:
            release.set()
            dialog.cancel_all()
            dialog.deleteLater()

    def test_transfer_dialog_decreases_parallel_limit_after_running_items_finish(self) -> None:
        started: list[str] = []
        finished: list[str] = []
        lock = threading.Lock()
        items = [
            TransferItem("download", f"/remote/{name}.bin", f"{name}.bin")
            for name in ("a", "b", "c", "d")
        ]
        releases = {item.src: threading.Event() for item in items}

        def run_item(item, _progress=None):
            with lock:
                started.append(item.src)
            releases[item.src].wait(5)
            with lock:
                finished.append(item.src)

        dialog = TransferDialog(
            title="Download",
            items=items,
            run_item=run_item,
            parallel_limit=3,
        )
        try:
            dialog.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                QApplication.processEvents()
                with lock:
                    if len(started) >= 3:
                        break
                time.sleep(0.01)
            with lock:
                self.assertEqual(len(started), 3)

            dialog.set_parallel_limit(1)
            with lock:
                first = started[0]
            releases[first].set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                QApplication.processEvents()
                with lock:
                    if len(finished) >= 1:
                        break
                time.sleep(0.01)
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.01)
            with lock:
                self.assertEqual(len(started), 3)

            for event in releases.values():
                event.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                QApplication.processEvents()
                with lock:
                    if len(started) >= 4:
                        break
                time.sleep(0.01)
            with lock:
                self.assertEqual(len(started), 4)
        finally:
            for event in releases.values():
                event.set()
            dialog.cancel_all()
            dialog.deleteLater()

    def test_transfer_dialog_respects_max_parallel_limit_when_settings_increase(self) -> None:
        started: list[str] = []
        release = threading.Event()
        lock = threading.Lock()
        items = [
            TransferItem("upload", f"local-{name}.txt", f"/remote/{name}.txt")
            for name in ("a", "b")
        ]

        def run_item(item, _progress=None):
            with lock:
                started.append(item.src)
            release.wait(5)

        dialog = TransferDialog(
            title="Upload",
            items=items,
            run_item=run_item,
            parallel_limit=1,
            max_parallel_limit=1,
        )
        try:
            dialog.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                QApplication.processEvents()
                with lock:
                    if len(started) >= 1:
                        break
                time.sleep(0.01)
            dialog.set_parallel_limit(5)
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.01)
            with lock:
                self.assertEqual(len(started), 1)
        finally:
            release.set()
            dialog.cancel_all()
            dialog.deleteLater()

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
        opened_new_window = []
        submitted = []
        self.widget.openFileRequested.connect(opened.append)
        self.widget.openFileInNewWindowRequested.connect(opened_new_window.append)
        self.widget.submitRequested.connect(submitted.append)

        self.widget.panel_scratch.open_file.emit("/scratch/readme.txt")
        self.widget.panel_home.open_file.emit("/home/script.slurm")
        self.widget.panel_scratch.open_file_in_new_window.emit("/scratch/edit.py")
        self.widget.panel_home.open_file_in_new_window.emit("/home/edit.py")
        self.widget.panel_scratch.submit_requested.emit("/scratch/a.slurm")
        self.widget.panel_home.submit_requested.emit("/home/b.sbatch")

        self.assertEqual(
            opened,
            ["/scratch/readme.txt", "/home/script.slurm"],
        )
        self.assertEqual(
            opened_new_window,
            ["/scratch/edit.py", "/home/edit.py"],
        )
        self.assertEqual(
            submitted,
            ["/scratch/a.slurm", "/home/b.sbatch"],
        )

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

    def test_main_window_routes_ftp_actions_to_existing_directories_handlers(self) -> None:
        opened = []
        opened_new_window = []
        submitted = []

        def record_open(_self, path):
            opened.append(path)

        def record_open_new_window(_self, path):
            opened_new_window.append(path)

        def record_submit(_self, path):
            submitted.append(path)

        with (
            patch("truba_gui.ui.main_window.QTimer.singleShot"),
            patch.object(DirectoriesWidget, "on_open_file", record_open),
            patch.object(
                DirectoriesWidget,
                "on_open_file_in_new_window",
                record_open_new_window,
            ),
            patch.object(DirectoriesWidget, "submit_script", record_submit),
        ):
            window = MainWindow()
            try:
                window.ftp.panel_scratch.open_file.emit("/scratch/file.txt")
                window.ftp.panel_scratch.open_file_in_new_window.emit(
                    "/scratch/edit.py"
                )
                window.ftp.panel_home.submit_requested.emit("/home/job.slurm")

                self.assertEqual(opened, ["/scratch/file.txt"])
                self.assertEqual(opened_new_window, ["/scratch/edit.py"])
                self.assertEqual(submitted, ["/home/job.slurm"])
            finally:
                window.graceful_shutdown()
                window.deleteLater()

    def test_directories_new_window_edit_reads_remote_file(self) -> None:
        files = _Files()
        files.remote["/remote/edit.py"] = b"print('ok')\n"
        widget = DirectoriesWidget()
        seen: list[tuple[str, str]] = []
        try:
            widget.session = {"connected": True, "files": files}
            widget.open_in_editor_window.connect(
                lambda path, content: seen.append((path, content))
            )

            widget.on_open_file_in_new_window("/remote/edit.py")

            self.assertEqual(seen, [("/remote/edit.py", "print('ok')\n")])
        finally:
            widget.shutdown()
            widget.deleteLater()

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

    def test_main_window_can_keep_current_tab_after_sbatch_submission(self) -> None:
        focus_calls = []

        def record_focus(
            job_id,
            script_path="",
            *,
            switch_to_outputs=True,
            follow_mode="outputs_tab",
        ):
            focus_calls.append((job_id, script_path, switch_to_outputs, follow_mode))

        with (
            patch("truba_gui.ui.main_window.QTimer.singleShot"),
            patch(
                "truba_gui.ui.main_window.get_sbatch_auto_open_outputs_enabled",
                return_value=False,
            ),
            patch(
                "truba_gui.ui.main_window.get_sbatch_follow_mode",
                return_value="new_windows_split",
            ),
        ):
            window = MainWindow()
            try:
                window.jobs_outputs.focus_job = record_focus
                window.tabs.setCurrentWidget(window.directories)

                window.on_script_submitted("12345", "/remote/job.slurm")

                self.assertIs(window.tabs.currentWidget(), window.directories)
                self.assertEqual(
                    focus_calls,
                    [("12345", "/remote/job.slurm", False, "new_windows_split")],
                )
            finally:
                window.graceful_shutdown()
                window.deleteLater()

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
            self.assertEqual(
                updates[-1],
                ("/arf/scratch/{user}", "/arf/home/{user}"),
            )
            self.assertEqual(
                dialog.ftp_home_dir.text(),
                "/arf/home/{user}",
            )
        finally:
            dialog.deleteLater()

    def test_settings_save_does_not_refresh_profile_when_remote_defaults_unchanged(self) -> None:
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
            with patch("truba_gui.ui.dialogs.settings_dialog.update_settings"):
                dialog._save_and_close()
            self.assertEqual(updates, [])
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
                self.widget.panel_scratch, "_apply_local_upload", return_value=True
            ) as upload,
        ):
            self.assertTrue(self.widget.upload_selected())
        upload.assert_called_once_with([str(local_file)], "/remote")

        with (
            patch.object(
                self.widget, "_selected_remote_paths", return_value=["/remote/out.txt"]
            ),
            patch.object(
                self.widget.panel_scratch, "_apply_remote_download", return_value=True
            ) as download,
        ):
            self.assertTrue(self.widget.download_selected())
        download.assert_called_once()
        self.assertEqual(
            download.call_args.args,
            (["/remote/out.txt"], self.widget.local_panel.current_dir),
        )
        self.assertIn("after_finished", download.call_args.kwargs)

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
            "_apply_local_upload",
            return_value=True,
        ) as upload:
            self.widget.local_panel.fileActivated.emit(str(local_file))
        upload.assert_called_once_with([str(local_file)], "/remote")

        with patch.object(
            self.widget.panel_scratch,
            "_apply_remote_download",
            return_value=True,
        ) as download:
            self.widget.panel_scratch.file_activated.emit("/remote/out.txt")
        download.assert_called_once()
        self.assertEqual(
            download.call_args.args,
            (["/remote/out.txt"], self.widget.local_panel.current_dir),
        )
        self.assertIn("after_finished", download.call_args.kwargs)

    def test_download_refreshes_local_target_after_transfer_finishes(self) -> None:
        panel = self.widget.panel_scratch
        files = _Files()
        files.remote["/remote/out.txt"] = b"payload"
        panel.session = {"connected": True, "files": files}
        self.widget.session = {"connected": True}
        callbacks = []

        def fake_run(_plan, _title, after_finished=None):
            callbacks.append(after_finished)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(self.widget.local_panel.set_dir(tmp))
            with (
                patch.object(
                    self.widget,
                    "_selected_remote_paths",
                    return_value=["/remote/out.txt"],
                ),
                patch.object(
                    panel,
                    "_run_plan_with_progress",
                    side_effect=fake_run,
                ),
                patch.object(self.widget.local_panel, "refresh") as refresh,
            ):
                self.assertTrue(self.widget.download_selected())
                refresh.assert_not_called()
                self.assertEqual(len(callbacks), 1)
                callbacks[0]()
                refresh.assert_called_once()

    def test_remote_panel_download_refreshes_visible_local_target_after_finish(self) -> None:
        panel = self.widget.panel_scratch
        files = _Files()
        files.remote["/remote/out.txt"] = b"payload"
        panel.session = {"connected": True, "files": files}
        callbacks = []

        def fake_run(_plan, _title, after_finished=None):
            callbacks.append(after_finished)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(self.widget.local_panel.set_dir(tmp))
            with (
                patch.object(panel, "_run_plan_with_progress", side_effect=fake_run),
                patch.object(self.widget.local_panel, "refresh") as refresh,
            ):
                self.assertTrue(panel._apply_remote_download(["/remote/out.txt"], tmp))
                refresh.assert_not_called()
                self.assertEqual(len(callbacks), 1)
                callbacks[0]()
                refresh.assert_called_once()

    def test_download_auto_refresh_can_be_disabled(self) -> None:
        panel = self.widget.panel_scratch
        files = _Files()
        files.remote["/remote/out.txt"] = b"payload"
        panel.session = {"connected": True, "files": files}
        callbacks = []

        def fake_run(_plan, _title, after_finished=None):
            callbacks.append(after_finished)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(self.widget.local_panel.set_dir(tmp))
            with (
                patch.object(panel, "_run_plan_with_progress", side_effect=fake_run),
                patch(
                    "truba_gui.ui.widgets.ftp_widget.get_transfer_auto_refresh_enabled",
                    return_value=False,
                ),
                patch.object(self.widget.local_panel, "refresh") as refresh,
            ):
                self.assertTrue(panel._apply_remote_download(["/remote/out.txt"], tmp))
                self.assertEqual(len(callbacks), 1)
                callbacks[0]()
                refresh.assert_not_called()

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
                "_apply_local_upload",
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

    def test_settings_can_disable_sbatch_auto_open_outputs(self) -> None:
        with (
            patch(
                "truba_gui.ui.dialogs.settings_dialog.get_sbatch_auto_open_outputs_enabled",
                return_value=True,
            ),
            patch(
                "truba_gui.ui.dialogs.settings_dialog.get_sbatch_follow_mode",
                return_value="new_tabs_split",
            ),
            patch(
                "truba_gui.ui.dialogs.settings_dialog.update_settings",
                return_value={},
            ) as update_settings,
            patch(
                "truba_gui.ui.dialogs.settings_dialog.update_ftp_state",
                return_value={},
            ),
        ):
            dialog = SettingsDialog()
            try:
                self.assertTrue(dialog.cb_sbatch_auto_open_outputs.isChecked())
                dialog.cb_sbatch_auto_open_outputs.setChecked(False)
                dialog._save_and_close()
            finally:
                dialog.deleteLater()

        self.assertFalse(
            update_settings.call_args.args[0]["sbatch_auto_open_outputs"]
        )

    def test_settings_can_choose_sbatch_follow_mode(self) -> None:
        with (
            patch(
                "truba_gui.ui.dialogs.settings_dialog.get_sbatch_follow_mode",
                return_value="new_tabs_split",
            ),
            patch(
                "truba_gui.ui.dialogs.settings_dialog.update_settings",
                return_value={},
            ) as update_settings,
            patch(
                "truba_gui.ui.dialogs.settings_dialog.update_ftp_state",
                return_value={},
            ),
        ):
            dialog = SettingsDialog()
            try:
                index = dialog.cb_sbatch_follow_mode.findData("new_windows_split")
                self.assertGreaterEqual(index, 0)
                dialog.cb_sbatch_follow_mode.setCurrentIndex(index)
                dialog._save_and_close()
            finally:
                dialog.deleteLater()

        self.assertEqual(
            update_settings.call_args.args[0]["sbatch_follow_mode"],
            "new_windows_split",
        )

    def test_sbatch_follow_mode_options_have_hover_explanations(self) -> None:
        dialog = SettingsDialog()
        try:
            expected_modes = {
                "new_tabs_split",
                "new_window_combined",
                "new_windows_split",
                "outputs_tab",
            }
            seen_modes = set()
            for index in range(dialog.cb_sbatch_follow_mode.count()):
                mode = dialog.cb_sbatch_follow_mode.itemData(index)
                seen_modes.add(mode)
                tooltip = dialog.cb_sbatch_follow_mode.itemData(
                    index,
                    Qt.ItemDataRole.ToolTipRole,
                )
                self.assertIsInstance(tooltip, str)
                self.assertTrue(tooltip.strip())

            self.assertEqual(seen_modes, expected_modes)
        finally:
            dialog.deleteLater()

    def test_settings_can_disable_transfer_auto_refresh(self) -> None:
        with (
            patch(
                "truba_gui.ui.dialogs.settings_dialog.get_transfer_auto_refresh_enabled",
                return_value=True,
            ),
            patch(
                "truba_gui.ui.dialogs.settings_dialog.update_settings",
                return_value={},
            ) as update_settings,
            patch(
                "truba_gui.ui.dialogs.settings_dialog.update_ftp_state",
                return_value={},
            ),
        ):
            dialog = SettingsDialog()
            try:
                self.assertTrue(dialog.cb_transfer_auto_refresh.isChecked())
                dialog.cb_transfer_auto_refresh.setChecked(False)
                dialog._save_and_close()
            finally:
                dialog.deleteLater()

        self.assertFalse(
            update_settings.call_args.args[0]["transfer_auto_refresh_enabled"]
        )

    def test_settings_show_and_save_persistent_ftp_state(self) -> None:
        with (
            patch(
                "truba_gui.ui.dialogs.settings_dialog.get_ftp_state",
                return_value={
                    "local_dir": r"C:\ftp-target",
                    "active_remote": "home",
                    "splitter_sizes": [300, 700],
                },
            ),
            patch(
                "truba_gui.ui.dialogs.settings_dialog.get_ftp_transfer_type",
                return_value=AUTO,
            ),
            patch(
                "truba_gui.ui.dialogs.settings_dialog.update_settings",
                return_value={},
            ),
            patch(
                "truba_gui.ui.dialogs.settings_dialog.update_ftp_state",
                return_value={},
            ) as update_ftp_state,
        ):
            dialog = SettingsDialog()
            try:
                self.assertEqual(dialog.ftp_local_dir.text(), r"C:\ftp-target")
                self.assertEqual(dialog.cb_ftp_active_remote.currentData(), "home")

                dialog.ftp_local_dir.setText(r"D:\downloads")
                dialog.cb_ftp_active_remote.setCurrentIndex(
                    dialog.cb_ftp_active_remote.findData("scratch")
                )
                dialog._save_and_close()

                update_ftp_state.assert_called_once_with(
                    local_dir=r"D:\downloads",
                    active_remote="scratch",
                )
            finally:
                dialog.deleteLater()

    def test_ftp_apply_settings_updates_active_transfer_parallel_limit(self) -> None:
        class Controller:
            def __init__(self) -> None:
                self.limits: list[int] = []

            def set_parallel_limit(self, value: int) -> None:
                self.limits.append(value)

        controller = Controller()
        self.widget.transfer_activity._controller = controller
        with (
            patch("truba_gui.ui.widgets.ftp_widget.get_ftp_transfer_type", return_value=AUTO),
            patch("truba_gui.ui.widgets.ftp_widget.get_transfer_parallelism", return_value=6),
        ):
            self.widget.apply_settings()

        self.assertEqual(controller.limits, [6])

    def test_plain_ftp_login_and_widget_operations_against_local_server(self) -> None:
        self.assertTrue(is_plain_ftp_target("ftp://127.0.0.1", 2121))
        self.assertTrue(is_plain_ftp_target("127.0.0.1", 21))
        self.assertEqual(normalize_plain_ftp_host("ftp://127.0.0.1/root"), "127.0.0.1")

        with tempfile.TemporaryDirectory() as server_tmp, tempfile.TemporaryDirectory() as local_tmp:
            root = Path(server_tmp)
            scratch = root / "arf" / "scratch" / "user"
            home = root / "arf" / "home" / "user"
            scratch.mkdir(parents=True)
            home.mkdir(parents=True)
            (scratch / "remote.txt").write_text("remote\n", encoding="utf-8")
            (scratch / "folder").mkdir()
            (scratch / "folder" / "nested.txt").write_text("nested\n", encoding="utf-8")

            with _local_ftp_server(root) as port:
                emitted = []
                login = LoginWidget()
                try:
                    login.session_changed.connect(lambda session: emitted.append(session))
                    login.profile_name.setText("local ftp")
                    login.host.setText("ftp://127.0.0.1")
                    login.port.setText(str(port))
                    login.username.setText("user")
                    login.password.setText("pass")

                    self.assertTrue(login.connect_clicked())
                    self.assertTrue(emitted)
                    session = emitted[-1]
                    self.assertTrue(session["connected"])
                    self.assertIsInstance(session["files"], FTPFilesBackend)
                    self.assertIsNone(session["ssh"])

                    self.assertTrue(self.widget.local_panel.set_dir(local_tmp))
                    with patch.object(
                        RemoteDirPanel,
                        "_run_plan_with_progress",
                        self._run_plan_synchronously,
                    ):
                        self.widget.set_session(session)
                        panel = self.widget.panel_scratch
                        files = session["files"]

                        self.assertTrue(
                            panel._apply_remote_download(
                                ["/arf/scratch/user/remote.txt"],
                                local_tmp,
                            )
                        )
                        self.assertEqual(
                            Path(local_tmp, "remote.txt").read_text(encoding="utf-8"),
                            "remote\n",
                        )

                        self.assertTrue(
                            panel._apply_remote_download(
                                ["/arf/scratch/user/folder"],
                                local_tmp,
                            )
                        )
                        self.assertEqual(
                            Path(local_tmp, "folder", "nested.txt").read_text(encoding="utf-8"),
                            "nested\n",
                        )

                        upload_path = Path(local_tmp, "upload.txt")
                        upload_path.write_text("upload\n", encoding="utf-8")
                        self.assertTrue(
                            panel._apply_local_upload(
                                [str(upload_path)],
                                "/arf/scratch/user/uploads",
                            )
                        )
                        self.assertEqual(
                            Path(scratch, "uploads", "upload.txt").read_text(encoding="utf-8"),
                            "upload\n",
                        )

                    files.mkdir("/arf/scratch/user/made")
                    files.write_text("/arf/scratch/user/made/text.txt", "hello\n")
                    self.assertEqual(
                        files.read_text("/arf/scratch/user/made/text.txt"),
                        "hello\n",
                    )
                    files.rename(
                        "/arf/scratch/user/made/text.txt",
                        "/arf/scratch/user/made/renamed.txt",
                    )
                    self.assertTrue(files.exists("/arf/scratch/user/made/renamed.txt"))
                    files.copy(
                        "/arf/scratch/user/made/renamed.txt",
                        "/arf/scratch/user/made/copied.txt",
                    )
                    self.assertEqual(
                        files.read_text("/arf/scratch/user/made/copied.txt"),
                        "hello\n",
                    )
                    files.move(
                        "/arf/scratch/user/made/copied.txt",
                        "/arf/scratch/user/made/moved.txt",
                    )
                    self.assertTrue(files.exists("/arf/scratch/user/made/moved.txt"))
                    files.remove("/arf/scratch/user/made/moved.txt")
                    self.assertFalse(files.exists("/arf/scratch/user/made/moved.txt"))
                    files.remove("/arf/scratch/user/made", recursive=True)
                    self.assertFalse(files.exists("/arf/scratch/user/made"))
                finally:
                    self.widget.set_session({"connected": False, "files": None})
                    if emitted:
                        files = emitted[-1].get("files")
                        if hasattr(files, "close"):
                            files.close()
                    login.deleteLater()

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

            with patch.object(panel, "_apply_local_upload", return_value=True) as upload:
                panel.views["all"].dropEvent(event)

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

            with patch.object(panel, "_apply_local_upload", return_value=True) as upload:
                panel.dropEvent(event)

            upload.assert_called_once()
            uploaded_paths, target_dir = upload.call_args.args
            self.assertEqual([Path(path) for path in uploaded_paths], [source])
            self.assertEqual(target_dir, "/remote/body-target")
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
        try:
            panel.enable_output_menu = True
            panel.open_in_slot.connect(lambda slot, path: seen.append((slot, path)))
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

            labels = [
                action.text
                for action in FakeMenu.instances[-1].actions
                if action is not None
            ]
            self.assertIn("Follow in Output 1", labels)
            self.assertIn("Follow in Output 2", labels)
            self.assertIn("Follow in New Window", labels)
            self.assertIn("Follow Output 1 in New Window", labels)
            self.assertIn("Follow Output 2 in New Window", labels)
            self.assertIn("Follow Output 1 in New Tab", labels)
            self.assertIn("Follow Output 2 in New Tab", labels)
            self.assertEqual(seen, [(1, "/remote/out.log")])
        finally:
            panel.deleteLater()

    def test_jobs_files_context_menu_can_follow_single_file_in_new_window(self) -> None:
        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

        class FakeMenu:
            choose_text = "Follow in New Window"

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
                    if action is not None and action.text == self.choose_text:
                        return action
                return None

        files = _Files()
        files.remote["/remote/out.log"] = b"out"
        panel = RemoteDirPanel()
        seen: list[str] = []
        try:
            panel.enable_output_menu = True
            panel.open_file_follow_new_window.connect(seen.append)
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

            self.assertEqual(seen, ["/remote/out.log"])
        finally:
            panel.deleteLater()

    def test_jobs_files_context_menu_can_follow_in_new_window(self) -> None:
        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

        class FakeMenu:
            choose_text = "Follow Output 1 in New Window"

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
                    if action is not None and action.text == self.choose_text:
                        return action
                return None

        files = _Files()
        files.remote["/remote/out.log"] = b"out"
        panel = RemoteDirPanel()
        seen: list[tuple[int, str]] = []
        try:
            panel.enable_output_menu = True
            panel.open_in_slot_new_window.connect(
                lambda slot, path: seen.append((slot, path))
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

            self.assertEqual(seen, [(0, "/remote/out.log")])
        finally:
            panel.deleteLater()

    def test_jobs_files_context_menu_can_assign_to_numbered_follow_target(self) -> None:
        class FakeAction:
            def __init__(self, text: str) -> None:
                self.text = text
                self.enabled = True

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = enabled

        class FakeMenu:
            instances: list["FakeMenu"] = []
            choose_text = "Window 1 - Output 2"

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
        seen: list[tuple[str, int, str]] = []
        try:
            panel.enable_output_menu = True
            panel.set_output_target_provider(lambda: [("window:1", "Window 1")])
            panel.open_in_existing_follower.connect(
                lambda target, slot, path: seen.append((target, slot, path))
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

            labels = [
                action.text
                for action in FakeMenu.instances[-1].actions
                if action is not None
            ]
            self.assertIn("Window 1 - Output 1", labels)
            self.assertIn("Window 1 - Output 2", labels)
            self.assertEqual(seen, [("window:1", 1, "/remote/out.log")])
        finally:
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
                "_apply_remote_download",
                return_value=True,
            ) as download:
                paste_event = QKeyEvent(
                    QEvent.Type.KeyPress,
                    Qt.Key.Key_V,
                    Qt.KeyboardModifier.ControlModifier,
                )
                QApplication.sendEvent(self.widget.local_panel.tree, paste_event)
            download.assert_called_once()
            self.assertEqual(
                download.call_args.args,
                (["/remote/out.txt"], self.widget.local_panel.current_dir),
            )
            self.assertIn("after_finished", download.call_args.kwargs)
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

    def test_remote_delete_and_ctrl_delete_remove_selected_files(self) -> None:
        files = MockFilesBackend()
        files.write_text("/arf/scratch/user/delete.txt", "delete")
        files.write_text("/arf/scratch/user/ctrl-delete.txt", "ctrl")
        panel = RemoteDirPanel()

        try:
            panel.set_session({"connected": True, "files": files})
            panel.set_dir("/arf/scratch/user")

            def select_name(name: str):
                view = panel.views["all"]
                view.clearSelection()
                for index in range(view.topLevelItemCount()):
                    item = view.topLevelItem(index)
                    if item.text(0) == name:
                        view.setCurrentItem(
                            item,
                            0,
                            QItemSelectionModel.SelectionFlag.ClearAndSelect,
                        )
                        return view
                self.fail(f"remote item not found: {name}")

            with patch(
                "truba_gui.ui.widgets.remote_dir_panel.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                view = select_name("delete.txt")
                self.assertEqual(
                    panel._selected_paths_from_view(view),
                    ["/arf/scratch/user/delete.txt"],
                )
                delete_event = QKeyEvent(
                    QEvent.Type.KeyPress,
                    Qt.Key.Key_Delete,
                    Qt.KeyboardModifier.NoModifier,
                )
                self.assertTrue(panel.eventFilter(view, delete_event))
                self.assertFalse(files.exists("/arf/scratch/user/delete.txt"))

                view = select_name("ctrl-delete.txt")
                ctrl_delete_event = QKeyEvent(
                    QEvent.Type.KeyPress,
                    Qt.Key.Key_Delete,
                    Qt.KeyboardModifier.ControlModifier,
                )
                self.assertTrue(panel.eventFilter(view, ctrl_delete_event))
                self.assertFalse(files.exists("/arf/scratch/user/ctrl-delete.txt"))
        finally:
            RemoteDirPanel._instances.pop(panel.panel_id, None)
            panel.deleteLater()

    def test_remote_page_home_end_shortcuts_move_selection(self) -> None:
        files = MockFilesBackend()
        for index in range(20):
            files.write_text(f"/arf/scratch/user/item-{index:02d}.txt", str(index))
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.set_dir("/arf/scratch/user")
        view = panel.views["all"]

        home_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Home,
            Qt.KeyboardModifier.NoModifier,
        )
        self.assertTrue(panel.eventFilter(view, home_event))
        self.assertEqual(view.currentItem(), view.topLevelItem(0))

        end_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_End,
            Qt.KeyboardModifier.NoModifier,
        )
        self.assertTrue(panel.eventFilter(view, end_event))
        self.assertEqual(view.currentItem(), view.topLevelItem(view.topLevelItemCount() - 1))

        page_up_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_PageUp,
            Qt.KeyboardModifier.NoModifier,
        )
        self.assertTrue(panel.eventFilter(view, page_up_event))
        after_page_up = view.currentItem()
        self.assertIsNotNone(after_page_up)
        self.assertNotEqual(after_page_up, view.topLevelItem(view.topLevelItemCount() - 1))

        page_down_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_PageDown,
            Qt.KeyboardModifier.NoModifier,
        )
        self.assertTrue(panel.eventFilter(view, page_down_event))
        self.assertNotEqual(view.currentItem(), after_page_up)

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
                "dirs.upload",
                "dirs.add_files_to_queue",
                "---",
                "files.open",
                "files.open_with",
                "dirs.open_in_new_tab",
                "dirs.edit",
                "---",
                "dirs.create_directory",
                "dirs.create_directory_enter",
                "dirs.refresh",
                "---",
                "dirs.delete",
                "dirs.rename",
            ],
        )
        for key in LOCAL_CONTEXT_MENU_LABELS:
            if key != "---":
                self.assertNotEqual(t(key), f"[{key}]")

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
                    if action is not None and action.text == t("dirs.open_in_new_tab"):
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
                "dirs.download",
                "dirs.save_as",
                "dirs.add_files_to_queue",
                "dirs.view_edit",
                "dirs.edit_in_new_window",
                "dirs.open_in_new_tab",
                "---",
                "dirs.create_directory",
                "dirs.create_directory_enter",
                "dirs.create_new_file",
                "dirs.refresh",
                "---",
                "dirs.delete",
                "dirs.rename",
                "dirs.copy_urls",
                "dirs.file_permissions",
            ],
        )

    def test_remote_context_download_uses_left_panel_directory(self) -> None:
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
                    if action is not None and action.text == t("dirs.download"):
                        return action
                return None

        with tempfile.TemporaryDirectory() as tmp:
            files = MockFilesBackend()
            panel = self.widget.panel_scratch
            panel.session = {"connected": True, "files": files}
            self.assertTrue(self.widget.local_panel.set_dir(tmp))
            panel.set_dir("/arf/scratch/user")
            view = panel.views["all"]
            target_item = None
            for index in range(view.topLevelItemCount()):
                item = view.topLevelItem(index)
                if item.text(0) == "example.txt":
                    target_item = item
                    item.setSelected(True)
                    break
            self.assertIsNotNone(target_item)

            with patch("truba_gui.ui.widgets.remote_dir_panel.QMenu", FakeMenu), patch(
                "truba_gui.ui.widgets.remote_dir_panel.QFileDialog.getExistingDirectory"
            ) as choose_dir, patch.object(
                panel, "_apply_remote_download", return_value=True
            ) as download:
                panel._on_context_menu(view, view.visualItemRect(target_item).center())

            choose_dir.assert_not_called()
            download.assert_called_once_with(["/arf/scratch/user/example.txt"], tmp)

    def test_remote_context_save_as_prompts_for_directory(self) -> None:
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
                    if action is not None and action.text == t("dirs.save_as"):
                        return action
                return None

        with tempfile.TemporaryDirectory() as tmp:
            save_dir = str(Path(tmp, "chosen"))
            files = MockFilesBackend()
            panel = self.widget.panel_scratch
            panel.session = {"connected": True, "files": files}
            panel.set_dir("/arf/scratch/user")
            view = panel.views["all"]
            target_item = None
            for index in range(view.topLevelItemCount()):
                item = view.topLevelItem(index)
                if item.text(0) == "example.txt":
                    target_item = item
                    item.setSelected(True)
                    break
            self.assertIsNotNone(target_item)

            with patch("truba_gui.ui.widgets.remote_dir_panel.QMenu", FakeMenu), patch(
                "truba_gui.ui.widgets.remote_dir_panel.QFileDialog.getExistingDirectory",
                return_value=save_dir,
            ) as choose_dir, patch.object(
                panel, "_apply_remote_download", return_value=True
            ) as download:
                panel._on_context_menu(view, view.visualItemRect(target_item).center())

            choose_dir.assert_called_once()
            download.assert_called_once_with(["/arf/scratch/user/example.txt"], save_dir)

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
                    if action is not None and action.text == t("dirs.open_in_new_tab"):
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

        self.assertEqual(panel.tabs.count(), 6)
        self.assertEqual(panel.directory_tabs.count(), 2)
        self.assertEqual(panel.current_dir, "/arf/scratch/user/project")
        opened = panel.views["all"]
        self.assertTrue(
            any(
                opened.topLevelItem(i).text(0) == "input.dat"
                for i in range(opened.topLevelItemCount())
            )
        )

    def test_remote_middle_click_opens_directory_in_new_tab(self) -> None:
        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.set_dir("/arf/scratch/user")
        view = panel.views["all"]
        target_item = None
        for index in range(view.topLevelItemCount()):
            item = view.topLevelItem(index)
            if item.text(0) == "project":
                target_item = item
                break
        self.assertIsNotNone(target_item)

        center = view.visualItemRect(target_item).center()
        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(center),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(view.viewport(), event)

        self.assertTrue(event.isAccepted())
        self.assertEqual(panel.directory_tabs.count(), 2)
        self.assertEqual(
            panel.directory_tabs.tabData(panel.directory_tabs.currentIndex()),
            "/arf/scratch/user/project",
        )

    def test_remote_directory_tabs_sit_above_filter_tabs(self) -> None:
        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.set_dir("/arf/scratch/user")

        self.assertTrue(panel.open_directory_in_new_tab("/arf/scratch/user/project"))
        self.assertEqual(panel.tabs.count(), 6)
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

    def test_remote_directory_tabs_are_closable_except_last_tab(self) -> None:
        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        panel.set_dir("/arf/scratch/user")

        self.assertTrue(panel.open_directory_in_new_tab("/arf/scratch/user/project"))
        self.assertTrue(panel.directory_tabs.tabsClosable())
        self.assertEqual(panel.directory_tabs.count(), 2)

        panel._close_directory_tab(panel.directory_tabs.currentIndex())
        self.assertEqual(panel.directory_tabs.count(), 1)
        self.assertEqual(panel.current_dir, "/arf/scratch/user")

        panel._close_directory_tab(0)
        self.assertEqual(panel.directory_tabs.count(), 1)

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

    def test_remote_f5_refresh_bypasses_directory_cache(self) -> None:
        files = _CountingFiles()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}

        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.monotonic",
            side_effect=[0.0, 10.0],
        ):
            panel.set_dir("/remote")
            event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_F5,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(panel.views["all"], event)

        self.assertTrue(event.isAccepted())
        self.assertEqual(files.calls, ["/remote", "/remote"])

    def test_remote_directory_cache_expires_after_ttl(self) -> None:
        files = _CountingFiles()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}

        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.monotonic",
            side_effect=[0.0, 601.0],
        ):
            panel.set_dir("/remote")
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

    def test_remote_mutation_auto_refresh_can_be_disabled(self) -> None:
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

            with (
                patch.object(target_panel, "_run_plan_with_progress", side_effect=fake_run),
                patch(
                    "truba_gui.ui.widgets.remote_dir_panel.get_transfer_auto_refresh_enabled",
                    return_value=False,
                ),
            ):
                self.assertTrue(
                    target_panel._apply_copy_move_with_conflicts(
                        "move",
                        ["/remote/root.txt"],
                        "/remote/child",
                    )
                )
                self.assertEqual(files.calls, [])
                self.assertEqual(len(callbacks), 1)
                callbacks[0]()

            self.assertEqual(files.calls, [])
        finally:
            source_panel.deleteLater()

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

    def test_download_transfer_items_include_remote_file_size(self) -> None:
        files = _Files()
        files.remote["/remote/sized.bin"] = b"x" * 4096
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        with tempfile.TemporaryDirectory() as tmp:
            item = panel._transfer_item_from_plan(
                _PlannedOp("download", "/remote/sized.bin", str(Path(tmp, "sized.bin")))
            )
        self.assertEqual(item.size, 4096)

    def test_folder_download_queues_selected_folders_without_ui_thread_walk(self) -> None:
        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                panel,
                "_remote_walk",
                side_effect=AssertionError("folder walking must stay out of the UI path"),
            ), patch.object(panel, "_run_plan_with_progress", return_value=True) as run_plan:
                self.assertTrue(
                    panel._apply_remote_download(
                        ["/arf/scratch/user/project", "/arf/scratch/user/project"],
                        tmp,
                    )
                )

        plan = run_plan.call_args.args[0]
        self.assertEqual(
            [(item.op, item.src) for item in plan],
            [("download_tree", "/arf/scratch/user/project")],
        )

    def test_folder_download_overwrite_merges_without_deleting_local_extras(self) -> None:
        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp, "project")
            target.mkdir()
            (target / "input.dat").write_text("old\n", encoding="utf-8")
            (target / "keep.txt").write_text("keep\n", encoding="utf-8")
            with patch.object(
                RemoteDirPanel,
                "_run_plan_with_progress",
                self._run_plan_synchronously,
            ), patch.object(panel, "_resolve_conflict", return_value="overwrite"):
                self.assertTrue(
                    panel._apply_remote_download(
                        ["/arf/scratch/user/project"],
                        tmp,
                    )
                )

            self.assertEqual((target / "input.dat").read_text(encoding="utf-8"), "1 2 3\n")
            self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "keep\n")

    def test_folder_download_runs_synchronously_even_when_parallel_limit_is_higher(self) -> None:
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": MockFilesBackend()}
        _FakeTransferDialog.captured_parallel_limits.clear()
        _FakeTransferDialog.captured_max_parallel_limits.clear()
        with (
            patch(
                "truba_gui.ui.widgets.remote_dir_panel.get_transfer_parallelism",
                return_value=4,
            ),
            patch(
                "truba_gui.ui.widgets.remote_dir_panel.TransferDialog",
                _FakeTransferDialog,
            ),
        ):
            self.assertTrue(
                panel._run_plan_with_progress(
                    [
                        _PlannedOp("download_tree", "/remote/a", r"D:\target\a"),
                        _PlannedOp("download_tree", "/remote/b", r"D:\target\b"),
                    ],
                    "İndiriliyor...",
                )
            )

        self.assertEqual(_FakeTransferDialog.captured_parallel_limits, [1])
        self.assertEqual(_FakeTransferDialog.captured_max_parallel_limits, [1])

    def test_file_download_uses_configured_parallel_limit(self) -> None:
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": MockFilesBackend()}
        _FakeTransferDialog.captured_parallel_limits.clear()
        _FakeTransferDialog.captured_max_parallel_limits.clear()
        with (
            patch(
                "truba_gui.ui.widgets.remote_dir_panel.get_transfer_parallelism",
                return_value=4,
            ),
            patch(
                "truba_gui.ui.widgets.remote_dir_panel.TransferDialog",
                _FakeTransferDialog,
            ),
        ):
            self.assertTrue(
                panel._run_plan_with_progress(
                    [
                        _PlannedOp("download", "/remote/a.txt", r"D:\target\a.txt"),
                        _PlannedOp("download", "/remote/b.txt", r"D:\target\b.txt"),
                    ],
                    "İndiriliyor...",
                )
            )

        self.assertEqual(_FakeTransferDialog.captured_parallel_limits, [4])
        self.assertEqual(_FakeTransferDialog.captured_max_parallel_limits, [10])

    def test_single_connection_uploads_are_forced_to_one_at_a_time(self) -> None:
        files = _Files()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        _FakeTransferDialog.captured_parallel_limits.clear()
        _FakeTransferDialog.captured_max_parallel_limits.clear()
        source_a = str(Path(__file__).resolve())
        source_b = str(Path(__file__).resolve().parent / "test_ftp_widget.py")
        with (
            patch(
                "truba_gui.ui.widgets.remote_dir_panel.get_transfer_parallelism",
                return_value=5,
            ),
            patch(
                "truba_gui.ui.widgets.remote_dir_panel.TransferDialog",
                _FakeTransferDialog,
            ),
        ):
            self.assertTrue(
                panel._run_plan_with_progress(
                    [
                        _PlannedOp("upload", source_a, "/remote/a.py"),
                        _PlannedOp("upload", source_b, "/remote/b.py"),
                    ],
                    "Yükleniyor...",
                )
            )

        self.assertEqual(_FakeTransferDialog.captured_parallel_limits, [1])
        self.assertEqual(_FakeTransferDialog.captured_max_parallel_limits, [1])

    def test_transfer_items_use_dedicated_backend_when_available(self) -> None:
        class CloneableFiles:
            supports_parallel_transfers = False

            def __init__(self) -> None:
                self.main_uploads: list[tuple[str, str]] = []
                self.transfer_uploads: list[tuple[str, str]] = []
                self.closed = False

            def open_transfer_backend(self):
                parent = self

                class TransferFiles:
                    def upload(self, local_path: str, remote_path: str, progress_cb=None) -> None:
                        parent.transfer_uploads.append((local_path, remote_path))
                        if progress_cb is not None:
                            progress_cb(Path(local_path).stat().st_size, Path(local_path).stat().st_size)

                    def close(self) -> None:
                        parent.closed = True

                return TransferFiles()

            def upload(self, local_path: str, remote_path: str, progress_cb=None) -> None:
                self.main_uploads.append((local_path, remote_path))

        files = CloneableFiles()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "payload.bin")
            source.write_bytes(b"\x00payload")
            panel._execute_transfer_item(
                TransferItem("upload", str(source), "/remote/payload.bin")
            )

        self.assertEqual(files.main_uploads, [])
        self.assertEqual(len(files.transfer_uploads), 1)
        self.assertTrue(files.closed)

    def test_folder_download_forwards_nested_file_progress(self) -> None:
        files = MockFilesBackend()
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        progress: list[tuple[int, int]] = []
        with tempfile.TemporaryDirectory() as tmp:
            panel._download_remote_tree(
                "/arf/scratch/user/project",
                str(Path(tmp, "project")),
                progress_cb=lambda done, total: progress.append((done, total)),
            )

        self.assertTrue(progress)
        self.assertEqual(progress[0][0], 0)
        self.assertEqual(progress[-1][0], progress[-1][1])
        self.assertGreater(progress[-1][1], 0)

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

    def test_folder_upload_overwrite_merges_without_deleting_remote_extras(self) -> None:
        files = MockFilesBackend()
        files.write_text("/arf/scratch/user/project/keep.txt", "keep\n")
        panel = self.widget.panel_scratch
        panel.session = {"connected": True, "files": files}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "project")
            source.mkdir()
            (source / "input.dat").write_text("new\n", encoding="utf-8")
            (source / "added.txt").write_text("added\n", encoding="utf-8")
            with patch.object(
                RemoteDirPanel,
                "_run_plan_with_progress",
                self._run_plan_synchronously,
            ), patch.object(panel, "_resolve_conflict", return_value="overwrite"):
                self.assertTrue(
                    panel._apply_local_upload(
                        [str(source)],
                        "/arf/scratch/user",
                    )
                )

        self.assertEqual(files.read_text("/arf/scratch/user/project/input.dat"), "new\n")
        self.assertEqual(files.read_text("/arf/scratch/user/project/added.txt"), "added\n")
        self.assertEqual(files.read_text("/arf/scratch/user/project/keep.txt"), "keep\n")

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

            files.mkdir("/arf/scratch/user/second")
            files.write_text("/arf/scratch/user/second/notes.txt", "second\n")
            multi_target = Path(tmp, "multi")
            multi_target.mkdir()
            self.assertTrue(self.widget.local_panel.set_dir(str(multi_target)))
            mime = QMimeData()
            mime.setData(
                MIME_REMOTE_PATHS,
                json.dumps(
                    {
                        "paths": [
                            "/arf/scratch/user/project",
                            "/arf/scratch/user/second",
                        ],
                        "src_panel_id": self.widget.panel_scratch.panel_id,
                    }
                ).encode("utf-8"),
            )
            drop_event = _FakeDropEvent(mime)
            with patch.object(
                RemoteDirPanel,
                "_run_plan_with_progress",
                self._run_plan_synchronously,
            ):
                self.widget.local_panel.tree.dropEvent(drop_event)

            self.assertTrue(drop_event.accepted)
            self.assertFalse(drop_event.ignored)
            self.assertEqual(
                Path(multi_target, "project", "input.dat").read_text(),
                "1 2 3\n",
            )
            self.assertEqual(
                Path(multi_target, "second", "notes.txt").read_text(),
                "second\n",
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
