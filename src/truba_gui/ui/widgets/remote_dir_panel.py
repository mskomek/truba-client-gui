from __future__ import annotations

import datetime
import json
import os
import shutil
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QPoint, Qt, Signal, QObject, QThread, Slot
from PySide6.QtGui import QDrag, QIcon, QKeyEvent
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QCheckBox,
    QGroupBox,
    QListWidget,
    QProgressDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from truba_gui.core.i18n import t
from truba_gui.services.file_clipboard import get_file_clipboard
from truba_gui.services.files_base import RemoteEntry


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
        return t("dirs.type_folder") if t("dirs.type_folder") != "[dirs.type_folder]" else "Klasör"
    lower = name.lower()
    if lower.endswith(".iso"):
        return "Disc Image File"
    if lower.endswith((".zip", ".rar", ".7z")):
        return "WinRAR ZIP archive"
    if lower.endswith((".tgz", ".tar.gz", ".tar")):
        return "TAR archive"
    if "." in name:
        return name.split(".")[-1].upper() + " File"
    return "File"


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

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

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
        if md.hasUrls() and any(u.isLocalFile() for u in md.urls()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):  # type: ignore[override]
        md = event.mimeData()
        if md.hasFormat(MIME_REMOTE_PATHS):
            event.acceptProposedAction()
            return
        if md.hasUrls() and any(u.isLocalFile() for u in md.urls()):
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
        if md.hasUrls() and any(u.isLocalFile() for u in md.urls()):
            dest_dir = self._panel.current_dir or "/"
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                clicked_path = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
                clicked_is_dir = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
                if clicked_path and clicked_is_dir:
                    dest_dir = clicked_path.rstrip("/")
            local_paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            ok = self._panel._apply_local_upload(local_paths, dest_dir)
            if ok:
                event.acceptProposedAction()
            else:
                event.ignore()
            return

        return super().dropEvent(event)


