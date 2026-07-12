from __future__ import annotations

import datetime
import json
import os
import re
import shutil
from time import monotonic
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QEvent, QPoint, Qt, Signal, QObject, QThread, Slot
from PySide6.QtGui import QDrag, QIcon, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QListWidget,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QTabBar,
    QToolButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from truba_gui.core.i18n import t
from truba_gui.core.ui_errors import show_exception
from truba_gui.config.storage import (
    get_transfer_auto_refresh_enabled,
    get_transfer_parallelism,
)
from truba_gui.services.file_clipboard import get_file_clipboard
from truba_gui.services.files_base import RemoteEntry
from truba_gui.services.transfer_mode import (
    BINARY,
    download_with_mode,
    normalize_transfer_mode,
    upload_with_mode,
)
from truba_gui.ui.dialogs.transfer_conflict_dialog import (
    TransferConflictDecision,
    TransferConflictDialog,
    TransferConflictInfo,
)
from truba_gui.ui.dialogs.transfer_dialog import TransferDialog, TransferItem


def _fmt_size(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(n)
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    return f"{v:.1f} {units[i]}" if i else f"{int(v)} {units[i]}"


def _fmt_mtime(ts: int) -> str:
    if not ts:
        return ""
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%d-%m-%y %H:%M")
    except Exception:
        return ""


def _file_type(name: str, is_dir: bool) -> str:
    if is_dir:
        return t("dirs.type_folder")
    lower = name.lower()
    if lower.endswith(".iso"):
        return t("dirs.type_disc_image")
    if lower.endswith((".zip", ".rar", ".7z")):
        return t("dirs.type_zip_archive")
    if lower.endswith((".tgz", ".tar.gz", ".tar")):
        return t("dirs.type_tar_archive")
    if "." in name:
        return t("dirs.type_extension_file").format(ext=name.split(".")[-1].upper())
    return t("dirs.type_file")


def _file_type_sort_value(name: str, is_dir: bool) -> str:
    if is_dir:
        return "folder"
    lower = name.lower()
    if lower.endswith(".iso"):
        return "iso"
    if lower.endswith((".zip", ".rar", ".7z")):
        return lower.rsplit(".", 1)[-1]
    if lower.endswith(".tar.gz"):
        return "tar.gz"
    if lower.endswith((".tgz", ".tar")):
        return lower.rsplit(".", 1)[-1]
    if "." in name:
        return name.rsplit(".", 1)[-1]
    return "file"


def _category(entry: RemoteEntry) -> str:
    if entry.is_dir:
        return "folders"
    lower = entry.name.lower()
    if lower.endswith(".iso"):
        return "iso"
    if lower.endswith((".zip", ".rar", ".7z", ".tgz", ".tar.gz", ".tar")):
        return "archives"
    if lower.endswith((".slurm", ".sbatch")):
        return "slurm"
    return "other"


MIME_REMOTE_PATHS = "application/x-truba-remote-paths"
DIRECTORY_CACHE_TTL_SECONDS = 600.0

REMOTE_CONTEXT_MENU_KEYS = [
    "dirs.download",
    "dirs.save_as",
    "dirs.add_files_to_queue",
    "dirs.view_edit",
    "dirs.edit_in_new_window",
    "dirs.open_in_new_tab",
    "dirs.create_directory",
    "dirs.create_directory_enter",
    "dirs.create_new_file",
    "dirs.refresh",
    "dirs.delete",
    "dirs.rename",
    "dirs.copy_urls",
    "dirs.file_permissions",
]
REMOTE_CONTEXT_MENU_LABELS = [
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
]

_SORT_NAME_ROLE = Qt.ItemDataRole.UserRole + 10
_SORT_SIZE_ROLE = Qt.ItemDataRole.UserRole + 11
_SORT_TYPE_ROLE = Qt.ItemDataRole.UserRole + 12
_SORT_MTIME_ROLE = Qt.ItemDataRole.UserRole + 13


def _natural_sort_key(value: str) -> tuple:
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", value or "")
        if part
    )


@dataclass
class _DragPayload:
    paths: List[str]
    src_panel_id: str


def _encode_payload(payload: _DragPayload) -> bytes:
    return json.dumps({"paths": payload.paths, "src_panel_id": payload.src_panel_id}).encode("utf-8")


def _decode_payload(raw: bytes) -> Optional[_DragPayload]:
    try:
        obj = json.loads(raw.decode("utf-8"))
        paths = [str(p) for p in obj.get("paths", []) if p]
        src_panel_id = str(obj.get("src_panel_id", ""))
        if not paths or not src_panel_id:
            return None
        return _DragPayload(paths=paths, src_panel_id=src_panel_id)
    except Exception:
        return None


@dataclass
class _PlannedOp:
    op: str  # "copy" | "move" | "delete"
    src: str
    dst: str
    recursive: bool = False


@dataclass
class _UndoRecord:
    kind: str  # currently only "move"
    moves: List[Tuple[str, str]]  # (src, dst) executed


class _FileOpWorker(QObject):
    progress = Signal(int, str)  # step, label
    finished = Signal(bool, str)  # cancelled, message

    def __init__(self, files_backend, plan: List[_PlannedOp]):
        super().__init__()
        self._files = files_backend
        self._plan = plan
        self._cancel = False

    @Slot()
    def cancel(self) -> None:
        self._cancel = True

    @Slot()
    def run(self) -> None:
        total = len(self._plan)
        for i, op in enumerate(self._plan, start=1):
            if self._cancel:
                self.finished.emit(True, "İptal edildi.")
                return
            label = f"{i}/{total}: {os.path.basename((op.dst or op.src).rstrip('/'))}"
            self.progress.emit(i, label)
            try:
                if op.op == "delete":
                    # delete remote path (dst)
                    self._files.remove(op.dst, recursive=op.recursive)
                elif op.op == "copy":
                    self._files.copy(op.src, op.dst, recursive=op.recursive)
                elif op.op == "move":
                    self._files.move(op.src, op.dst)
                elif op.op == "upload":
                    # upload local (src) -> remote (dst)
                    self._files.upload(op.src, op.dst)
                elif op.op == "download":
                    # download remote (src) -> local (dst)
                    self._files.download_toggle(op.src, op.dst) if hasattr(self._files, 'download_toggle') else self._files.download(op.src, op.dst)
                elif op.op == "mkdir_remote":
                    self._files.mkdir(op.dst)
                elif op.op == "mkdir_local":
                    os.makedirs(op.dst, exist_ok=True)
                elif op.op == "delete_local":
                    # delete local path (dst)
                    if os.path.isdir(op.dst):
                        shutil.rmtree(op.dst, ignore_errors=True)
                    else:
                        try:
                            os.remove(op.dst)
                        except FileNotFoundError:
                            pass
                else:
                    raise RuntimeError(f"Unknown op: {op.op}")
            except Exception as e:
                self.finished.emit(False, f"{label}\n{e}")
                return
        self.finished.emit(False, "")


class _RemoteTree(QTreeWidget):
    """A QTreeWidget that supports drag/drop between RemoteDirPanel instances."""

    def __init__(self, panel: "RemoteDirPanel"):
        super().__init__()
        self._panel = panel
        self._sort_column: Optional[int] = None
        self._sort_order = Qt.SortOrder.AscendingOrder

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.header().setSectionsClickable(True)
        self.header().setSortIndicatorShown(False)
        self.header().sectionClicked.connect(self._on_header_clicked)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.MiddleButton:
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                path = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
                is_dir = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
                is_parent = bool(item.data(0, Qt.ItemDataRole.UserRole + 2))
                if path and is_dir and not is_parent:
                    if self._panel.open_directory_in_new_tab(path):
                        event.accept()
                        return
        super().mouseReleaseEvent(event)

    def move_current_for_key(self, key: Qt.Key) -> None:
        count = self.topLevelItemCount()
        if count <= 0:
            return
        current = self.currentItem()
        current_index = self.indexOfTopLevelItem(current) if current is not None else -1
        if current_index < 0:
            current_index = 0
        if key == Qt.Key.Key_Home:
            target_index = 0
        elif key == Qt.Key.Key_End:
            target_index = count - 1
        else:
            row_height = self.sizeHintForRow(max(0, current_index))
            if row_height <= 0:
                row_height = max(1, self.fontMetrics().height())
            page_rows = max(1, self.viewport().height() // row_height - 1)
            delta = -page_rows if key == Qt.Key.Key_PageUp else page_rows
            target_index = max(0, min(count - 1, current_index + delta))
        target = self.topLevelItem(target_index)
        if target is None:
            return
        self.clearSelection()
        target.setSelected(True)
        self.setCurrentItem(target)
        self.scrollToItem(target)

    def _on_header_clicked(self, column: int) -> None:
        if column < 0 or column >= 4:
            return
        if self._sort_column == column:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_column = column
            self._sort_order = Qt.SortOrder.AscendingOrder
        self.header().setSortIndicatorShown(True)
        self.header().setSortIndicator(column, self._sort_order)
        self.apply_sort()

    def apply_sort(self) -> None:
        if self._sort_column is None or self.topLevelItemCount() < 2:
            return

        items = [self.takeTopLevelItem(0) for _ in range(self.topLevelItemCount())]
        parent_items = [item for item in items if bool(item.data(0, Qt.ItemDataRole.UserRole + 2))]
        folders = [
            item
            for item in items
            if item not in parent_items and bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
        ]
        files = [
            item
            for item in items
            if item not in parent_items and not bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
        ]
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder

        def key(item: QTreeWidgetItem):
            role = (
                _SORT_NAME_ROLE,
                _SORT_SIZE_ROLE,
                _SORT_TYPE_ROLE,
                _SORT_MTIME_ROLE,
            )[self._sort_column]
            value = item.data(0, role)
            if self._sort_column in (0, 2):
                return _natural_sort_key(str(value or ""))
            return int(value or 0)

        self.addTopLevelItems(
            parent_items
            + sorted(folders, key=key, reverse=reverse)
            + sorted(files, key=key, reverse=reverse)
        )

    def startDrag(self, supportedActions: Qt.DropActions) -> None:  # type: ignore[override]
        paths = self._panel._selected_paths_from_view(self)
        if not paths:
            return
        mime = QMimeData()
        mime.setData(MIME_REMOTE_PATHS, _encode_payload(_DragPayload(paths=paths, src_panel_id=self._panel.panel_id)))

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):  # type: ignore[override]
        md = event.mimeData()
        if md.hasFormat(MIME_REMOTE_PATHS):
            event.acceptProposedAction()
            return
        if self._panel._local_paths_from_mime(md):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):  # type: ignore[override]
        md = event.mimeData()
        if md.hasFormat(MIME_REMOTE_PATHS):
            event.acceptProposedAction()
            return
        if self._panel._local_paths_from_mime(md):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):  # type: ignore[override]
        md = event.mimeData()
        # 1) Remote->Remote drag payload
        if md.hasFormat(MIME_REMOTE_PATHS):
            raw = bytes(md.data(MIME_REMOTE_PATHS))
            payload = _decode_payload(raw)
            if not payload:
                return

            # Determine destination directory: drop on folder => into that folder, else current dir.
            dest_dir = self._panel.current_dir or "/"
            item = self.itemAt(event.position().toPoint())  # Qt6
            if item is not None:
                clicked_path = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
                clicked_is_dir = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
                if clicked_path and clicked_is_dir:
                    dest_dir = clicked_path.rstrip("/")

            # Decide copy vs move: Ctrl => copy, else move.
            is_copy = bool(event.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)

            ok = self._panel._apply_drag_drop(payload.paths, dest_dir, is_copy=is_copy, src_panel_id=payload.src_panel_id)
            if ok:
                event.acceptProposedAction()
            else:
                event.ignore()
            return

        # 2) Local->Remote OS drag (upload)
        local_paths = self._panel._local_paths_from_mime(md)
        if local_paths:
            dest_dir = self._panel._drop_dest_dir_for_item(
                self.itemAt(event.position().toPoint())
            )
            ok = self._panel._apply_local_upload(local_paths, dest_dir)
            if ok:
                event.acceptProposedAction()
            else:
                event.ignore()
            return

        return super().dropEvent(event)


