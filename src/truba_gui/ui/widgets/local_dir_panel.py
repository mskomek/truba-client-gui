from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QPoint, QMimeData, QUrl, Qt, Signal
from PySide6.QtGui import QDrag, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QPushButton,
    QStyle,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from truba_gui.core.i18n import t
from truba_gui.config.storage import (
    get_file_association,
    set_file_association,
)
from truba_gui.services.local_files import (
    list_local_entries,
    list_windows_drives,
    safe_initial_local_directory,
)
from truba_gui.services.file_clipboard import get_file_clipboard
from truba_gui.ui.widgets.remote_dir_panel import MIME_REMOTE_PATHS

LOCAL_CONTEXT_MENU_LABELS = [
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
]

_SORT_NAME_ROLE = Qt.ItemDataRole.UserRole + 10
_SORT_SIZE_ROLE = Qt.ItemDataRole.UserRole + 11
_SORT_TYPE_ROLE = Qt.ItemDataRole.UserRole + 12
_SORT_MTIME_ROLE = Qt.ItemDataRole.UserRole + 13


def _format_size(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    return f"{int(size)} {units[unit]}" if unit == 0 else f"{size:.1f} {units[unit]}"


def _natural_sort_key(value: str) -> tuple:
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", value or "")
        if part
    )


class _LocalTree(QTreeWidget):
    remotePathsDropped = Signal(list, str)

    def __init__(self, panel: "LocalDirPanel") -> None:
        super().__init__(panel)
        self._panel = panel
        self._sort_column: int | None = None
        self._sort_order = Qt.SortOrder.AscendingOrder
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.header().setSectionsClickable(True)
        self.header().setSortIndicatorShown(False)
        self.header().sectionClicked.connect(self._on_header_clicked)

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
        parent_items = [
            item for item in items if bool(item.data(0, Qt.ItemDataRole.UserRole + 2))
        ]
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
            )[self._sort_column or 0]
            value = item.data(0, role)
            if self._sort_column == 0:
                return _natural_sort_key(str(value or ""))
            if self._sort_column == 2:
                return str(value or "").casefold()
            return int(value or 0)

        self.addTopLevelItems(
            parent_items
            + sorted(folders, key=key, reverse=reverse)
            + sorted(files, key=key, reverse=reverse)
        )

    def startDrag(self, supported_actions) -> None:  # type: ignore[override]
        paths = self._panel.selected_paths()
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasFormat(MIME_REMOTE_PATHS):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasFormat(MIME_REMOTE_PATHS):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        mime = event.mimeData()
        if not mime.hasFormat(MIME_REMOTE_PATHS):
            super().dropEvent(event)
            return
        try:
            payload = json.loads(bytes(mime.data(MIME_REMOTE_PATHS)).decode("utf-8"))
            paths = [str(path) for path in payload.get("paths", []) if path]
            source = str(payload.get("src_panel_id", ""))
        except Exception:
            paths, source = [], ""
        if paths and source:
            self.remotePathsDropped.emit(paths, source)
            event.acceptProposedAction()
        else:
            event.ignore()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_C:
                if self._panel.copy_selected():
                    event.accept()
                    return
            if event.key() == Qt.Key.Key_X:
                if self._panel.cut_selected():
                    event.accept()
                    return
            if event.key() == Qt.Key.Key_V:
                if self._panel.paste_into_current_dir():
                    event.accept()
                    return
        if event.key() == Qt.Key.Key_F2 and not event.modifiers():
            if self._panel.rename_selected():
                event.accept()
                return
        super().keyPressEvent(event)