class RemoteDirPanel(QWidget):
    open_file = Signal(str)  # remote path (double click)
    open_in_slot = Signal(int, str)  # slot_index(0/1), remote path

    # registry to refresh source/target panels on move
    _instances: Dict[str, "RemoteDirPanel"] = {}

    # single-level undo (last operation)
    _last_undo: Optional[_UndoRecord] = None

    def __init__(self, title: str = ""):
        super().__init__()
        self.session = None
        self.enable_output_menu = False  # JobsOutputsWidget can turn this on
        self.current_dir = ""
        self.title = title

        self.panel_id = str(id(self))
        RemoteDirPanel._instances[self.panel_id] = self

        self.lbl = QLabel(title)
        self.path = QLineEdit()
        self.path.setReadOnly(True)

        self.btn_upload = QPushButton(t("dirs.upload") if t("dirs.upload") != "[dirs.upload]" else "Yükle")
        self.btn_upload.clicked.connect(self.upload_files)

        self.btn_download = QPushButton(
            t("dirs.download_selected") if t("dirs.download_selected") != "[dirs.download_selected]" else "Seçilenleri İndir"
        )
        self.btn_download.clicked.connect(self.download_selected)

        self.btn_delete = QPushButton(t("dirs.delete") if t("dirs.delete") != "[dirs.delete]" else "Sil")
        self.btn_delete.clicked.connect(self.delete_selected)

        self.btn_undo = QPushButton(t("dirs.undo") if t("dirs.undo") != "[dirs.undo]" else "Geri Al")
        self.btn_undo.clicked.connect(self.undo_last)

        self.btn_refresh = QPushButton(t("dirs.refresh") if t("dirs.refresh") != "[dirs.refresh]" else "Yenile")
        self.btn_refresh.clicked.connect(self.refresh)

        top = QHBoxLayout()
        top.addWidget(self.lbl)
        top.addStretch(1)
        top.addWidget(self.btn_upload)
        top.addWidget(self.btn_download)
        top.addWidget(self.btn_delete)
        top.addWidget(self.btn_undo)
        top.addWidget(self.btn_refresh)

        self.tabs = QTabWidget()
        self.views: Dict[str, _RemoteTree] = {
            "all": self._make_view(),
            "folders": self._make_view(),
            "iso": self._make_view(),
            "archives": self._make_view(),
            "slurm": self._make_view(),
            "other": self._make_view(),
        }
        self.tabs.addTab(self.views["all"], t("dirs.tab_all") if t("dirs.tab_all") != "[dirs.tab_all]" else "Tümü")
        self.tabs.addTab(self.views["folders"], t("dirs.tab_folders") if t("dirs.tab_folders") != "[dirs.tab_folders]" else "Klasörler")
        self.tabs.addTab(self.views["iso"], t("dirs.tab_iso") if t("dirs.tab_iso") != "[dirs.tab_iso]" else "ISO")
        self.tabs.addTab(
            self.views["archives"], t("dirs.tab_archives") if t("dirs.tab_archives") != "[dirs.tab_archives]" else "Arşivler"
        )
        self.tabs.addTab(self.views["slurm"], t("dirs.tab_slurm") if t("dirs.tab_slurm") != "[dirs.tab_slurm]" else "Slurm")
        self.tabs.addTab(self.views["other"], t("dirs.tab_other") if t("dirs.tab_other") != "[dirs.tab_other]" else "Diğer")

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(QLabel(t("dirs.path") if t("dirs.path") != "[dirs.path]" else "Dizin:"))
        lay.addWidget(self.path)
        lay.addWidget(self.tabs)

        # Transfer queue (batch view)
        self.queue_group = QGroupBox(t("dirs.queue_title") if t("dirs.queue_title") != "[dirs.queue_title]" else "İşlem Kuyruğu")
        qlay = QVBoxLayout(self.queue_group)
        self.queue_current = QLabel("-")
        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(80)
        qlay.addWidget(QLabel(t("dirs.queue_current") if t("dirs.queue_current") != "[dirs.queue_current]" else "Şu an:"))

        # ---- active batch tracking (for graceful shutdown / diagnostics)
        self._active_thread: Optional[QThread] = None
        self._active_worker: Optional[_FileOpWorker] = None
        self._active_plan: List[_PlannedOp] = []
        self._active_step: int = 0
        self._active_title: str = ""
        qlay.addWidget(self.queue_current)
        qlay.addWidget(QLabel(t("dirs.queue_next") if t("dirs.queue_next") != "[dirs.queue_next]" else "Sıradaki:"))
        qlay.addWidget(self.queue_list)
        self.queue_group.setVisible(False)
        lay.addWidget(self.queue_group)

        self._update_undo_enabled()

    def _make_view(self) -> _RemoteTree:
        w = _RemoteTree(panel=self)
        w.setColumnCount(4)
        w.setHeaderLabels(
            [
                t("dirs.col_name") if t("dirs.col_name") != "[dirs.col_name]" else "Filename",
                t("dirs.col_size") if t("dirs.col_size") != "[dirs.col_size]" else "Filesize",
                t("dirs.col_type") if t("dirs.col_type") != "[dirs.col_type]" else "Filetype",
                t("dirs.col_mtime") if t("dirs.col_mtime") != "[dirs.col_mtime]" else "Last modified",
            ]
        )
        w.setRootIsDecorated(False)
        w.setAlternatingRowColors(True)
        w.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        w.itemDoubleClicked.connect(lambda item, col: self.open_file.emit(str(item.data(0, Qt.ItemDataRole.UserRole) or "")))
        w.header().setStretchLastSection(True)
        w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        w.customContextMenuRequested.connect(lambda pos, view=w: self._on_context_menu(view, pos))
        w.installEventFilter(self)
        return w

    def eventFilter(self, watched, event):
        # Delete / Paste / Undo key support on directory views
        if isinstance(watched, QTreeWidget) and event.type() == QEvent.Type.KeyPress:
            e: QKeyEvent = event  # type: ignore
            if e.key() == Qt.Key.Key_Delete:
                self.delete_selected()
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

    def set_dir(self, remote_dir: str):
        self.current_dir = remote_dir
        self.path.setText(remote_dir)
        self.refresh()

    def _icon_for(self, entry: RemoteEntry) -> QIcon:
        st = self.style()
        if entry.is_dir:
            return st.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        lower = entry.name.lower()
        if lower.endswith(".iso"):
            return st.standardIcon(QStyle.StandardPixmap.SP_DriveDVDIcon)
        return st.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def refresh(self):
        if not self.session or not self.session.get("files"):
            for v in self.views.values():
                v.clear()
            return

        files = self.session["files"]
        try:
            entries = files.listdir_entries(self.current_dir)
        except Exception as e:
            self._show_op_error(
                f"{t('dirs.load_failed') if t('dirs.load_failed') != '[dirs.load_failed]' else 'Dizin okunamadı'}: {e}"
            )
            for v in self.views.values():
                v.clear()
            return

        for v in self.views.values():
            v.clear()

        def add(view: QTreeWidget, entry: RemoteEntry):
            it = QTreeWidgetItem()
            it.setText(0, entry.name)
            it.setIcon(0, self._icon_for(entry))
            it.setText(1, "" if entry.is_dir else _fmt_size(entry.size))
            it.setText(2, _file_type(entry.name, entry.is_dir))
            it.setText(3, _fmt_mtime(entry.mtime))
            it.setData(0, Qt.ItemDataRole.UserRole, entry.path)
            it.setData(0, Qt.ItemDataRole.UserRole + 1, bool(entry.is_dir))
            view.addTopLevelItem(it)

        for e in entries:
            add(self.views["all"], e)
            cat = _category(e)
            if cat in self.views:
                add(self.views[cat], e)

        for v in self.views.values():
            v.resizeColumnToContents(0)
            v.resizeColumnToContents(1)
            v.resizeColumnToContents(2)
            v.resizeColumnToContents(3)

        self._update_undo_enabled()

    # ---------- selection helpers ----------
    def _selected_paths_from_view(self, view: QTreeWidget) -> List[str]:
        paths: List[str] = []
        for it in view.selectedItems():
            p = it.data(0, Qt.ItemDataRole.UserRole)
            if p:
                paths.append(str(p))
        return paths

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

        # build undo plan (dst -> src)
        plan: List[_PlannedOp] = []
        policy: Optional[str] = None

        for src, dst in moves:
            # undo means: move dst back to src
            undo_src = dst.rstrip("/")
            undo_dst = src.rstrip("/")

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
                    action = self._resolve_conflict(undo_dst)
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

        ok = self._run_plan_with_progress(plan, "Geri alınıyor...")
        if not ok:
            return

        self._set_last_undo(None)
        # refresh all panels
        for p in list(RemoteDirPanel._instances.values()):
            try:
                p.refresh()
            except Exception:
                pass

    # ---------- context menu ----------
    def _on_context_menu(self, view: QTreeWidget, pos: QPoint):
        if not self.session or not self.session.get("files"):
            return

        files = self.session.get("files")
        clipboard = get_file_clipboard()

        item = view.itemAt(pos)
        clicked_path: Optional[str] = None
        clicked_is_dir = False
        if item is not None:
            clicked_path = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            clicked_is_dir = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))

        sel_paths = self._selected_paths_from_view(view)
        if not sel_paths and clicked_path:
            sel_paths = [clicked_path]

        menu = QMenu(self)

        # Undo
        act_undo = None
        if RemoteDirPanel._last_undo is not None:
            act_undo = menu.addAction(t("dirs.undo") if t("dirs.undo") != "[dirs.undo]" else "Geri Al")
            menu.addSeparator()

        # Optional output open actions (JobsOutputsWidget)
        if self.enable_output_menu and clicked_path:
            menu.addAction(t("jobs_outputs.open_out1") if t("jobs_outputs.open_out1") != "[jobs_outputs.open_out1]" else "Çıktı-1'de Aç")
            menu.addAction(t("jobs_outputs.open_out2") if t("jobs_outputs.open_out2") != "[jobs_outputs.open_out2]" else "Çıktı-2'de Aç")
            menu.addSeparator()

        # Paste actions
        sys_clip = QApplication.clipboard().mimeData()
        has_local_urls = bool(sys_clip and sys_clip.hasUrls() and any(u.isLocalFile() for u in sys_clip.urls()))

        clip = clipboard.get()
        act_paste_here = None
        act_paste_into = None
        act_paste_to_local = None
        act_paste_local_here = None
        act_paste_local_into = None

        # Local -> Remote paste (from OS clipboard)
        if has_local_urls:
            act_paste_local_here = menu.addAction("Yerelden Yapıştır")
            if clicked_path and clicked_is_dir:
                act_paste_local_into = menu.addAction("Yerelden klasöre yapıştır")
            menu.addSeparator()

        # Remote -> Remote paste (internal clipboard)
        if clip and clip.paths:
            act_paste_here = menu.addAction(t("dirs.paste") if t("dirs.paste") != "[dirs.paste]" else "Yapıştır")
            if clicked_path and clicked_is_dir:
                act_paste_into = menu.addAction(t("dirs.paste_into") if t("dirs.paste_into") != "[dirs.paste_into]" else "Klasöre Yapıştır")
            # Remote -> Local paste (download to a chosen local folder)
            act_paste_to_local = menu.addAction("Yerel'e Yapıştır")
            menu.addSeparator()
        act_edit = act_download = act_rename = act_copy = act_move = act_delete = None
        if sel_paths:
            act_edit = menu.addAction(t("dirs.edit") if t("dirs.edit") != "[dirs.edit]" else "Düzenle")
            act_download = menu.addAction(t("dirs.download") if t("dirs.download") != "[dirs.download]" else "İndir")
            menu.addSeparator()
            act_rename = menu.addAction(t("dirs.rename") if t("dirs.rename") != "[dirs.rename]" else "Yeniden Adlandır")
            act_copy = menu.addAction(t("dirs.copy") if t("dirs.copy") != "[dirs.copy]" else "Kopyala")
            act_move = menu.addAction(t("dirs.move") if t("dirs.move") != "[dirs.move]" else "Taşı")
            menu.addSeparator()
            act_delete = menu.addAction(t("dirs.delete") if t("dirs.delete") != "[dirs.delete]" else "Sil")
            if len(sel_paths) != 1:
                act_edit.setEnabled(False)  # type: ignore[union-attr]
                act_rename.setEnabled(False)  # type: ignore[union-attr]

        chosen = menu.exec(view.viewport().mapToGlobal(pos))
        if not chosen:
            return

        if act_undo is not None and chosen == act_undo:
            self.undo_last()
            return

        # Output actions
        if self.enable_output_menu and clicked_path:
            if chosen.text() == (t("jobs_outputs.open_out1") if t("jobs_outputs.open_out1") != "[jobs_outputs.open_out1]" else "Çıktı-1'de Aç"):
                self.open_in_slot.emit(0, clicked_path)
                return
            if chosen.text() == (t("jobs_outputs.open_out2") if t("jobs_outputs.open_out2") != "[jobs_outputs.open_out2]" else "Çıktı-2'de Aç"):
                self.open_in_slot.emit(1, clicked_path)
                return

        # Paste (Local -> Remote)
        if act_paste_local_here is not None and chosen == act_paste_local_here:
            self._paste_system_clipboard_into(self.current_dir or "/")
            return
        if act_paste_local_into is not None and chosen == act_paste_local_into and clicked_path:
            self._paste_system_clipboard_into(clicked_path)
            return

        # Paste (Remote -> Remote)
        if act_paste_here is not None and chosen == act_paste_here:
            self._paste_remote_clipboard_into(self.current_dir or "/")
            return
        if act_paste_into is not None and chosen == act_paste_into and clicked_path:
            self._paste_remote_clipboard_into(clicked_path)
            return

        # Paste (Remote -> Local)
        if act_paste_to_local is not None and chosen == act_paste_to_local:
            self._paste_remote_to_local()
            return

        if not sel_paths:
            return

        # Edit
        if act_edit is not None and chosen == act_edit:
            rp = sel_paths[0]
            try:
                files.listdir(rp.rstrip("/"))
                QMessageBox.information(self, t("common.info"), "Klasör düzenlenemez.")
                return
            except Exception:
                pass
            self.open_file.emit(rp)
            return

        # Download
        if act_download is not None and chosen == act_download:
            self.download_selected()
            return

        # Delete
        if act_delete is not None and chosen == act_delete:
            self._delete_paths(sel_paths)
            return

        # Rename
        if act_rename is not None and chosen == act_rename:
            if len(sel_paths) != 1:
                QMessageBox.information(self, t("common.info"), "Yeniden adlandırmak için tek bir öğe seçin.")
                return
            old = sel_paths[0]
            base = old.rstrip("/").split("/")[-1]
            new_name, ok = QInputDialog.getText(
                self,
                t("dirs.rename") if t("dirs.rename") != "[dirs.rename]" else "Yeniden Adlandır",
                "Yeni ad:",
                text=base,
            )
            if not ok or not new_name.strip():
                return
            parent = "/".join(old.rstrip("/").split("/")[:-1]) or "/"
            dst = parent.rstrip("/") + "/" + new_name.strip()
            try:
                files.rename(old.rstrip("/"), dst)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, t("common.error"), str(e))
            return

        # Copy/Move into clipboard
        if act_copy is not None and chosen == act_copy:
            clipboard.set("copy", sel_paths)
            return
        if act_move is not None and chosen == act_move:
            clipboard.set("move", sel_paths)
            return

    # ---------- delete / paste ----------
    def _delete_paths(self, paths: List[str]) -> None:
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        files = self.session["files"]
        if not paths:
            return
        msg = "Seçilen öğeler silinsin mi?\n" + "\n".join([p.split("/")[-1] for p in paths[:10]])
        if len(paths) > 10:
            msg += f"\n... (+{len(paths)-10})"
        if QMessageBox.question(
            self,
            t("common.confirm") if t("common.confirm") != "[common.confirm]" else "Onay",
            msg,
        ) != QMessageBox.StandardButton.Yes:
            return
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
        self.refresh()

    def delete_selected(self):
        tab = self.tabs.currentWidget()
        tab_key = "all"
        for k, v in self.views.items():
            if v is tab:
                tab_key = k
                break
        sel = self.selected_paths(tab_key)
        if not sel:
            QMessageBox.information(self, t("common.info"), "Dosya seçilmedi.")
            return
        self._delete_paths(sel)

    # ---------- conflict dialogs ----------
    def _resolve_conflict(self, dst: str):
        """Return one of: overwrite|skip|rename|cancel (optionally applied to all)."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(t("common.confirm"))
        box.setText(f"Hedefte zaten var:\n{dst}\n\nNe yapmak istiyorsun?")
        overwrite_btn = box.addButton("Üzerine yaz", QMessageBox.ButtonRole.AcceptRole)
        skip_btn = box.addButton("Atla", QMessageBox.ButtonRole.DestructiveRole)
        rename_btn = box.addButton("Yeniden adlandır", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(overwrite_btn)

        cb = QCheckBox("Tüm çakışmalara uygula")
        box.setCheckBox(cb)

        box.exec()
        clicked = box.clickedButton()
        apply_all = bool(cb.isChecked())

        def _ret(x: str) -> str:
            return x + "_all" if apply_all else x

        if clicked == cancel_btn:
            return _ret("cancel")
        if clicked == overwrite_btn:
            return _ret("overwrite")
        if clicked == skip_btn:
            return _ret("skip")
        if clicked == rename_btn:
            return _ret("rename")
        return _ret("cancel")

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

    def _persist_batch_state(self, remaining: List[_PlannedOp], *, title: str) -> None:
        """Persist remaining batch ops for crash-safe diagnostics.

        This does **not** auto-resume (no new behavior for the user). It only
        stores a small JSON snapshot under ~/.truba_slurm_gui.
        """
        try:
            from pathlib import Path
            import json
            import time

            d = Path.home() / ".truba_slurm_gui"
            d.mkdir(parents=True, exist_ok=True)
            path = d / "last_batch.json"
            payload = {
                "ts": int(time.time()),
                "title": title,
                "panel_title": self.title,
                "cwd": self.current_dir,
                "remaining": [
                    {"op": op.op, "src": op.src, "dst": op.dst, "recursive": bool(op.recursive)}
                    for op in remaining
                ],
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def shutdown(self) -> None:
        """Cancel in-flight batch operations (best-effort, non-blocking)."""
        try:
            if self._active_worker is not None:
                try:
                    self._active_worker.cancel()
                except Exception:
                    pass

                # Save remaining plan snapshot (diagnostics only)
                try:
                    if self._active_plan:
                        remaining = self._active_plan[max(0, self._active_step - 1):]
                        if remaining:
                            self._persist_batch_state(remaining, title=self._active_title or "batch")
                except Exception:
                    pass

            if self._active_thread is not None:
                try:
                    self._active_thread.quit()
                    self._active_thread.wait(500)
                except Exception:
                    pass
        except Exception:
            pass

    # ---------- plan runner ----------
    def _run_plan_with_progress(self, plan: List[_PlannedOp], title: str) -> bool:
        if not self.session or not self.session.get("files"):
            return False
        if not plan:
            return True

        # Show batch queue view
        self._queue_set(plan)

        dlg = QProgressDialog(title, "İptal", 0, len(plan), self)
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(True)
        dlg.setAutoReset(True)
        dlg.setValue(0)

        # Track active batch for graceful shutdown.
        self._active_plan = list(plan)
        self._active_step = 0
        self._active_title = title

        thread = QThread(self)
        worker = _FileOpWorker(self.session["files"], plan)
        self._active_thread = thread
        self._active_worker = worker
        worker.moveToThread(thread)

        state = {"cancelled": False, "error": ""}

        def on_progress(step: int, label: str) -> None:
            # step is 1-based, emitted before executing the step.
            self._active_step = int(step)
            dlg.setLabelText(label)
            dlg.setValue(step)
            self._queue_progress(step, label)
            QApplication.processEvents()

        def on_finished(cancelled: bool, msg: str) -> None:
            state["cancelled"] = bool(cancelled)
            state["error"] = msg or ""
            dlg.setValue(len(plan))
            dlg.close()
            # Clear queue view when the batch stops (success/cancel/error)
            self._queue_clear()

            # If cancelled during shutdown, persist remaining plan for diagnostics.
            try:
                if state["cancelled"] and self._active_plan:
                    remaining = self._active_plan[max(0, self._active_step - 1):]
                    if remaining:
                        self._persist_batch_state(remaining, title=self._active_title)
            except Exception:
                pass

            # Clear active refs
            self._active_thread = None
            self._active_worker = None
            self._active_plan = []
            self._active_step = 0
            self._active_title = ""
            thread.quit()

        dlg.canceled.connect(worker.cancel)
        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        thread.started.connect(worker.run)
        thread.finished.connect(thread.deleteLater)
        thread.start()

        dlg.exec()

        thread.quit()
        thread.wait(3000)

        if state["error"]:
            self._show_op_error(state["error"])
            return False
        if state["cancelled"]:
            return False
        return True

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
                        action = self._resolve_conflict(dst)
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
                        plan.append(_PlannedOp(op="delete", src="", dst=dst, recursive=isdir))

                plan.append(_PlannedOp(op=op, src=src_clean, dst=dst, recursive=recursive))
                break

        return plan

    def _apply_copy_move_with_conflicts(self, op: str, src_paths: List[str], dest_dir: str) -> None:
        plan = self._build_copy_move_plan_with_conflicts(op, src_paths, dest_dir)
        if plan is None:
            return

        title = "İşlem yapılıyor..."
        if op == "copy":
            title = "Kopyalanıyor..."
        elif op == "move":
            title = "Taşınıyor..."

        ok = self._run_plan_with_progress(plan, title)
        if not ok:
            return

        # store undo for move only
        if op == "move":
            moves: List[Tuple[str, str]] = [(p.src, p.dst) for p in plan if p.op == "move"]
            if moves:
                self._set_last_undo(_UndoRecord(kind="move", moves=moves))

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
            self._apply_copy_move_with_conflicts(op, [s for s in clip.paths], dest_dir)
            self.refresh()
            if clip.op == "move":
                clipboard.clear()
        except Exception as e:
            QMessageBox.critical(self, t("common.error"), str(e))


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
        target_dir = QFileDialog.getExistingDirectory(self, "Yerel klasör seç")
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

    def _apply_remote_download(self, src_paths: List[str], target_dir: str) -> bool:
        if not self.session or not self.session.get("files"):
            return False
        files = self.session["files"]
        target_dir = os.path.abspath(target_dir)

        plan: List[_PlannedOp] = []
        policy: Optional[str] = None

        for src in src_paths:
            src_clean = src.rstrip("/")
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
                    action = self._resolve_conflict(local_dst)
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
                    plan.append(_PlannedOp(op="delete_local", src="", dst=local_dst, recursive=is_dir))
                    break

            if not local_dst:
                continue

            if not is_dir:
                plan.append(_PlannedOp(op="download", src=src_clean, dst=local_dst))
            else:
                # mkdir base local
                plan.append(_PlannedOp(op="mkdir_local", src="", dst=local_dst, recursive=False))
                # walk remote dir and download files
                for rpath, rel, r_is_dir in self._remote_walk(src_clean):
                    if rel == "":
                        continue
                    lp = os.path.join(local_dst, rel)
                    if r_is_dir:
                        plan.append(_PlannedOp(op="mkdir_local", src="", dst=lp))
                    else:
                        # local file overwrite within folder: best-effort overwrite
                        if os.path.exists(lp):
                            plan.append(_PlannedOp(op="delete_local", src="", dst=lp, recursive=False))
                        plan.append(_PlannedOp(op="download", src=rpath, dst=lp))

        if not plan:
            return True
        ok = self._run_plan_with_progress(plan, "İndiriliyor...")
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

        for lp in local_paths:
            lp = os.path.abspath(lp)
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
                        action = self._resolve_conflict(rp_base)
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
                        plan.append(_PlannedOp(op="delete", src="", dst=rp_base, recursive=isdir_remote))
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
                        # overwrite within uploaded dir: best-effort overwrite
                        try:
                            if files.exists(rfile):
                                try:
                                    isdir_remote = bool(files.is_dir(rfile))
                                except Exception:
                                    isdir_remote = False
                                plan.append(_PlannedOp(op="delete", src="", dst=rfile, recursive=isdir_remote))
                        except Exception:
                            pass
                        plan.append(_PlannedOp(op="upload", src=lfile, dst=rfile))

        if not plan:
            return True

        ok = self._run_plan_with_progress(plan, "Yükleniyor...")
        if ok:
            self.refresh()
        return ok

    # ---------- upload / download ----------
    def upload_files(self):
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        if not self.current_dir:
            QMessageBox.warning(self, t("common.error"), "Dizin seçili değil.")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, t("dirs.upload") if t("dirs.upload") != "[dirs.upload]" else "Yükle")
        if not paths:
            return
        files = self.session["files"]
        ok = 0
        for lp in paths:
            name = os.path.basename(lp)
            rp = self.current_dir.rstrip("/") + "/" + name
            try:
                files.upload(lp, rp)
                ok += 1
            except Exception as e:
                QMessageBox.warning(self, t("common.error"), f"Yüklenemedi: {name}\n{e}")
        if ok:
            self.refresh()

    def download_selected(self):
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        files = self.session["files"]
        tab = self.tabs.currentWidget()
        tab_key = "all"
        for k, v in self.views.items():
            if v is tab:
                tab_key = k
                break
        sel = self.selected_paths(tab_key)
        if not sel:
            QMessageBox.information(self, t("common.info"), "Dosya seçilmedi.")
            return
        target_dir = QFileDialog.getExistingDirectory(
            self, t("dirs.download_selected") if t("dirs.download_selected") != "[dirs.download_selected]" else "Seçilenleri İndir"
        )
        if not target_dir:
            return
        for rp in sel:
            name = rp.rstrip("/").split("/")[-1]
            lp = os.path.join(target_dir, name)
            try:
                files.download(rp, lp)
            except Exception as e:
                QMessageBox.warning(self, t("common.error"), f"İndirilemedi: {name}\n{e}")

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
            self._apply_copy_move_with_conflicts(op, src_paths, dest_dir)

            # refresh both panels (source + target)
            self.refresh()
            src_panel = RemoteDirPanel._instances.get(src_panel_id)
            if src_panel is not None and src_panel is not self:
                src_panel.refresh()
            return True
        except Exception as e:
            QMessageBox.critical(self, t("common.error"), str(e))
            return False