class RemoteDirPanel(QWidget):
    open_file = Signal(str)  # remote path (file double click)
    open_file_in_new_window = Signal(str)
    file_activated = Signal(str)
    open_in_slot = Signal(int, str)  # slot_index(0/1), remote path
    open_in_slot_new_window = Signal(int, str)
    open_in_slot_new_tab = Signal(int, str)
    open_in_existing_follower = Signal(str, int, str)
    open_file_follow_new_window = Signal(str)
    submit_requested = Signal(str)  # remote Slurm script path
    set_default_requested = Signal()

    # registry to refresh source/target panels on move
    _instances: Dict[str, "RemoteDirPanel"] = {}

    # single-level undo (last operation)
    _last_undo: Optional[_UndoRecord] = None

    def __init__(self, title: str = ""):
        super().__init__()
        self.session = None
        self.enable_output_menu = False  # JobsOutputsWidget can turn this on
        self.default_location_label = ""
        self.current_dir = ""
        self._category_dir = ""
        self.title = title
        self._transfer_mode_provider: Optional[Callable[[str], str]] = None
        self._default_download_dir_provider: Optional[Callable[[], str]] = None
        self._download_finished_callback: Optional[Callable[[str], None]] = None
        self._output_target_provider: Optional[
            Callable[[], List[Tuple[str, str]]]
        ] = None
        self._transfer_activity_callback: Optional[
            Callable[[str, List[TransferItem], str], None]
        ] = None
        self._transfer_dialogs: List[TransferDialog] = []
        self._active_transfer_keys: set[tuple[str, str, str]] = set()
        self._show_transfer_dialog = True
        self._directory_cache: Dict[str, Tuple[float, List[RemoteEntry]]] = {}

        self.panel_id = str(id(self))
        RemoteDirPanel._instances[self.panel_id] = self
        self.setAcceptDrops(True)

        self.lbl = QLabel(title)
        self.path = QLineEdit()
        self.path.returnPressed.connect(self._open_path_field)

        self.search_label = QLabel(t("dirs.search_label"))
        self.search_in = QLineEdit()
        self.search_in.setPlaceholderText(t("dirs.search_placeholder"))
        self.search_in.textChanged.connect(lambda _text: self.refresh())
        self.btn_search_clear = QPushButton(t("dirs.search_clear"))
        self.btn_search_clear.clicked.connect(self.search_in.clear)

        self.btn_upload = QPushButton(t("dirs.upload"))
        self.btn_upload.clicked.connect(self.upload_files)

        self.btn_new_folder = QPushButton(
            t("dirs.new_folder")
        )
        self.btn_new_folder.clicked.connect(self.create_new_folder)

        self.btn_new_file = QPushButton(
            t("dirs.new_file")
        )
        self.btn_new_file.clicked.connect(self.create_new_file)

        self.btn_template_upload = QPushButton(
            t("dirs.template_upload")
        )
        self.btn_template_upload.clicked.connect(self.show_template_upload_menu)

        self.btn_download = QPushButton(
            t("dirs.download_selected")
        )
        self.btn_download.clicked.connect(self.download_selected)

        self.btn_delete = QPushButton(t("dirs.delete"))
        self.btn_delete.clicked.connect(self.delete_selected)

        self.btn_undo = QPushButton(t("dirs.undo"))
        self.btn_undo.clicked.connect(self.undo_last)

        self.btn_parent = QToolButton()
        self.btn_parent.setAutoRaise(False)
        self.btn_parent.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_parent.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.btn_parent.clicked.connect(self.go_parent)
        self.btn_parent.setEnabled(False)

        self.btn_refresh = QPushButton(t("dirs.refresh"))
        self.btn_refresh.clicked.connect(lambda: self.refresh(force=True))

        self.refresh_shortcut = QShortcut(QKeySequence.Refresh, self)
        self.refresh_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.refresh_shortcut.activated.connect(lambda: self.refresh(force=True))

        top = QHBoxLayout()
        top.addWidget(self.lbl)
        top.addStretch(1)
        top.addWidget(self.btn_new_folder)
        top.addWidget(self.btn_new_file)
        top.addWidget(self.btn_upload)
        top.addWidget(self.btn_template_upload)
        top.addWidget(self.btn_download)
        top.addWidget(self.btn_delete)
        top.addWidget(self.btn_undo)
        top.addWidget(self.btn_parent)
        top.addWidget(self.btn_refresh)

        self.directory_tabs = QTabBar()
        self.directory_tabs.setExpanding(False)
        self.directory_tabs.setMovable(True)
        self.directory_tabs.setTabsClosable(True)
        self.directory_tabs.currentChanged.connect(self._on_directory_tab_changed)
        self.directory_tabs.tabCloseRequested.connect(self._close_directory_tab)

        self.tabs = QTabWidget()
        self.views: Dict[str, _RemoteTree] = {
            "all": self._make_view(),
            "folders": self._make_view(),
            "iso": self._make_view(),
            "archives": self._make_view(),
            "slurm": self._make_view(),
            "other": self._make_view(),
        }
        self.tabs.addTab(self.views["all"], t("dirs.tab_all"))
        self.tabs.addTab(self.views["folders"], t("dirs.tab_folders"))
        self.tabs.addTab(self.views["iso"], t("dirs.tab_iso"))
        self.tabs.addTab(
            self.views["archives"], t("dirs.tab_archives")
        )
        self.tabs.addTab(self.views["slurm"], t("dirs.tab_slurm"))
        self.tabs.addTab(self.views["other"], t("dirs.tab_other"))
        self.tabs.currentChanged.connect(self._on_tab_changed)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        self.path_label = QLabel(t("dirs.path"))
        lay.addWidget(self.path_label)
        lay.addWidget(self.path)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search_label)
        search_row.addWidget(self.search_in, 1)
        search_row.addWidget(self.btn_search_clear)
        lay.addLayout(search_row)
        lay.addWidget(self.directory_tabs)
        lay.addWidget(self.tabs)

        # Transfer queue (batch view)
        self.queue_group = QGroupBox(t("dirs.queue_title"))
        qlay = QVBoxLayout(self.queue_group)
        self.queue_current = QLabel("-")
        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(80)
        self.queue_current_label = QLabel(t("dirs.queue_current"))
        qlay.addWidget(self.queue_current_label)

        # ---- active batch tracking (for graceful shutdown / diagnostics)
        self._active_thread: Optional[QThread] = None
        self._active_worker: Optional[_FileOpWorker] = None
        self._active_plan: List[_PlannedOp] = []
        self._active_step: int = 0
        self._active_title: str = ""
        qlay.addWidget(self.queue_current)
        self.queue_next_label = QLabel(t("dirs.queue_pending"))
        qlay.addWidget(self.queue_next_label)
        qlay.addWidget(self.queue_list)
        self.queue_group.setVisible(False)
        lay.addWidget(self.queue_group)

        self._update_undo_enabled()
        self._update_navigation_controls()

    def retranslate_ui(self) -> None:
        self.btn_new_folder.setText(t("dirs.new_folder"))
        self.btn_new_file.setText(t("dirs.new_file"))
        self.btn_upload.setText(t("dirs.upload"))
        self.btn_template_upload.setText(t("dirs.template_upload"))
        self.btn_download.setText(t("dirs.download_selected"))
        self.btn_delete.setText(t("dirs.delete"))
        self.btn_undo.setText(t("dirs.undo"))
        self.btn_refresh.setText(t("dirs.refresh"))
        self.path_label.setText(t("dirs.path"))
        self.search_label.setText(t("dirs.search_label"))
        self.search_in.setPlaceholderText(t("dirs.search_placeholder"))
        self.btn_search_clear.setText(t("dirs.search_clear"))
        self.queue_group.setTitle(t("dirs.queue_title"))
        self.queue_current_label.setText(t("dirs.queue_current"))
        self.queue_next_label.setText(t("dirs.queue_pending"))
        tab_keys = ("all", "folders", "iso", "archives", "slurm", "other")
        for index, key in enumerate(tab_keys):
            self.tabs.setTabText(index, t(f"dirs.tab_{key}"))
        for index in range(self.directory_tabs.count()):
            directory = str(self.directory_tabs.tabData(index) or "")
            if directory:
                self.directory_tabs.setTabText(index, self._directory_tab_label(directory))
        headers = [
            t("dirs.col_name"),
            t("dirs.col_size"),
            t("dirs.col_type"),
            t("dirs.col_mtime"),
        ]
        for view in self.views.values():
            view.setHeaderLabels(headers)

    def _make_view(self) -> _RemoteTree:
        w = _RemoteTree(panel=self)
        w.setColumnCount(4)
        w.setHeaderLabels(
            [
                t("dirs.col_name"),
                t("dirs.col_size"),
                t("dirs.col_type"),
                t("dirs.col_mtime"),
            ]
        )
        w.setRootIsDecorated(False)
        w.setAlternatingRowColors(True)
        w.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        w.itemDoubleClicked.connect(self._handle_item_double_clicked)
        w.header().setStretchLastSection(True)
        w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        w.customContextMenuRequested.connect(lambda pos, view=w: self._on_context_menu(view, pos))
        w.installEventFilter(self)
        return w

    @staticmethod
    def _directory_tab_label(remote_dir: str) -> str:
        cleaned = (remote_dir or "/").rstrip("/") or "/"
        return cleaned.rsplit("/", 1)[-1] or cleaned

    def _on_tab_changed(self, index: int) -> None:
        self._update_navigation_controls()

    def _on_directory_tab_changed(self, index: int) -> None:
        if index < 0:
            return
        remote_dir = str(self.directory_tabs.tabData(index) or "")
        if not remote_dir:
            return
        self.current_dir = remote_dir
        self._category_dir = remote_dir
        self.path.setText(remote_dir)
        self.refresh()

    def _close_directory_tab(self, index: int) -> None:
        if self.directory_tabs.count() <= 1 or index < 0:
            return
        was_current = index == self.directory_tabs.currentIndex()
        self.directory_tabs.removeTab(index)
        if was_current:
            self._on_directory_tab_changed(self.directory_tabs.currentIndex())

    def open_directory_in_new_tab(self, remote_dir: str) -> bool:
        if not self.session or not self.session.get("files"):
            return False
        target = (remote_dir or "").rstrip("/") or "/"
        if not target:
            return False
        index = self._find_directory_tab(target)
        if index < 0:
            index = self.directory_tabs.addTab(self._directory_tab_label(target))
            self.directory_tabs.setTabData(index, target)
        changed = self.directory_tabs.currentIndex() != index
        self.directory_tabs.setCurrentIndex(index)
        self.current_dir = target
        self._category_dir = target
        self.path.setText(target)
        if not changed:
            self.refresh()
        self._update_navigation_controls()
        return True

    def _find_directory_tab(self, remote_dir: str) -> int:
        target = (remote_dir or "").rstrip("/") or "/"
        for index in range(self.directory_tabs.count()):
            if self.directory_tabs.tabData(index) == target:
                return index
        return -1

    def _open_path_field(self) -> None:
        self.set_dir(self.path.text())

    def eventFilter(self, watched, event):
        # Delete / Paste / Undo key support on directory views
        if isinstance(watched, QTreeWidget) and event.type() == QEvent.Type.KeyPress:
            e: QKeyEvent = event  # type: ignore
            if e.key() == Qt.Key.Key_Backspace and not e.modifiers():
                self.go_parent()
                return True
            if e.key() == Qt.Key.Key_Delete and e.modifiers() in (
                Qt.KeyboardModifier.NoModifier,
                Qt.KeyboardModifier.ControlModifier,
            ):
                self._delete_paths(self._selected_paths_from_view(watched))
                return True
            if e.key() in (
                Qt.Key.Key_PageUp,
                Qt.Key.Key_PageDown,
                Qt.Key.Key_Home,
                Qt.Key.Key_End,
            ) and not e.modifiers():
                if isinstance(watched, _RemoteTree):
                    watched.move_current_for_key(e.key())
                return True
            if e.key() == Qt.Key.Key_F5 and not e.modifiers():
                self.refresh(force=True)
                return True
            if e.key() == Qt.Key.Key_F2 and not e.modifiers():
                if self.rename_selected(watched):
                    return True
            if (e.modifiers() & Qt.KeyboardModifier.ControlModifier) and e.key() == Qt.Key.Key_C:
                paths = self._selected_paths_from_view(watched)
                if paths:
                    get_file_clipboard().set("copy", paths)
                    return True
            if (e.modifiers() & Qt.KeyboardModifier.ControlModifier) and e.key() == Qt.Key.Key_X:
                paths = self._selected_paths_from_view(watched)
                if paths:
                    get_file_clipboard().set("move", paths)
                    return True
            if (e.modifiers() & Qt.KeyboardModifier.ControlModifier) and e.key() == Qt.Key.Key_V:
                if self._paste_system_clipboard_into(self.current_dir or "/"):
                    return True
                self._paste_remote_clipboard_into(self.current_dir or "/")
                return True
            if (e.modifiers() & Qt.KeyboardModifier.ControlModifier) and e.key() == Qt.Key.Key_Z:
                self.undo_last()
                return True
        return super().eventFilter(watched, event)

    def set_session(self, session):
        self.session = session
        self._directory_cache.clear()
        self._update_navigation_controls()

    def set_transfer_mode_provider(
        self, provider: Optional[Callable[[str], str]]
    ) -> None:
        self._transfer_mode_provider = provider

    def set_default_download_dir_provider(
        self, provider: Optional[Callable[[], str]],
    ) -> None:
        self._default_download_dir_provider = provider

    def set_download_finished_callback(
        self,
        callback: Optional[Callable[[str], None]],
    ) -> None:
        self._download_finished_callback = callback

    def set_output_target_provider(
        self,
        provider: Optional[Callable[[], List[Tuple[str, str]]]],
    ) -> None:
        self._output_target_provider = provider

    def set_transfer_activity_callback(
        self,
        callback: Optional[Callable[[str, List[TransferItem], str], None]],
    ) -> None:
        self._transfer_activity_callback = callback

    def set_transfer_dialog_visible(self, visible: bool) -> None:
        self._show_transfer_dialog = bool(visible)

    def _requested_transfer_mode(self, path: str) -> str:
        if self._transfer_mode_provider is None:
            return BINARY
        try:
            return normalize_transfer_mode(self._transfer_mode_provider(path), BINARY)
        except Exception:
            return BINARY

    def _default_download_dir(self) -> str:
        if self._default_download_dir_provider is None:
            return ""
        try:
            return str(self._default_download_dir_provider() or "")
        except Exception:
            return ""

    def _finish_local_download_mutation(self, target_dir: str, after_finished=None) -> None:
        if after_finished is not None:
            after_finished()
        elif self._download_finished_callback is not None:
            self._download_finished_callback(target_dir)

    def set_dir(self, remote_dir: str):
        target = (remote_dir or "").rstrip("/") or "/"
        self.current_dir = target
        self._category_dir = target
        signals_were_blocked = self.directory_tabs.blockSignals(True)
        if self.directory_tabs.count() == 0:
            index = self.directory_tabs.addTab(self._directory_tab_label(target))
            self.directory_tabs.setTabData(index, target)
            self.directory_tabs.setCurrentIndex(index)
        else:
            index = max(0, self.directory_tabs.currentIndex())
            self.directory_tabs.setTabText(index, self._directory_tab_label(target))
            self.directory_tabs.setTabData(index, target)
        self.directory_tabs.blockSignals(signals_were_blocked)
        self.path.setText(target)
        self._update_navigation_controls()
        self.refresh()

    @staticmethod
    def _cache_key(remote_dir: str) -> str:
        return (remote_dir or "/").rstrip("/") or "/"

    @classmethod
    def _normalize_remote_dir(cls, remote_dir: Optional[str]) -> str:
        return cls._cache_key(remote_dir or "/")

    @classmethod
    def _parent_remote_dir(cls, remote_path: str) -> str:
        clean = (remote_path or "/").rstrip("/") or "/"
        if clean == "/":
            return "/"
        return cls._normalize_remote_dir("/".join(clean.split("/")[:-1]) or "/")

    def _invalidate_directory_cache(self, remote_dir: Optional[str] = None) -> None:
        if remote_dir is None:
            self._directory_cache.clear()
            return
        self._directory_cache.pop(self._cache_key(remote_dir), None)

    def _finish_remote_directory_mutation(self, remote_dirs: Iterable[str]) -> None:
        affected = {
            self._normalize_remote_dir(remote_dir)
            for remote_dir in remote_dirs
            if remote_dir
        }
        if not affected:
            return

        panels = list(RemoteDirPanel._instances.values())
        for panel in panels:
            for remote_dir in affected:
                panel._invalidate_directory_cache(remote_dir)

        if not get_transfer_auto_refresh_enabled():
            return

        for panel in panels:
            current = self._normalize_remote_dir(panel.current_dir or "/")
            if current in affected:
                panel.refresh(force=True)

    def _listdir_entries_cached(
        self,
        remote_dir: str,
        *,
        force: bool = False,
    ) -> List[RemoteEntry]:
        if not self.session or not self.session.get("files"):
            return []
        key = self._cache_key(remote_dir)
        now = monotonic()
        cached = self._directory_cache.get(key)
        if not force and cached is not None:
            cached_at, entries = cached
            if now - cached_at <= DIRECTORY_CACHE_TTL_SECONDS:
                return list(entries)
        entries = list(self.session["files"].listdir_entries(key))
        self._directory_cache[key] = (now, entries)
        return list(entries)

    @staticmethod
    def _local_paths_from_mime(mime) -> List[str]:
        if not mime or not mime.hasUrls():
            return []
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]

    def _drop_dest_dir_for_item(self, item: Optional[QTreeWidgetItem]) -> str:
        dest_dir = self.current_dir or "/"
        if item is not None:
            clicked_path = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            clicked_is_dir = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
            if clicked_path and clicked_is_dir:
                dest_dir = clicked_path.rstrip("/") or "/"
        return dest_dir

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if self._local_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._local_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        paths = self._local_paths_from_mime(event.mimeData())
        if not paths:
            super().dropEvent(event)
            return
        if self._apply_local_upload(paths, self.current_dir or "/"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _remote_parent_dir(self, remote_dir: str) -> str:
        cleaned = (remote_dir or "").rstrip("/")
        if not cleaned or cleaned == "/":
            return ""
        parent = cleaned.rsplit("/", 1)[0]
        return parent or "/"

    def _update_navigation_controls(self) -> None:
        has_session = bool(self.session and self.session.get("connected"))
        has_parent = bool(self._remote_parent_dir(self.current_dir)) if has_session else False
        if hasattr(self, "btn_parent"):
            self.btn_parent.setEnabled(has_parent)
        if hasattr(self, "btn_new_folder"):
            self.btn_new_folder.setEnabled(bool(has_session and self.current_dir))
        if hasattr(self, "btn_new_file"):
            self.btn_new_file.setEnabled(bool(has_session and self.current_dir))
        if hasattr(self, "btn_template_upload"):
            self.btn_template_upload.setEnabled(bool(has_session and self.current_dir))

    @staticmethod
    def _child_path(parent_dir: str, name: str) -> str:
        return (parent_dir.rstrip("/") or "") + "/" + name

    def _prompt_new_name(self, *, kind: str) -> str:
        is_folder = kind == "folder"
        title_key = "dirs.new_folder_title" if is_folder else "dirs.new_file_title"
        label_key = "dirs.new_folder_label" if is_folder else "dirs.new_file_label"
        name, ok = QInputDialog.getText(self, t(title_key), t(label_key))
        if not ok:
            return ""
        name = (name or "").strip()
        if not name:
            return ""
        if name in (".", "..") or "/" in name or "\\" in name:
            QMessageBox.warning(self, t("common.error"), t("dirs.invalid_new_name"))
            return ""
        return name

    def _create_remote_item(self, *, kind: str, parent_dir: Optional[str] = None) -> bool:
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return False
        raw_target_dir = parent_dir or self.current_dir or ""
        if not raw_target_dir:
            QMessageBox.warning(self, t("common.error"), t("dirs.no_directory_selected"))
            return False
        target_dir = raw_target_dir.rstrip("/") or "/"

        name = self._prompt_new_name(kind=kind)
        if not name:
            return False
        target_path = self._child_path(target_dir, name)
        files = self.session["files"]
        try:
            if files.exists(target_path):
                QMessageBox.warning(
                    self,
                    t("dirs.conflict_title"),
                    t("dirs.new_item_exists").format(path=target_path),
                )
                return False
            if kind == "folder":
                files.mkdir(target_path)
            else:
                files.write_text(target_path, "")
            self._finish_remote_directory_mutation([target_dir])
            return True
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="FILES")
            return False

    def create_new_folder(self, parent_dir: Optional[str] = None) -> bool:
        return self._create_remote_item(kind="folder", parent_dir=parent_dir)

    def create_new_folder_and_enter(self, parent_dir: Optional[str] = None) -> bool:
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return False
        raw_target_dir = parent_dir or self.current_dir or ""
        if not raw_target_dir:
            QMessageBox.warning(self, t("common.error"), t("dirs.no_directory_selected"))
            return False
        target_dir = raw_target_dir.rstrip("/") or "/"
        name = self._prompt_new_name(kind="folder")
        if not name:
            return False
        target_path = self._child_path(target_dir, name)
        files = self.session["files"]
        try:
            if files.exists(target_path):
                QMessageBox.warning(
                    self,
                    t("dirs.conflict_title"),
                    t("dirs.new_item_exists").format(path=target_path),
            )
                return False
            files.mkdir(target_path)
            self._finish_remote_directory_mutation([target_dir])
            self.set_dir(target_path)
            return True
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="FILES")
            return False

    def create_new_file(self, parent_dir: Optional[str] = None) -> bool:
        return self._create_remote_item(kind="file", parent_dir=parent_dir)

    def _handle_item_double_clicked(self, item, col):
        path = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if not path:
            return
        is_dir = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
        if is_dir:
            self.set_dir(path.rstrip("/") or "/")
            return
        self.file_activated.emit(path)

    def go_parent(self):
        parent = self._remote_parent_dir(self.current_dir)
        if not parent:
            return
        self.set_dir(parent)

    def _icon_for(self, entry: RemoteEntry) -> QIcon:
        st = self.style()
        if entry.is_dir:
            return st.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        lower = entry.name.lower()
        if lower.endswith(".iso"):
            return st.standardIcon(QStyle.StandardPixmap.SP_DriveDVDIcon)
        return st.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def refresh(self, force: bool = False):
        if not self.session or not self.session.get("files"):
            for v in self.views.values():
                v.clear()
            self._update_navigation_controls()
            return

        category_dir = self._category_dir or self.current_dir
        try:
            entries = self._listdir_entries_cached(category_dir, force=bool(force))
        except Exception as e:
            self._show_op_error(
                f"{t('dirs.load_failed') if t('dirs.load_failed') != '[dirs.load_failed]' else 'Dizin okunamadı'}: {e}"
            )
            for v in self.views.values():
                v.clear()
            return

        for v in self.views.values():
            v.clear()

        search_terms = self._search_terms()

        def add(view: QTreeWidget, entry: RemoteEntry):
            it = QTreeWidgetItem()
            it.setText(0, entry.name)
            it.setIcon(0, self._icon_for(entry))
            it.setText(1, "" if entry.is_dir else _fmt_size(entry.size))
            file_type = _file_type(entry.name, entry.is_dir)
            it.setText(2, file_type)
            it.setText(3, _fmt_mtime(entry.mtime))
            it.setData(0, Qt.ItemDataRole.UserRole, entry.path)
            it.setData(0, Qt.ItemDataRole.UserRole + 1, bool(entry.is_dir))
            it.setData(0, _SORT_NAME_ROLE, entry.name)
            it.setData(0, _SORT_SIZE_ROLE, int(entry.size or 0))
            it.setData(0, _SORT_TYPE_ROLE, _file_type_sort_value(entry.name, entry.is_dir))
            it.setData(0, _SORT_MTIME_ROLE, int(entry.mtime or 0))
            view.addTopLevelItem(it)

        parent_dir = self._remote_parent_dir(category_dir)
        if parent_dir:
            def make_parent_item() -> QTreeWidgetItem:
                item = QTreeWidgetItem()
                item.setText(0, "..")
                item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                item.setText(1, "")
                item.setText(2, _file_type("..", True))
                item.setText(3, "")
                item.setData(0, Qt.ItemDataRole.UserRole, parent_dir)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
                item.setData(0, Qt.ItemDataRole.UserRole + 2, True)
                item.setData(0, _SORT_NAME_ROLE, "..")
                item.setData(0, _SORT_SIZE_ROLE, 0)
                item.setData(0, _SORT_TYPE_ROLE, _file_type_sort_value("..", True))
                item.setData(0, _SORT_MTIME_ROLE, 0)
                return item

            self.views["all"].addTopLevelItem(make_parent_item())
            if "folders" in self.views:
                self.views["folders"].addTopLevelItem(make_parent_item())

        for e in entries:
            if not self._entry_matches_search(e, search_terms):
                continue
            add(self.views["all"], e)
            cat = _category(e)
            if cat in self.views:
                add(self.views[cat], e)

        for v in self.views.values():
            v.apply_sort()
            v.resizeColumnToContents(0)
            v.resizeColumnToContents(1)
            v.resizeColumnToContents(2)
            v.resizeColumnToContents(3)

        self._update_undo_enabled()
        self._update_navigation_controls()

    def _search_terms(self) -> List[str]:
        text = ""
        if hasattr(self, "search_in"):
            text = self.search_in.text()
        return [part.casefold() for part in text.split() if part.strip()]

    def _entry_matches_search(self, entry: RemoteEntry, terms: List[str]) -> bool:
        if not terms:
            return True
        file_type = _file_type(entry.name, entry.is_dir)
        size_text = "" if entry.is_dir else _fmt_size(entry.size)
        searchable = " ".join(
            str(value)
            for value in (
                entry.name,
                entry.path,
                size_text,
                int(entry.size or 0),
                file_type,
                _file_type_sort_value(entry.name, entry.is_dir),
                _fmt_mtime(entry.mtime),
            )
            if value is not None
        ).casefold()
        return all(term in searchable for term in terms)

    # ---------- selection helpers ----------
    def _selected_paths_from_view(self, view: QTreeWidget) -> List[str]:
        paths: List[str] = []
        for it in view.selectedItems():
            if bool(it.data(0, Qt.ItemDataRole.UserRole + 2)):
                continue
            p = it.data(0, Qt.ItemDataRole.UserRole)
            if p:
                paths.append(str(p))
        return paths

    def _selected_entries_from_view(self, view: QTreeWidget) -> List[Tuple[str, bool]]:
        entries: List[Tuple[str, bool]] = []
        for it in view.selectedItems():
            if bool(it.data(0, Qt.ItemDataRole.UserRole + 2)):
                continue
            path = str(it.data(0, Qt.ItemDataRole.UserRole) or "")
            if path:
                entries.append((path, bool(it.data(0, Qt.ItemDataRole.UserRole + 1))))
        return entries

    @staticmethod
    def _submit_candidate(entries: List[Tuple[str, bool]]) -> str:
        if len(entries) != 1:
            return ""
        path, is_dir = entries[0]
        if is_dir or not path.lower().endswith((".slurm", ".sbatch")):
            return ""
        return path

    def selected_paths(self, tab_key: str = "all") -> List[str]:
        view = self.views.get(tab_key, self.views["all"])
        return self._selected_paths_from_view(view)

    # ---------- undo ----------
    def _update_undo_enabled(self) -> None:
        self.btn_undo.setEnabled(bool(RemoteDirPanel._last_undo))

    def _set_last_undo(self, rec: Optional[_UndoRecord]) -> None:
        RemoteDirPanel._last_undo = rec
        # reflect on all panels
        for p in list(RemoteDirPanel._instances.values()):
            try:
                p._update_undo_enabled()
            except Exception:
                pass

    def undo_last(self) -> None:
        if not self.session or not self.session.get("files"):
            return
        rec = RemoteDirPanel._last_undo
        if not rec:
            return
        if rec.kind != "move" or not rec.moves:
            self._set_last_undo(None)
            return

        files = self.session["files"]
        # reverse order for safety
        moves = list(reversed(rec.moves))
        affected_dirs = set()

        # build undo plan (dst -> src)
        plan: List[_PlannedOp] = []
        policy: Optional[str] = None

        for src, dst in moves:
            # undo means: move dst back to src
            undo_src = dst.rstrip("/")
            undo_dst = src.rstrip("/")
            affected_dirs.add(self._parent_remote_dir(undo_src))
            affected_dirs.add(self._parent_remote_dir(undo_dst))

            # if destination already exists, resolve
            try:
                exists = bool(files.exists(undo_dst))
            except Exception:
                try:
                    files.listdir(undo_dst)
                    exists = True
                except Exception:
                    exists = False

            if exists:
                if policy is None:
                    action = self._resolve_conflict(
                        undo_dst,
                        src=undo_src,
                        source_is_local=False,
                        target_is_local=False,
                    )
                    if action.endswith("_all"):
                        policy = action.replace("_all", "")
                    action_simple = action.replace("_all", "")
                else:
                    action_simple = policy

                if action_simple == "cancel":
                    return
                if action_simple == "skip":
                    continue
                if action_simple == "rename":
                    dst_dir = os.path.dirname(undo_dst) or "/"
                    current_name = os.path.basename(undo_dst)
                    new_dst = self._prompt_rename(dst_dir, current_name)
                    if not new_dst:
                        continue
                    undo_dst = new_dst
                if action_simple == "overwrite":
                    # delete existing target before moving back
                    try:
                        isdir = bool(files.is_dir(undo_dst))
                    except Exception:
                        isdir = False
                    plan.append(_PlannedOp(op="delete", src="", dst=undo_dst, recursive=isdir))

            plan.append(_PlannedOp(op="move", src=undo_src, dst=undo_dst, recursive=False))

        if not plan:
            self._set_last_undo(None)
            return

        def after_finished() -> None:
            self._set_last_undo(None)
            self._finish_remote_directory_mutation(affected_dirs)

        ok = self._run_plan_with_progress(plan, "Geri alınıyor...", after_finished=after_finished)
        if not ok:
            return

    # ---------- context menu ----------
    def _on_context_menu(self, view: QTreeWidget, pos: QPoint):
        if not self.session or not self.session.get("files"):
            return

        files = self.session.get("files")

        item = view.itemAt(pos)
        clicked_path: Optional[str] = None
        clicked_is_dir = False
        if item is not None:
            if not bool(item.data(0, Qt.ItemDataRole.UserRole + 2)):
                clicked_path = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
                clicked_is_dir = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))

        selected_items = view.selectedItems()
        selected_entries = self._selected_entries_from_view(view)
        if clicked_path and item is not None and not item.isSelected():
            selected_entries = [(clicked_path, clicked_is_dir)]
            selected_items = [item]
        elif not selected_items and clicked_path:
            selected_entries = [(clicked_path, clicked_is_dir)]
        sel_paths = [path for path, _is_dir in selected_entries]
        submit_path = self._submit_candidate(selected_entries)

        menu = QMenu(self)
        clipboard = get_file_clipboard()

        new_parent_dir = clicked_path if clicked_path and clicked_is_dir else (self.current_dir or "/")
        act_download = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[0]))
        act_save_as = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[1]))
        act_add_queue = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[2]))
        act_view_edit = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[3]))
        act_edit_new_window = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[4]))
        act_open_new_tab = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[5]))
        act_submit = None
        if submit_path:
            act_submit = menu.addAction(t("dirs.submit_sbatch"))
        act_open_out1 = None
        act_open_out2 = None
        existing_output_actions: Dict[object, Tuple[str, int]] = {}
        if self.enable_output_menu:
            act_open_out1 = menu.addAction(
                t("jobs_outputs.open_out1")
            )
            act_open_out2 = menu.addAction(
                t("jobs_outputs.open_out2")
            )
            act_open_file_new_window = menu.addAction(
                t("jobs_outputs.open_file_new_window")
            )
            act_open_out1_new_window = menu.addAction(
                t("jobs_outputs.open_out1_new_window")
            )
            act_open_out2_new_window = menu.addAction(
                t("jobs_outputs.open_out2_new_window")
            )
            act_open_out1_new_tab = menu.addAction(
                t("jobs_outputs.open_out1_new_tab")
            )
            act_open_out2_new_tab = menu.addAction(
                t("jobs_outputs.open_out2_new_tab")
            )
            output_targets: List[Tuple[str, str]] = []
            if self._output_target_provider is not None:
                try:
                    output_targets = list(self._output_target_provider() or [])
                except Exception:
                    output_targets = []
            if output_targets:
                menu.addSeparator()
                for target_id, target_label in output_targets:
                    act_existing_out1 = menu.addAction(
                        t("jobs_outputs.assign_existing_out1").format(
                            target=target_label
                        )
                    )
                    act_existing_out2 = menu.addAction(
                        t("jobs_outputs.assign_existing_out2").format(
                            target=target_label
                        )
                    )
                    existing_output_actions[act_existing_out1] = (target_id, 0)
                    existing_output_actions[act_existing_out2] = (target_id, 1)
        else:
            act_open_file_new_window = None
            act_open_out1_new_window = None
            act_open_out2_new_window = None
            act_open_out1_new_tab = None
            act_open_out2_new_tab = None
        menu.addSeparator()
        act_new_folder = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[6]))
        act_new_folder_enter = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[7]))
        act_new_file = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[8]))
        act_refresh = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[9]))
        menu.addSeparator()
        sys_clip = QApplication.clipboard().mimeData()
        has_local_urls = bool(self._local_paths_from_mime(sys_clip))
        clip = clipboard.get()
        act_paste_local_here = None
        act_paste_local_into = None
        act_paste_here = None
        act_paste_into = None
        act_paste_to_local = None
        act_undo = None
        if has_local_urls:
            act_paste_local_here = menu.addAction(
                t("dirs.paste_from_local")
            )
            if clicked_path and clicked_is_dir:
                act_paste_local_into = menu.addAction(
                    t("dirs.paste_from_local_into")
                )
        if clip and clip.paths:
            act_paste_here = menu.addAction(t("dirs.paste"))
            if clicked_path and clicked_is_dir:
                act_paste_into = menu.addAction(t("dirs.paste_into"))
            act_paste_to_local = menu.addAction(
                t("dirs.paste_to_local")
            )
        if RemoteDirPanel._last_undo is not None:
            act_undo = menu.addAction(t("dirs.undo"))
        if any(
            action is not None
            for action in (
                act_paste_local_here,
                act_paste_here,
                act_undo,
            )
        ):
            menu.addSeparator()
        act_delete = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[10]))
        act_rename = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[11]))
        act_copy_path = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[12]))
        act_copy = menu.addAction(t("dirs.copy"))
        act_move = menu.addAction(t("dirs.move"))
        act_permissions = menu.addAction(t(REMOTE_CONTEXT_MENU_KEYS[13]))

        has_selection = bool(sel_paths)
        single_selection = len(sel_paths) == 1
        single_selection_is_dir = bool(selected_entries[0][1]) if single_selection else False
        act_download.setEnabled(has_selection)
        act_save_as.setEnabled(has_selection)
        act_add_queue.setEnabled(False)
        act_view_edit.setEnabled(single_selection and not single_selection_is_dir)
        act_edit_new_window.setEnabled(single_selection and not single_selection_is_dir)
        act_open_new_tab.setEnabled(single_selection and single_selection_is_dir)
        if act_open_out1 is not None:
            act_open_out1.setEnabled(single_selection and not single_selection_is_dir)
        if act_open_out2 is not None:
            act_open_out2.setEnabled(single_selection and not single_selection_is_dir)
        if act_open_file_new_window is not None:
            act_open_file_new_window.setEnabled(single_selection and not single_selection_is_dir)
        if act_open_out1_new_window is not None:
            act_open_out1_new_window.setEnabled(single_selection and not single_selection_is_dir)
        if act_open_out2_new_window is not None:
            act_open_out2_new_window.setEnabled(single_selection and not single_selection_is_dir)
        if act_open_out1_new_tab is not None:
            act_open_out1_new_tab.setEnabled(single_selection and not single_selection_is_dir)
        if act_open_out2_new_tab is not None:
            act_open_out2_new_tab.setEnabled(single_selection and not single_selection_is_dir)
        for action in existing_output_actions:
            if hasattr(action, "setEnabled"):
                action.setEnabled(single_selection and not single_selection_is_dir)
        act_delete.setEnabled(has_selection)
        act_rename.setEnabled(single_selection)
        act_copy_path.setEnabled(has_selection)
        act_copy.setEnabled(has_selection)
        act_move.setEnabled(has_selection)
        act_permissions.setEnabled(False)

        chosen = menu.exec(view.viewport().mapToGlobal(pos))
        if not chosen:
            return

        if chosen == act_new_folder:
            self.create_new_folder(new_parent_dir)
            return
        if chosen == act_new_folder_enter:
            self.create_new_folder_and_enter(new_parent_dir)
            return
        if chosen == act_new_file:
            self.create_new_file(new_parent_dir)
            return
        if chosen == act_refresh:
            self.refresh(force=True)
            return

        if act_paste_local_here is not None and chosen == act_paste_local_here:
            self._paste_system_clipboard_into(self.current_dir or "/")
            return
        if act_paste_local_into is not None and chosen == act_paste_local_into and clicked_path:
            self._paste_system_clipboard_into(clicked_path)
            return
        if act_paste_here is not None and chosen == act_paste_here:
            self._paste_remote_clipboard_into(self.current_dir or "/")
            return
        if act_paste_into is not None and chosen == act_paste_into and clicked_path:
            self._paste_remote_clipboard_into(clicked_path)
            return
        if act_paste_to_local is not None and chosen == act_paste_to_local:
            self._paste_remote_to_local()
            return
        if act_undo is not None and chosen == act_undo:
            self.undo_last()
            return

        if not sel_paths:
            return

        if act_submit is not None and chosen == act_submit:
            self.submit_requested.emit(submit_path)
            return

        if chosen == act_view_edit:
            rp = sel_paths[0]
            try:
                files.listdir(rp.rstrip("/"))
                QMessageBox.information(self, t("common.info"), t("dirs.folder_not_editable"))
                return
            except Exception:
                pass
            self.open_file.emit(rp)
            return

        if chosen == act_edit_new_window:
            self.open_file_in_new_window.emit(sel_paths[0])
            return

        if chosen == act_open_new_tab and single_selection_is_dir:
            self.open_directory_in_new_tab(sel_paths[0])
            return

        if act_open_out1 is not None and chosen == act_open_out1:
            self.open_in_slot.emit(0, sel_paths[0])
            return

        if act_open_out2 is not None and chosen == act_open_out2:
            self.open_in_slot.emit(1, sel_paths[0])
            return

        if act_open_file_new_window is not None and chosen == act_open_file_new_window:
            self.open_file_follow_new_window.emit(sel_paths[0])
            return

        if act_open_out1_new_window is not None and chosen == act_open_out1_new_window:
            self.open_in_slot_new_window.emit(0, sel_paths[0])
            return

        if act_open_out2_new_window is not None and chosen == act_open_out2_new_window:
            self.open_in_slot_new_window.emit(1, sel_paths[0])
            return

        if act_open_out1_new_tab is not None and chosen == act_open_out1_new_tab:
            self.open_in_slot_new_tab.emit(0, sel_paths[0])
            return

        if act_open_out2_new_tab is not None and chosen == act_open_out2_new_tab:
            self.open_in_slot_new_tab.emit(1, sel_paths[0])
            return

        if chosen in existing_output_actions:
            target_id, slot = existing_output_actions[chosen]
            self.open_in_existing_follower.emit(target_id, slot, sel_paths[0])
            return

        if chosen == act_download:
            self.download_selected(target_dir=self._default_download_dir())
            return

        if chosen == act_save_as:
            self.download_selected()
            return

        if chosen == act_delete:
            self._delete_paths(sel_paths)
            return

        if chosen == act_rename:
            self._rename_paths(sel_paths)
            return

        if chosen == act_copy_path:
            QApplication.clipboard().setText("\n".join(sel_paths))
            return

        if chosen == act_copy:
            clipboard.set("copy", sel_paths)
            return

        if chosen == act_move:
            clipboard.set("move", sel_paths)
            return

    def rename_selected(self, view: Optional[QTreeWidget] = None) -> bool:
        if view is None:
            current = self.tabs.currentWidget()
            view = current if isinstance(current, QTreeWidget) else self.views["all"]
        return self._rename_paths(self._selected_paths_from_view(view))

    def _rename_paths(self, paths: List[str]) -> bool:
        if not self.session or not self.session.get("files"):
            return False
        if len(paths) != 1:
            QMessageBox.information(self, t("common.info"), t("dirs.rename_single_required"))
            return False
        old = paths[0].rstrip("/")
        base = old.split("/")[-1]
        new_name, ok = QInputDialog.getText(
            self,
            t("dirs.rename"),
            t("dirs.rename_label"),
            text=base,
        )
        if not ok or not new_name.strip():
            return False
        parent = "/".join(old.split("/")[:-1]) or "/"
        dst = parent.rstrip("/") + "/" + new_name.strip()
        try:
            self.session["files"].rename(old, dst)
            self._finish_remote_directory_mutation([parent])
            return True
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="FILES")
            return False

    # ---------- delete / paste ----------
    def _delete_paths(self, paths: List[str]) -> None:
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        files = self.session["files"]
        if not paths:
            return
        msg = t("dirs.delete_confirm") + "\n" + "\n".join([p.split("/")[-1] for p in paths[:10]])
        if len(paths) > 10:
            msg += f"\n... (+{len(paths)-10})"
        if QMessageBox.question(
            self,
            t("common.confirm"),
            msg,
        ) != QMessageBox.StandardButton.Yes:
            return
        affected_dirs = set()
        for rp in paths:
            recursive = False
            try:
                recursive = bool(files.is_dir(rp.rstrip("/")))
            except Exception:
                try:
                    files.listdir(rp.rstrip("/"))
                    recursive = True
                except Exception:
                    recursive = rp.endswith("/")
            files.remove(rp.rstrip("/"), recursive=recursive)
            affected_dirs.add(self._parent_remote_dir(rp))
        affected_dirs.add(self.current_dir or "/")
        self._finish_remote_directory_mutation(affected_dirs)

    def delete_selected(self):
        tab = self.tabs.currentWidget()
        tab_key = "all"
        for k, v in self.views.items():
            if v is tab:
                tab_key = k
                break
        sel = self.selected_paths(tab_key)
        if not sel:
            QMessageBox.information(self, t("common.info"), t("dirs.no_file_selected"))
            return
        self._delete_paths(sel)

    # ---------- conflict dialogs ----------
    def _resolve_conflict(
        self,
        dst: str,
        *,
        src: str = "",
        source_is_local: bool | None = None,
        target_is_local: bool | None = None,
    ):
        """Return one of: overwrite|resume|skip|rename|cancel (optionally applied to all)."""
        source = self._conflict_info(src or dst, is_local=source_is_local)
        target = self._conflict_info(dst, is_local=target_is_local)
        decision = TransferConflictDialog.get_decision(
            self,
            source=source,
            target=target,
        )
        action = self._normalize_conflict_decision(decision, source, target)
        apply_all = bool(decision.always_use or decision.apply_current_queue_only)
        return action + "_all" if apply_all else action

    def _conflict_info(
        self,
        path: str,
        *,
        is_local: bool | None = None,
    ) -> TransferConflictInfo:
        if is_local is True:
            try:
                st = os.stat(path)
                return TransferConflictInfo(
                    path=path,
                    size=int(st.st_size),
                    mtime=int(st.st_mtime),
                )
            except Exception:
                return TransferConflictInfo(path=path)
        if is_local is False and self.session and self.session.get("files"):
            try:
                size, mtime = self.session["files"].stat(path)
                return TransferConflictInfo(
                    path=path,
                    size=int(size),
                    mtime=int(mtime),
                )
            except Exception:
                return TransferConflictInfo(path=path)
        try:
            if os.path.exists(path):
                st = os.stat(path)
                return TransferConflictInfo(
                    path=path,
                    size=int(st.st_size),
                    mtime=int(st.st_mtime),
                )
        except Exception:
            pass
        if self.session and self.session.get("files"):
            try:
                size, mtime = self.session["files"].stat(path)
                return TransferConflictInfo(
                    path=path,
                    size=int(size),
                    mtime=int(mtime),
                )
            except Exception:
                pass
        return TransferConflictInfo(path=path)

    @staticmethod
    def _normalize_conflict_decision(
        decision: TransferConflictDecision,
        source: TransferConflictInfo,
        target: TransferConflictInfo,
    ) -> str:
        action = decision.action
        if action in {"overwrite", "resume", "skip", "rename", "cancel"}:
            return action
        source_newer = (
            source.mtime is not None
            and target.mtime is not None
            and int(source.mtime) > int(target.mtime)
        )
        size_differs = (
            source.size is not None
            and target.size is not None
            and int(source.size) != int(target.size)
        )
        if action == "overwrite_if_newer":
            return "overwrite" if source_newer else "skip"
        if action == "overwrite_if_size_differs":
            return "overwrite" if size_differs else "skip"
        if action == "overwrite_if_size_differs_or_newer":
            return "overwrite" if (size_differs or source_newer) else "skip"
        return "cancel"

    def _prompt_rename(self, dst_dir: str, current_name: str) -> str | None:
        new_name, ok = QInputDialog.getText(self, "Yeniden adlandır", "Yeni ad:", text=current_name)
        if not ok:
            return None
        new_name = (new_name or "").strip()
        if not new_name:
            return None
        return dst_dir.rstrip("/") + "/" + new_name

    # ---------- friendly errors (permission/quota UX) ----------
    def _humanize_error(self, raw: str) -> Tuple[str, str]:
        """Return (title, short_message), raw goes to details."""
        text = (raw or "").strip()
        lo = text.lower()

        if "permission denied" in lo or "access is denied" in lo:
            return "İzin yok (Permission denied)", "Bu işlem için gerekli izinlerin yok. (chmod/chown veya doğru dizin?)"

        if "no space left on device" in lo or "disk quota exceeded" in lo or "quota exceeded" in lo:
            return "Disk dolu / Kota aşıldı", "Hedef tarafta boş alan kalmamış veya kota limitine ulaşıldı."

        if "read-only file system" in lo:
            return "Salt okunur dosya sistemi", "Hedef dosya sistemi read-only. Yazma işlemi yapılamaz."

        # fallback
        return t("common.error"), "İşlem başarısız oldu. Detaylar aşağıda."

    def _show_op_error(self, raw: str) -> None:
        title, short = self._humanize_error(raw)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(short)
        box.setDetailedText(raw)
        box.exec()

    # ---------- queue UI ----------
    def _queue_set(self, plan: List[_PlannedOp]) -> None:
        self.queue_list.clear()
        for op in plan:
            name = os.path.basename((op.dst or op.src).rstrip("/"))
            label = f"{op.op}: {name}"
            self.queue_list.addItem(label)
        self.queue_current.setText("-")
        self.queue_group.setVisible(True)

    def _queue_progress(self, step: int, label: str) -> None:
        self.queue_current.setText(label)
        # Worker emits progress *before* executing the step, so we remove the
        # previous item when step advances.
        if step > 1 and self.queue_list.count() > 0:
            self.queue_list.takeItem(0)

    def _queue_clear(self) -> None:
        self.queue_current.setText("-")
        self.queue_list.clear()
        self.queue_group.setVisible(False)

    def _journal_transfer(self, event: str, **fields) -> None:
        """Append transfer operation events for diagnostics/audit."""
        try:
            from pathlib import Path
            import json
            from datetime import datetime

            p = Path.home() / ".truba_slurm_gui" / "transfer_journal.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            payload = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event}
            payload.update(fields or {})
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ---------- plan runner ----------
    def _run_plan_with_progress(
        self,
        plan: List[_PlannedOp],
        title: str,
        after_finished=None,
    ) -> bool:
        if not self.session or not self.session.get("files"):
            return False
        if not plan:
            return True
        active_keys: set[tuple[str, str, str]] = set()
        filtered_plan: List[_PlannedOp] = []
        for op in plan:
            key = self._transfer_key(op)
            if key is not None:
                if key in self._active_transfer_keys or key in active_keys:
                    continue
                active_keys.add(key)
            filtered_plan.append(op)
        if not filtered_plan:
            return True
        self._active_transfer_keys.update(active_keys)
        plan = filtered_plan
        transfer_items = [self._transfer_item_from_plan(p) for p in plan]
        if self._transfer_activity_callback is not None:
            self._transfer_activity_callback("queued", transfer_items, title)
        max_parallel_limit = 10
        parallel_limit = get_transfer_parallelism()
        files = self.session.get("files") if self.session else None
        if any(item.op == "download_tree" for item in transfer_items) or not bool(
            getattr(files, "supports_parallel_transfers", False)
        ):
            parallel_limit = 1
            max_parallel_limit = 1
        dlg = TransferDialog(
            self,
            title=title,
            items=transfer_items,
            run_item=self._execute_transfer_item,
            parallel_limit=parallel_limit,
            max_parallel_limit=max_parallel_limit,
        )
        if self._transfer_activity_callback is not None:
            self._transfer_activity_callback("controller", [dlg], title)
        self._active_plan = list(plan)
        self._active_step = 0
        self._active_title = title
        def handle_finished(_result: int) -> None:
            try:
                if self._transfer_activity_callback is not None:
                    event = "completed" if dlg.finished_cleanly() else "failed"
                    self._transfer_activity_callback(event, transfer_items, title)
                if dlg.finished_cleanly() and after_finished is not None:
                    after_finished()
            finally:
                self._active_transfer_keys.difference_update(active_keys)
                try:
                    self._transfer_dialogs.remove(dlg)
                except ValueError:
                    pass
                dlg.deleteLater()

        dlg.finished.connect(handle_finished)
        self._transfer_dialogs.append(dlg)
        dlg.start()
        if self._show_transfer_dialog:
            dlg.show()
        self._active_plan = []
        self._active_step = 0
        self._active_title = ""
        return True

    @staticmethod
    def _transfer_key(op: _PlannedOp) -> tuple[str, str, str] | None:
        if op.op not in {"upload", "download", "download_tree"}:
            return None
        return (op.op, op.src, op.dst)

    def _transfer_item_size(self, op: _PlannedOp) -> Optional[int]:
        try:
            if op.op == "download" and self.session and self.session.get("files"):
                size, _mtime = self.session["files"].stat(op.src)
                return max(0, int(size or 0))
            if op.op == "upload" and op.src:
                path = Path(op.src)
                if path.exists() and path.is_file():
                    return max(0, int(path.stat().st_size))
        except Exception:
            return None
        return None

    def _transfer_item_from_plan(self, op: _PlannedOp) -> TransferItem:
        return TransferItem(
            op=op.op,
            src=op.src,
            dst=op.dst,
            recursive=op.recursive,
            size=self._transfer_item_size(op),
        )

    def _remote_tree_entries_for_download(
        self,
        base_remote: str,
    ) -> List[Tuple[str, str, bool, int]]:
        files = self.session["files"]
        base_remote = base_remote.rstrip("/")
        out: List[Tuple[str, str, bool, int]] = []

        def rec(cur: str, rel: str) -> None:
            entries = files.listdir_entries(cur)
            for entry in entries:
                epath = entry.path.rstrip("/")
                erel = (rel + "/" if rel else "") + entry.name
                if entry.is_dir:
                    out.append((epath, erel, True, 0))
                    rec(epath, erel)
                else:
                    out.append((epath, erel, False, int(entry.size or 0)))

        rec(base_remote, "")
        return out

    def _download_remote_tree(
        self,
        remote_dir: str,
        local_dir: str,
        progress_cb=None,
        files=None,
    ) -> None:
        if files is None:
            if not self.session or not self.session.get("files"):
                raise RuntimeError(t("common.no_connection"))
            files = self.session["files"]
        if files is None:
            raise RuntimeError(t("common.no_connection"))
        os.makedirs(local_dir, exist_ok=True)
        entries = self._remote_tree_entries_for_download_with_backend(files, remote_dir)
        total = sum(size for _path, _rel, is_dir, size in entries if not is_dir)
        done = 0
        if progress_cb is not None:
            progress_cb(0, total)
        for rpath, rel, is_dir, size in entries:
            local_path = os.path.join(local_dir, rel)
            if is_dir:
                os.makedirs(local_path, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(local_path) or local_dir, exist_ok=True)
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except IsADirectoryError:
                    shutil.rmtree(local_path, ignore_errors=True)
            def file_progress(file_done: int, file_total: int) -> None:
                if progress_cb is None or total <= 0:
                    return
                file_size = max(0, int(size or file_total or 0))
                progress_cb(min(total, done + min(file_size, int(file_done or 0))), total)

            download_with_mode(
                files,
                rpath,
                local_path,
                self._requested_transfer_mode(rpath),
                progress_cb=file_progress,
            )
            done += max(0, int(size or 0))
            if progress_cb is not None and total > 0:
                progress_cb(done, total)

    def _remote_tree_entries_for_download_with_backend(
        self,
        files,
        base_remote: str,
    ) -> List[Tuple[str, str, bool, int]]:
        base_remote = base_remote.rstrip("/")
        out: List[Tuple[str, str, bool, int]] = []

        def rec(cur: str, rel: str) -> None:
            entries = files.listdir_entries(cur)
            for entry in entries:
                epath = entry.path.rstrip("/")
                erel = (rel + "/" if rel else "") + entry.name
                if entry.is_dir:
                    out.append((epath, erel, True, 0))
                    rec(epath, erel)
                else:
                    out.append((epath, erel, False, int(entry.size or 0)))

        rec(base_remote, "")
        return out

    def _execute_transfer_item(self, item: TransferItem, progress_cb=None) -> None:
        if not self.session or not self.session.get("files"):
            raise RuntimeError(t("common.no_connection"))
        files = self.session["files"]
        transfer_files = self._open_transfer_backend(files)
        op = item.op
        try:
            if op == "delete":
                transfer_files.remove(item.dst, recursive=item.recursive)
            elif op == "copy":
                transfer_files.copy(item.src, item.dst, recursive=item.recursive)
            elif op == "move":
                transfer_files.move(item.src, item.dst)
            elif op == "upload":
                upload_with_mode(
                    transfer_files,
                    item.src,
                    item.dst,
                    self._requested_transfer_mode(item.src),
                    progress_cb=progress_cb,
                )
            elif op == "download":
                download_with_mode(
                    transfer_files,
                    item.src,
                    item.dst,
                    self._requested_transfer_mode(item.src),
                    progress_cb=progress_cb,
                )
            elif op == "download_tree":
                self._download_remote_tree(
                    item.src,
                    item.dst,
                    progress_cb=progress_cb,
                    files=transfer_files,
                )
            elif op == "mkdir_remote":
                transfer_files.mkdir(item.dst)
            elif op == "mkdir_local":
                os.makedirs(item.dst, exist_ok=True)
            elif op == "delete_local":
                if os.path.isdir(item.dst):
                    shutil.rmtree(item.dst, ignore_errors=True)
                else:
                    try:
                        os.remove(item.dst)
                    except FileNotFoundError:
                        pass
            else:
                raise RuntimeError(f"Unknown op: {op}")
        finally:
            if transfer_files is not files:
                close = getattr(transfer_files, "close", None)
                if callable(close):
                    close()

    @staticmethod
    def _open_transfer_backend(files):
        opener = getattr(files, "open_transfer_backend", None)
        if callable(opener):
            try:
                return opener()
            except Exception:
                return files
        return files

    def shutdown(self) -> None:
        """Cancel any in-flight batch operation (best-effort).

        This does not add new UX; it only prevents orphan threads and
        persists remaining steps as a diagnostic artifact.
        """
        try:
            if self._active_worker is not None:
                try:
                    self._active_worker.cancel()
                except Exception:
                    pass
            if self._active_thread is not None:
                try:
                    self._active_thread.quit()
                except Exception:
                    pass
                try:
                    self._active_thread.wait(1500)
                except Exception:
                    pass
            # Persist remaining plan if any.
            try:
                if self._active_plan:
                    remaining = self._active_plan[max(0, self._active_step - 1):]
                    if remaining:
                        self._persist_batch_state(remaining, title=self._active_title or "shutdown")
            except Exception:
                pass
        finally:
            self._active_thread = None
            self._active_worker = None
            self._active_plan = []
            self._active_step = 0
            self._active_title = ""

    def _persist_batch_state(self, remaining: List[_PlannedOp], *, title: str) -> None:
        """Write remaining batch operations to ~/.truba_slurm_gui/last_batch.json.

        This is *logs-only* / diagnostics; it does not auto-resume.
        """
        try:
            from pathlib import Path
            import json
            import time

            out_path = Path.home() / ".truba_slurm_gui" / "last_batch.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "ts": int(time.time()),
                "title": title,
                "remaining": [
                    {
                        "op": op.op,
                        "src": op.src,
                        "dst": op.dst,
                        "recursive": bool(op.recursive),
                    }
                    for op in remaining
                ],
            }
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ---------- copy/move helpers ----------
    def _build_copy_move_plan_with_conflicts(self, op: str, src_paths: List[str], dest_dir: str) -> List[_PlannedOp] | None:
        if not self.session or not self.session.get("files"):
            return None
        files = self.session.get("files")

        plan: List[_PlannedOp] = []
        policy: Optional[str] = None  # overwrite/skip/rename/cancel

        for src in src_paths:
            src_clean = src.rstrip("/")
            name = os.path.basename(src_clean)
            dst_dir = dest_dir.rstrip("/") or "/"
            dst = dst_dir.rstrip("/") + "/" + name

            recursive = False
            if op == "copy":
                try:
                    recursive = bool(files.is_dir(src_clean))
                except Exception:
                    try:
                        files.listdir(src_clean)
                        recursive = True
                    except Exception:
                        recursive = False

            while True:
                try:
                    exists = bool(files.exists(dst))
                except Exception:
                    try:
                        files.listdir(dst)
                        exists = True
                    except Exception:
                        exists = False

                if exists:
                    if policy is None:
                        action = self._resolve_conflict(
                            dst,
                            src=src_clean,
                            source_is_local=False,
                            target_is_local=False,
                        )
                        if action.endswith("_all"):
                            policy = action.replace("_all", "")
                        action_simple = action.replace("_all", "")
                    else:
                        action_simple = policy

                    if action_simple == "cancel":
                        return None
                    if action_simple == "skip":
                        break
                    if action_simple == "rename":
                        new_dst = self._prompt_rename(dst_dir, name)
                        if not new_dst:
                            break
                        dst = new_dst
                        continue
                    if action_simple == "overwrite":
                        try:
                            isdir = bool(files.is_dir(dst))
                        except Exception:
                            isdir = False
                        if recursive and isdir:
                            if op == "move":
                                plan.append(_PlannedOp(op="copy", src=src_clean, dst=dst, recursive=True))
                                plan.append(_PlannedOp(op="delete", src="", dst=src_clean, recursive=True))
                                break
                        else:
                            plan.append(_PlannedOp(op="delete", src="", dst=dst, recursive=isdir))

                plan.append(_PlannedOp(op=op, src=src_clean, dst=dst, recursive=recursive))
                break

        return plan

    def _apply_copy_move_with_conflicts(self, op: str, src_paths: List[str], dest_dir: str) -> bool:
        plan = self._build_copy_move_plan_with_conflicts(op, src_paths, dest_dir)
        if plan is None:
            return False

        title = "İşlem yapılıyor..."
        if op == "copy":
            title = "Kopyalanıyor..."
        elif op == "move":
            title = "Taşınıyor..."

        affected_dirs = {self._normalize_remote_dir(dest_dir)}
        if op == "move":
            for src in src_paths:
                affected_dirs.add(self._parent_remote_dir(src))

        ok = self._run_plan_with_progress(
            plan,
            title,
            after_finished=lambda: self._finish_remote_directory_mutation(affected_dirs),
        )
        if not ok:
            return False

        # store undo for move only
        if op == "move":
            moves: List[Tuple[str, str]] = [(p.src, p.dst) for p in plan if p.op == "move"]
            if moves:
                self._set_last_undo(_UndoRecord(kind="move", moves=moves))
        return True

    def _paste_remote_clipboard_into(self, dest_dir: str) -> None:
        if not self.session or not self.session.get("files"):
            return
        clipboard = get_file_clipboard()
        clip = clipboard.get()
        if not clip or not clip.paths:
            return

        dest_dir = (dest_dir or "/").strip()
        if not dest_dir.startswith("/"):
            dest_dir = "/" + dest_dir
        dest_dir = dest_dir.rstrip("/") or "/"

        try:
            op = "copy" if clip.op == "copy" else "move"
            ok = self._apply_copy_move_with_conflicts(op, [s for s in clip.paths], dest_dir)
            if ok and clip.op == "move":
                clipboard.clear()
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="FILES")


    def _paste_system_clipboard_into(self, dest_dir: str) -> bool:
        """If OS clipboard contains local file urls, upload them into dest_dir."""
        cb = QApplication.clipboard().mimeData()
        if not cb or not cb.hasUrls():
            return False
        local_paths = [u.toLocalFile() for u in cb.urls() if u.isLocalFile()]
        if not local_paths:
            return False
        return self._apply_local_upload(local_paths, dest_dir)

    def _paste_remote_to_local(self) -> None:
        """Download internal remote clipboard items into a chosen local directory."""
        if not self.session or not self.session.get("files"):
            return
        clip = get_file_clipboard().get()
        if not clip or not clip.paths:
            return
        target_dir = QFileDialog.getExistingDirectory(
            self, t("dirs.select_local_folder")
        )
        if not target_dir:
            return
        ok = self._apply_remote_download(clip.paths, target_dir)
        if ok and clip.op == "move":
            # move doesn't make sense for remote->local; keep clipboard as-is
            pass

    def _remote_walk(self, base_remote: str) -> List[Tuple[str, str, bool]]:
        """Return list of (remote_path, rel_path, is_dir) under base_remote including base."""
        files = self.session["files"]
        base_remote = base_remote.rstrip("/")
        out: List[Tuple[str, str, bool]] = []

        def rec(cur: str, rel: str):
            try:
                entries = files.listdir_entries(cur)
            except Exception:
                return
            for e in entries:
                epath = e.path.rstrip("/")
                erel = (rel + "/" if rel else "") + e.name
                if e.is_dir:
                    out.append((epath, erel, True))
                    rec(epath, erel)
                else:
                    out.append((epath, erel, False))

        out.append((base_remote, "", True))
        rec(base_remote, "")
        return out

    def _apply_remote_download(
        self,
        src_paths: List[str],
        target_dir: str,
        after_finished=None,
    ) -> bool:
        if not self.session or not self.session.get("files"):
            return False
        files = self.session["files"]
        target_dir = os.path.abspath(target_dir)

        plan: List[_PlannedOp] = []
        policy: Optional[str] = None

        seen_sources: set[str] = set()
        for src in src_paths:
            src_clean = src.rstrip("/")
            if not src_clean or src_clean in seen_sources:
                continue
            seen_sources.add(src_clean)
            name = os.path.basename(src_clean)
            local_dst = os.path.join(target_dir, name)

            # detect if remote is dir
            try:
                is_dir = bool(files.is_dir(src_clean))
            except Exception:
                is_dir = src.endswith("/")

            # conflict resolution on local target
            while os.path.exists(local_dst):
                if policy is None:
                    action = self._resolve_conflict(
                        local_dst,
                        src=src_clean,
                        source_is_local=False,
                        target_is_local=True,
                    )
                    if action.endswith("_all"):
                        policy = action.replace("_all", "")
                    action_simple = action.replace("_all", "")
                else:
                    action_simple = policy

                if action_simple == "cancel":
                    return False
                if action_simple == "skip":
                    local_dst = None
                    break
                if action_simple == "rename":
                    new_dst = self._prompt_rename(target_dir, name)
                    if not new_dst:
                        local_dst = None
                        break
                    local_dst = new_dst
                    continue
                if action_simple == "overwrite":
                    if not (is_dir and os.path.isdir(local_dst)):
                        plan.append(_PlannedOp(op="delete_local", src="", dst=local_dst, recursive=is_dir))
                    break
                if action_simple == "resume":
                    break

            if not local_dst:
                continue

            if not is_dir:
                plan.append(_PlannedOp(op="download", src=src_clean, dst=local_dst))
            else:
                plan.append(_PlannedOp(op="download_tree", src=src_clean, dst=local_dst))

        if not plan:
            return True
        ok = self._run_plan_with_progress(
            plan,
            "İndiriliyor...",
            after_finished=lambda: self._finish_local_download_mutation(
                target_dir,
                after_finished,
            ),
        )
        return ok

    def _apply_local_upload(self, local_paths: List[str], dest_dir: str) -> bool:
        if not self.session or not self.session.get("files"):
            return False
        files = self.session["files"]

        dest_dir = (dest_dir or "/").strip()
        if not dest_dir.startswith("/"):
            dest_dir = "/" + dest_dir
        dest_dir = dest_dir.rstrip("/") or "/"

        plan: List[_PlannedOp] = []
        policy: Optional[str] = None

        seen_sources: set[str] = set()
        for lp in local_paths:
            if not lp:
                continue
            lp = os.path.abspath(lp)
            if lp in seen_sources:
                continue
            seen_sources.add(lp)
            name = os.path.basename(lp.rstrip(os.sep))
            rp_base = dest_dir.rstrip("/") + "/" + name
            is_dir = os.path.isdir(lp)

            # conflict resolution on remote target
            while True:
                try:
                    exists = bool(files.exists(rp_base))
                except Exception:
                    exists = False

                if exists:
                    if policy is None:
                        action = self._resolve_conflict(
                            rp_base,
                            src=lp,
                            source_is_local=True,
                            target_is_local=False,
                        )
                        if action.endswith("_all"):
                            policy = action.replace("_all", "")
                        action_simple = action.replace("_all", "")
                    else:
                        action_simple = policy

                    if action_simple == "cancel":
                        return False
                    if action_simple == "skip":
                        rp_base = None
                        break
                    if action_simple == "rename":
                        new_dst = self._prompt_rename(dest_dir, name)
                        if not new_dst:
                            rp_base = None
                            break
                        rp_base = new_dst
                        continue
                    if action_simple == "overwrite":
                        try:
                            isdir_remote = bool(files.is_dir(rp_base))
                        except Exception:
                            isdir_remote = False
                        if not (is_dir and isdir_remote):
                            plan.append(_PlannedOp(op="delete", src="", dst=rp_base, recursive=isdir_remote))
                    elif action_simple == "resume":
                        pass
                break

            if not rp_base:
                continue

            if not is_dir:
                plan.append(_PlannedOp(op="upload", src=lp, dst=rp_base))
            else:
                # mkdir base
                plan.append(_PlannedOp(op="mkdir_remote", src="", dst=rp_base))
                # walk local dir
                for root, dirs, files_ls in os.walk(lp):
                    rel_root = os.path.relpath(root, lp)
                    rel_root = "" if rel_root == "." else rel_root
                    for d in dirs:
                        rdir = rp_base + ("/" + rel_root if rel_root else "") + "/" + d
                        plan.append(_PlannedOp(op="mkdir_remote", src="", dst=rdir))
                    for fn in files_ls:
                        lfile = os.path.join(root, fn)
                        rfile = rp_base + ("/" + rel_root if rel_root else "") + "/" + fn
                        while True:
                            try:
                                exists = bool(files.exists(rfile))
                            except Exception:
                                exists = False
                            if not exists:
                                break

                            if policy is None:
                                action = self._resolve_conflict(
                                    rfile,
                                    src=lfile,
                                    source_is_local=True,
                                    target_is_local=False,
                                )
                                if action.endswith("_all"):
                                    policy = action.replace("_all", "")
                                action_simple = action.replace("_all", "")
                            else:
                                action_simple = policy

                            if action_simple == "cancel":
                                return False
                            if action_simple == "skip":
                                rfile = None
                                break
                            if action_simple == "rename":
                                new_dst = self._prompt_rename(
                                    rfile.rsplit("/", 1)[0],
                                    fn,
                                )
                                if not new_dst:
                                    rfile = None
                                    break
                                rfile = new_dst
                                continue
                            if action_simple == "overwrite":
                                try:
                                    isdir_remote = bool(files.is_dir(rfile))
                                except Exception:
                                    isdir_remote = False
                                plan.append(_PlannedOp(op="delete", src="", dst=rfile, recursive=isdir_remote))
                                break
                            if action_simple == "resume":
                                break
                            break
                        if not rfile:
                            continue
                        plan.append(_PlannedOp(op="upload", src=lfile, dst=rfile))

        if not plan:
            return True

        return self._run_plan_with_progress(
            plan,
            "Yükleniyor...",
            after_finished=lambda: self._finish_remote_directory_mutation([dest_dir]),
        )

    def _template_upload_path(self) -> Path:
        return Path(__file__).resolve().parents[4] / "templates" / "extract_iso.py"

    def show_template_upload_menu(self) -> None:
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        if not self.current_dir:
            QMessageBox.warning(self, t("common.error"), t("dirs.no_directory_selected"))
            return

        menu = QMenu(self)
        act_extract_iso = menu.addAction(
            t("dirs.template_extract_iso")
        )
        chosen = menu.exec(self.btn_template_upload.mapToGlobal(self.btn_template_upload.rect().bottomLeft()))
        if chosen != act_extract_iso:
            return
        self.upload_template_file(self._template_upload_path())

    def upload_template_file(self, template_path: Path) -> bool:
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return False
        if not self.current_dir:
            QMessageBox.warning(self, t("common.error"), t("dirs.no_directory_selected"))
            return False
        if not template_path.exists():
            QMessageBox.warning(
                self,
                t("common.error"),
                t("dirs.template_missing").format(path=str(template_path)),
            )
            return False
        return self._apply_local_upload([str(template_path)], self.current_dir)

    # ---------- upload / download ----------
    def upload_files(self):
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        if not self.current_dir:
            QMessageBox.warning(self, t("common.error"), t("dirs.no_directory_selected"))
            return
        paths, _ = QFileDialog.getOpenFileNames(self, t("dirs.upload"))
        if not paths:
            return
        self._apply_local_upload(paths, self.current_dir)

    def download_selected(self, target_dir: Optional[str] = None):
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return False
        files = self.session["files"]
        tab = self.tabs.currentWidget()
        tab_key = "all"
        for k, v in self.views.items():
            if v is tab:
                tab_key = k
                break
        sel = self.selected_paths(tab_key)
        if not sel:
            QMessageBox.information(self, t("common.info"), t("dirs.no_file_selected"))
            return False
        if not target_dir:
            target_dir = QFileDialog.getExistingDirectory(
                self, t("dirs.download_selected")
            )
        if not target_dir:
            return False
        return self._apply_remote_download(sel, target_dir)

    # ---------- drag/drop apply ----------
    def _apply_drag_drop(self, src_paths: List[str], dest_dir: str, *, is_copy: bool, src_panel_id: str) -> bool:
        if not self.session or not self.session.get("files"):
            return False

        dest_dir = (dest_dir or "/").strip()
        if not dest_dir.startswith("/"):
            dest_dir = "/" + dest_dir
        dest_dir = dest_dir.rstrip("/") or "/"

        try:
            op = "copy" if is_copy else "move"
            return self._apply_copy_move_with_conflicts(op, src_paths, dest_dir)
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=str(e), exc=e, area="FILES")
            return False