class LocalDirPanel(QWidget):
    remotePathsDropped = Signal(list, str)
    directoryChanged = Signal(str)
    selectionChanged = Signal()
    fileActivated = Signal(str)
    uploadRequested = Signal(list)
    remoteClipboardPasteRequested = Signal(list, str)

    def __init__(self, initial_directory: str = "", parent=None) -> None:
        super().__init__(parent)
        self.current_dir = safe_initial_local_directory(initial_directory)
        self._history: list[str] = []
        self._tab_dirs: dict[_LocalTree, str] = {}
        self._local_clipboard: tuple[str, list[str]] | None = None

        self.title_label = QLabel(t("ftp.local_title"))
        self.path = QLineEdit(self.current_dir)
        self.path.returnPressed.connect(self._open_path_field)
        self.btn_drives = QPushButton(t("ftp.drives"))
        self.btn_back = QPushButton(t("ftp.back"))
        self.btn_parent = QPushButton(t("ftp.parent"))
        self.btn_refresh = QPushButton(t("ftp.refresh"))
        self.btn_drives.clicked.connect(self.show_drives)
        self.btn_back.clicked.connect(self.go_back)
        self.btn_parent.clicked.connect(self.go_parent)
        self.btn_refresh.clicked.connect(self.refresh)

        controls = QHBoxLayout()
        controls.addWidget(self.btn_drives)
        controls.addWidget(self.btn_back)
        controls.addWidget(self.btn_parent)
        controls.addWidget(self.btn_refresh)

        self.tabs = QTabWidget()
        self.tree = self._make_tree()
        self._tab_dirs[self.tree] = self.current_dir
        self.tabs.addTab(self.tree, self._tab_label(self.current_dir))
        self.tabs.currentChanged.connect(self._on_tab_changed)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addLayout(controls)
        layout.addWidget(self.path)
        layout.addWidget(self.tabs)
        self.retranslate_ui()
        self.refresh()

    def _make_tree(self) -> _LocalTree:
        tree = _LocalTree(self)
        tree.setColumnCount(4)
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.itemDoubleClicked.connect(self._open_item)
        tree.itemSelectionChanged.connect(self.selectionChanged)
        tree.remotePathsDropped.connect(self.remotePathsDropped)
        tree.customContextMenuRequested.connect(self._on_context_menu)
        return tree

    @staticmethod
    def _tab_label(directory: str) -> str:
        name = Path(directory).name
        return name or directory or "Local"

    def _on_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if isinstance(widget, _LocalTree):
            self.tree = widget
            self.current_dir = self._tab_dirs.get(widget, self.current_dir)
            self.path.setText(self.current_dir)
            self.refresh()

    def open_directory_in_new_tab(self, directory: str) -> bool:
        target = os.path.abspath(os.path.expanduser(directory or ""))
        if not os.path.isdir(target):
            return False
        tree = self._make_tree()
        self._tab_dirs[tree] = target
        index = self.tabs.addTab(tree, self._tab_label(target))
        self.tabs.setCurrentIndex(index)
        return True

    def retranslate_ui(self) -> None:
        self.title_label.setText(t("ftp.local_title"))
        self.btn_drives.setText(t("ftp.drives"))
        self.btn_back.setText(t("ftp.back"))
        self.btn_parent.setText(t("ftp.parent"))
        self.btn_refresh.setText(t("ftp.refresh"))
        self.tree.setHeaderLabels(
            [
                t("dirs.col_name"),
                t("dirs.col_size"),
                t("dirs.col_type"),
                t("dirs.col_mtime"),
            ]
        )
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, _LocalTree):
                widget.setHeaderLabels(
                    [
                        t("dirs.col_name"),
                        t("dirs.col_size"),
                        t("dirs.col_type"),
                        t("dirs.col_mtime"),
                    ]
                )
                self.tabs.setTabText(index, self._tab_label(self._tab_dirs.get(widget, "")))

    def _open_path_field(self) -> None:
        self.set_dir(self.path.text())

    def _open_item(self, item: QTreeWidgetItem, _column: int) -> None:
        if bool(item.data(0, Qt.ItemDataRole.UserRole + 1)):
            self.set_dir(str(item.data(0, Qt.ItemDataRole.UserRole)))
            return
        path = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if path:
            self.fileActivated.emit(path)

    def _selected_items(self) -> list[QTreeWidgetItem]:
        return [
            item
            for item in self.tree.selectedItems()
            if item.data(0, Qt.ItemDataRole.UserRole)
            and not bool(item.data(0, Qt.ItemDataRole.UserRole + 2))
        ]

    def _add_entry(
        self,
        name: str,
        path: str,
        is_dir: bool,
        size: int,
        mtime: int,
        *,
        is_parent: bool = False,
    ) -> None:
        item = QTreeWidgetItem()
        item.setText(0, name)
        item.setIcon(
            0,
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_DirIcon
                if is_dir
                else QStyle.StandardPixmap.SP_FileIcon
            ),
        )
        item.setText(1, "" if is_dir else _format_size(size))
        file_type = t("dirs.type_folder") if is_dir else (Path(name).suffix[1:].upper() or t("ftp.file"))
        item.setText(2, file_type)
        item.setText(
            3,
            datetime.datetime.fromtimestamp(mtime).strftime("%d-%m-%y %H:%M")
            if mtime
            else "",
        )
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, is_dir)
        item.setData(0, Qt.ItemDataRole.UserRole + 2, is_parent)
        item.setData(0, _SORT_NAME_ROLE, name)
        item.setData(0, _SORT_SIZE_ROLE, int(size or 0))
        item.setData(0, _SORT_TYPE_ROLE, file_type)
        item.setData(0, _SORT_MTIME_ROLE, int(mtime or 0))
        self.tree.addTopLevelItem(item)

    def set_dir(self, directory: str, *, remember: bool = True) -> bool:
        target = os.path.abspath(os.path.expanduser(directory or ""))
        if not os.path.isdir(target):
            QMessageBox.warning(self, t("common.error"), t("ftp.invalid_local_path").format(path=target))
            self.path.setText(self.current_dir)
            return False
        if remember and self.current_dir and target != self.current_dir:
            self._history.append(self.current_dir)
        self.current_dir = target
        self._tab_dirs[self.tree] = target
        self.tabs.setTabText(self.tabs.currentIndex(), self._tab_label(target))
        self.path.setText(target)
        self.refresh()
        self.directoryChanged.emit(target)
        return True

    def show_drives(self) -> None:
        self.tree.clear()
        self.path.setText(t("ftp.drives"))
        for entry in list_windows_drives():
            self._add_entry(entry.name, entry.path, True, 0, 0)
        self.tree.apply_sort()

    def go_back(self) -> None:
        if self._history:
            self.set_dir(self._history.pop(), remember=False)

    def go_parent(self) -> None:
        parent = str(Path(self.current_dir).parent)
        if parent != self.current_dir:
            self.set_dir(parent)

    def refresh(self) -> None:
        self.tree.clear()
        try:
            entries = list_local_entries(self.current_dir)
        except (OSError, PermissionError) as exc:
            QMessageBox.warning(self, t("common.error"), t("ftp.local_read_failed").format(error=exc))
            return
        self.path.setText(self.current_dir)
        parent = str(Path(self.current_dir).parent)
        if parent and parent != self.current_dir:
            self._add_entry("..", parent, True, 0, 0, is_parent=True)
        for entry in entries:
            self._add_entry(entry.name, entry.path, entry.is_dir, entry.size, entry.mtime)
        self.tree.apply_sort()

    def selected_paths(self) -> list[str]:
        return [
            str(item.data(0, Qt.ItemDataRole.UserRole))
            for item in self._selected_items()
        ]

    def _set_system_file_clipboard(self, paths: list[str]) -> None:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        QApplication.clipboard().setMimeData(mime)

    def copy_selected(self) -> bool:
        paths = self.selected_paths()
        if not paths:
            return False
        self._local_clipboard = ("copy", paths)
        self._set_system_file_clipboard(paths)
        return True

    def cut_selected(self) -> bool:
        paths = self.selected_paths()
        if not paths:
            return False
        self._local_clipboard = ("move", paths)
        self._set_system_file_clipboard(paths)
        return True

    @staticmethod
    def _unique_destination(target: Path) -> Path:
        if not target.exists():
            return target
        stem = target.stem
        suffix = target.suffix
        parent = target.parent
        for index in range(1, 1000):
            candidate = parent / f"{stem} ({index}){suffix}"
            if not candidate.exists():
                return candidate
        return parent / f"{stem} copy{suffix}"

    def paste_into_current_dir(self) -> bool:
        remote_clip = get_file_clipboard().get()
        if remote_clip and remote_clip.paths:
            self.remoteClipboardPasteRequested.emit(
                list(remote_clip.paths),
                self.current_dir,
            )
            return True

        if not self._local_clipboard:
            return False
        op, paths = self._local_clipboard
        target_dir = Path(self.current_dir)
        if not target_dir.is_dir():
            return False

        changed = False
        for source_text in paths:
            source = Path(source_text)
            if not source.exists():
                continue
            if source.parent == target_dir and op == "move":
                continue
            destination = self._unique_destination(target_dir / source.name)
            try:
                if op == "move":
                    shutil.move(str(source), str(destination))
                elif source.is_dir():
                    shutil.copytree(source, destination)
                else:
                    shutil.copy2(source, destination)
            except OSError as exc:
                QMessageBox.warning(self, t("common.error"), str(exc))
                return changed
            changed = True
        if changed:
            if op == "move":
                self._local_clipboard = None
            self.refresh()
        return changed

    def open_selected_in_file_explorer(self) -> bool:
        selected = self._selected_items()
        if len(selected) == 1:
            path = Path(str(selected[0].data(0, Qt.ItemDataRole.UserRole)))
            target = path if path.is_dir() else path.parent
        else:
            target = Path(self.current_dir)
        if not target.exists():
            return False
        if os.name == "nt":
            subprocess.Popen(["explorer", str(target)])
        else:
            QApplication.instance()
            QUrl.fromLocalFile(str(target))
        return True

    def create_directory(self, *, enter: bool = False) -> bool:
        name, ok = QInputDialog.getText(
            self,
            t("dirs.new_folder") if t("dirs.new_folder") != "[dirs.new_folder]" else "Yeni Klasör",
            t("dirs.new_folder_label") if t("dirs.new_folder_label") != "[dirs.new_folder_label]" else "Klasör adı:",
        )
        if not ok or not name.strip():
            return False
        target = Path(self.current_dir, name.strip())
        try:
            target.mkdir()
        except OSError as exc:
            QMessageBox.warning(self, t("common.error"), str(exc))
            return False
        if enter:
            return self.set_dir(str(target))
        self.refresh()
        return True

    def delete_selected(self) -> bool:
        paths = [Path(path) for path in self.selected_paths()]
        if not paths:
            return False
        if QMessageBox.question(self, t("common.confirm"), t("dirs.delete_confirm")) != QMessageBox.StandardButton.Yes:
            return False
        for path in paths:
            try:
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
            except OSError as exc:
                QMessageBox.warning(self, t("common.error"), str(exc))
                return False
        self.refresh()
        return True

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item is not None and not item.isSelected():
            self.tree.clearSelection()
            item.setSelected(True)
        paths = self.selected_paths()
        one_selected = len(paths) == 1
        one_is_dir = one_selected and Path(paths[0]).is_dir()

        menu = QMenu(self)
        act_upload = menu.addAction(LOCAL_CONTEXT_MENU_LABELS[0])
        act_add_queue = menu.addAction(LOCAL_CONTEXT_MENU_LABELS[1])
        act_add_queue.setEnabled(False)
        menu.addSeparator()
        act_open = menu.addAction(LOCAL_CONTEXT_MENU_LABELS[3])
        act_open_with = menu.addAction(t("files.open_with"))
        act_open_new_tab = menu.addAction(LOCAL_CONTEXT_MENU_LABELS[5])
        act_edit = menu.addAction(LOCAL_CONTEXT_MENU_LABELS[6])
        act_edit.setEnabled(False)
        menu.addSeparator()
        act_create_dir = menu.addAction(LOCAL_CONTEXT_MENU_LABELS[8])
        act_create_dir_enter = menu.addAction(LOCAL_CONTEXT_MENU_LABELS[9])
        act_refresh = menu.addAction(LOCAL_CONTEXT_MENU_LABELS[10])
        menu.addSeparator()
        act_delete = menu.addAction(LOCAL_CONTEXT_MENU_LABELS[12])
        act_rename = menu.addAction(LOCAL_CONTEXT_MENU_LABELS[13])

        act_upload.setEnabled(bool(paths))
        act_open.setEnabled(not paths or one_selected)
        act_open_with.setEnabled(one_selected and not one_is_dir)
        act_open_new_tab.setEnabled(one_is_dir)
        act_create_dir_enter.setEnabled(bool(self.current_dir))
        act_delete.setEnabled(bool(paths))
        act_rename.setEnabled(one_selected)
        if one_selected and item is not None and bool(item.data(0, Qt.ItemDataRole.UserRole + 2)):
            act_upload.setEnabled(False)
            act_open.setEnabled(True)
            act_open_with.setEnabled(False)
            act_open_new_tab.setEnabled(False)
            act_delete.setEnabled(False)
            act_rename.setEnabled(False)

        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if not chosen:
            return
        if chosen == act_upload:
            self.uploadRequested.emit(paths)
            return
        if chosen == act_open:
            self.open_selected_in_file_explorer()
            return
        if chosen == act_open_with:
            self.open_selected_with_program()
            return
        if chosen == act_open_new_tab and one_is_dir:
            self.open_directory_in_new_tab(paths[0])
            return
        if chosen == act_create_dir:
            self.create_directory(enter=False)
            return
        if chosen == act_create_dir_enter:
            self.create_directory(enter=True)
            return
        if chosen == act_refresh:
            self.refresh()
            return
        if chosen == act_delete:
            self.delete_selected()
            return
        if chosen == act_rename:
            self.rename_selected()
            return

    def rename_selected(self) -> bool:
        selected = self._selected_items()
        if len(selected) != 1:
            return False
        old = Path(str(selected[0].data(0, Qt.ItemDataRole.UserRole)))
        new_name, ok = QInputDialog.getText(
            self,
            t("dirs.rename") if t("dirs.rename") != "[dirs.rename]" else "Yeniden Adlandır",
            t("dirs.rename_label"),
            text=old.name,
        )
        if not ok or not new_name.strip():
            return False
        target = old.with_name(new_name.strip())
        try:
            old.rename(target)
        except OSError as exc:
            QMessageBox.warning(self, t("common.error"), str(exc))
            return False
        self.refresh()
        return True

    def open_selected_with_program(self) -> bool:
        selected = self._selected_items()
        if len(selected) != 1:
            return False
        target = Path(str(selected[0].data(0, Qt.ItemDataRole.UserRole)))
        if not target.is_file():
            return False
        program = get_file_association(target.suffix)
        if not program or not Path(program).exists():
            program, _ = QFileDialog.getOpenFileName(
                self,
                t("files.open_with_select_program"),
                "",
                t("files.open_with_program_filter"),
            )
            program = str(program or "").strip()
            if not program:
                return False
            if target.suffix:
                answer = QMessageBox.question(
                    self,
                    t("files.open_with_save_title"),
                    t("files.open_with_save_prompt").format(
                        extension=target.suffix.lower()
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    set_file_association(target.suffix, program)
        try:
            subprocess.Popen([program, str(target)])
        except OSError as exc:
            QMessageBox.warning(self, t("common.error"), str(exc))
            return False
        return True
