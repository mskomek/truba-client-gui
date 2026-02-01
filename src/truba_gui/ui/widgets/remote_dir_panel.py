from __future__ import annotations

import datetime
import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLineEdit, QStyle, QMessageBox, QFileDialog, QMenu, QInputDialog
)

from truba_gui.core.i18n import t
from truba_gui.services.files_base import RemoteEntry
from truba_gui.services.file_clipboard import get_file_clipboard


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
    if lower.endswith(".zip") or lower.endswith(".rar") or lower.endswith(".7z"):
        return "WinRAR ZIP archive"
    if lower.endswith(".tgz") or lower.endswith(".tar.gz") or lower.endswith(".tar"):
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


class RemoteDirPanel(QWidget):
    open_file = Signal(str)  # remote path (double click)
    open_in_slot = Signal(int, str)  # slot_index(0/1), remote path

    def __init__(self, title: str = ""):
        super().__init__()
        self.session = None
        self.enable_output_menu = False  # JobsOutputsWidget can turn this on
        self.current_dir = ""
        self.title = title

        self.lbl = QLabel(title)
        self.path = QLineEdit()
        self.path.setReadOnly(True)

        self.btn_upload = QPushButton(t("dirs.upload") if t("dirs.upload") != "[dirs.upload]" else "Yükle")
        self.btn_upload.clicked.connect(self.upload_files)

        self.btn_download = QPushButton(t("dirs.download_selected") if t("dirs.download_selected") != "[dirs.download_selected]" else "Seçilenleri İndir")
        self.btn_download.clicked.connect(self.download_selected)

        self.btn_delete = QPushButton(t("dirs.delete") if t("dirs.delete") != "[dirs.delete]" else "Sil")
        self.btn_delete.clicked.connect(self.delete_selected)

        self.btn_refresh = QPushButton(t("dirs.refresh") if t("dirs.refresh") != "[dirs.refresh]" else "Yenile")
        self.btn_refresh.clicked.connect(self.refresh)

        top = QHBoxLayout()
        top.addWidget(self.lbl)
        top.addStretch(1)
        top.addWidget(self.btn_upload)
        top.addWidget(self.btn_download)
        top.addWidget(self.btn_delete)
        top.addWidget(self.btn_refresh)

        self.tabs = QTabWidget()
        self.views = {
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
        self.tabs.addTab(self.views["archives"], t("dirs.tab_archives") if t("dirs.tab_archives") != "[dirs.tab_archives]" else "Arşivler")
        self.tabs.addTab(self.views["slurm"], t("dirs.tab_slurm") if t("dirs.tab_slurm") != "[dirs.tab_slurm]" else "Slurm")
        self.tabs.addTab(self.views["other"], t("dirs.tab_other") if t("dirs.tab_other") != "[dirs.tab_other]" else "Diğer")

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(QLabel(t("dirs.path") if t("dirs.path") != "[dirs.path]" else "Dizin:"))
        lay.addWidget(self.path)
        lay.addWidget(self.tabs)

    def _make_view(self) -> QTreeWidget:
        w = QTreeWidget()
        w.setColumnCount(4)
        w.setHeaderLabels([
            t("dirs.col_name") if t("dirs.col_name") != "[dirs.col_name]" else "Filename",
            t("dirs.col_size") if t("dirs.col_size") != "[dirs.col_size]" else "Filesize",
            t("dirs.col_type") if t("dirs.col_type") != "[dirs.col_type]" else "Filetype",
            t("dirs.col_mtime") if t("dirs.col_mtime") != "[dirs.col_mtime]" else "Last modified",
        ])
        w.setRootIsDecorated(False)
        w.setAlternatingRowColors(True)
        w.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        w.itemDoubleClicked.connect(lambda item, col: self.open_file.emit(item.data(0, Qt.ItemDataRole.UserRole)))
        w.header().setStretchLastSection(True)
        w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        w.customContextMenuRequested.connect(lambda pos, view=w: self._on_context_menu(view, pos))
        w.installEventFilter(self)
        return w

    def eventFilter(self, watched, event):
        # Delete / Paste key support on directory views
        try:
            from PySide6.QtCore import QEvent
            from PySide6.QtGui import QKeyEvent
            if isinstance(watched, QTreeWidget) and event.type() == QEvent.Type.KeyPress:
                e: QKeyEvent = event  # type: ignore
                if e.key() == Qt.Key.Key_Delete:
                    self.delete_selected()
                    return True
                # Ctrl+V paste clipboard into current directory
                if (e.modifiers() & Qt.KeyboardModifier.ControlModifier) and e.key() == Qt.Key.Key_V:
                    self._paste_clipboard_into(self.current_dir or "/")
                    return True
        except Exception:
            pass
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
        if lower.endswith((".zip", ".rar", ".7z", ".tgz", ".tar.gz", ".tar")):
            return st.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        return st.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def refresh(self):
        if not self.session or not self.session.get("files"):
            # still allow UI
            for v in self.views.values():
                v.clear()
            return

        files = self.session["files"]
        try:
            entries = files.listdir_entries(self.current_dir)
        except Exception as e:
            QMessageBox.warning(self, t("common.error"), f"{t('dirs.load_failed') if t('dirs.load_failed') != '[dirs.load_failed]' else 'Dizin okunamadı'}: {e}")
            # clear
            for v in self.views.values():
                v.clear()
            return

        # clear all
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



    def _selected_remote_path(self, view: QTreeWidget) -> str:
        it = view.currentItem()
        if not it:
            return ""
        rp = it.data(0, Qt.ItemDataRole.UserRole)
        return str(rp) if rp else ""

        def _on_context_menu(self, view: QTreeWidget, pos):
            # Context menu for directories tab (copy/move clipboard + paste + delete/download/rename/edit).
            if not self.session or not self.session.get("files"):
                return

            # Determine which tab key this view belongs to (for selection)
            tab_key = "all"
            for k, v in self.views.items():
                if v is view:
                    tab_key = k
                    break

            files = self.session.get("files")
            clipboard = get_file_clipboard()

            item = view.itemAt(pos)
            clicked_path = None
            clicked_is_dir = False
            if item is not None:
                clicked_path = item.data(0, Qt.ItemDataRole.UserRole)
                clicked_is_dir = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))

            sel_items = view.selectedItems()
            sel_paths = [it.data(0, Qt.ItemDataRole.UserRole) for it in sel_items if it is not None]
            # Use clicked item if nothing is selected (common UX)
            if not sel_paths and clicked_path:
                sel_paths = [clicked_path]

            menu = QMenu(self)

            # Optional output open actions (JobsOutputsWidget)
            if self.enable_output_menu and clicked_path:
                a1 = menu.addAction(t("jobs_outputs.open_out1") if t("jobs_outputs.open_out1") != "[jobs_outputs.open_out1]" else "Çıktı-1'de Aç")
                a2 = menu.addAction(t("jobs_outputs.open_out2") if t("jobs_outputs.open_out2") != "[jobs_outputs.open_out2]" else "Çıktı-2'de Aç")
                menu.addSeparator()

            # Clipboard paste actions (available even on empty area)
            clip = clipboard.get()
            act_paste_here = None
            act_paste_into = None
            if clip and clip.paths:
                act_paste_here = menu.addAction(t("dirs.paste") if t("dirs.paste") != "[dirs.paste]" else "Yapıştır")
                if clicked_path and clicked_is_dir:
                    act_paste_into = menu.addAction(t("dirs.paste_into") if t("dirs.paste_into") != "[dirs.paste_into]" else "Klasöre Yapıştır")
                menu.addSeparator()

            # If there is no selection, only paste should be shown
            if sel_paths:
                act_edit = menu.addAction(t("dirs.edit") if t("dirs.edit") != "[dirs.edit]" else "Düzenle")
                act_download = menu.addAction(t("dirs.download") if t("dirs.download") != "[dirs.download]" else "İndir")
                menu.addSeparator()
                act_rename = menu.addAction(t("dirs.rename") if t("dirs.rename") != "[dirs.rename]" else "Yeniden Adlandır")
                act_copy = menu.addAction(t("dirs.copy") if t("dirs.copy") != "[dirs.copy]" else "Kopyala")
                act_move = menu.addAction(t("dirs.move") if t("dirs.move") != "[dirs.move]" else "Taşı")
                menu.addSeparator()
                act_delete = menu.addAction(t("dirs.delete") if t("dirs.delete") != "[dirs.delete]" else "Sil")

                # Disable single-selection actions when multiple are selected
                if len(sel_paths) != 1:
                    act_edit.setEnabled(False)
                    act_rename.setEnabled(False)

            chosen = menu.exec(view.viewport().mapToGlobal(pos))
            if not chosen:
                return

            # Handle JobsOutputsWidget actions first
            if self.enable_output_menu and clicked_path:
                txt = chosen.text()
                if txt == (t("jobs_outputs.open_out1") if t("jobs_outputs.open_out1") != "[jobs_outputs.open_out1]" else "Çıktı-1'de Aç"):
                    self.open_in_slot.emit(0, clicked_path)
                    return
                if txt == (t("jobs_outputs.open_out2") if t("jobs_outputs.open_out2") != "[jobs_outputs.open_out2]" else "Çıktı-2'de Aç"):
                    self.open_in_slot.emit(1, clicked_path)
                    return

            # Paste handling
            if chosen == act_paste_here:
                self._paste_clipboard_into(self.current_dir or "/")
                return
            if act_paste_into is not None and chosen == act_paste_into and clicked_path:
                self._paste_clipboard_into(clicked_path)
                return

            # If there was no selection, nothing else to do
            if not sel_paths:
                return

            # Edit (only files: single file)
            if chosen.text() == (t("dirs.edit") if t("dirs.edit") != "[dirs.edit]" else "Düzenle"):
                rp = sel_paths[0]
                try:
                    # If listdir works, it's a dir; otherwise treat as file
                    files.listdir(rp)
                    QMessageBox.information(self, t("common.info"), "Klasör düzenlenemez.")
                    return
                except Exception:
                    pass
                self.open_file.emit(rp)
                return

            if chosen.text() == (t("dirs.download") if t("dirs.download") != "[dirs.download]" else "İndir"):
                self.download_selected()
                return

            if chosen.text() == (t("dirs.delete") if t("dirs.delete") != "[dirs.delete]" else "Sil"):
                self._delete_paths(sel_paths)
                return

            if chosen.text() == (t("dirs.rename") if t("dirs.rename") != "[dirs.rename]" else "Yeniden Adlandır"):
                if len(sel_paths) != 1:
                    QMessageBox.information(self, t("common.info"), "Yeniden adlandırmak için tek bir öğe seçin.")
                    return
                old = sel_paths[0]
                base = old.rstrip("/").split("/")[-1]
                new_name, ok = QInputDialog.getText(self, t("dirs.rename") if t("dirs.rename") != "[dirs.rename]" else "Yeniden Adlandır", "Yeni ad:", text=base)
                if not ok or not new_name.strip():
                    return
                new_path = old.rstrip("/")
                parent = "/".join(new_path.split("/")[:-1]) or "/"
                dst = parent.rstrip("/") + "/" + new_name.strip()
                try:
                    files.rename(old.rstrip("/"), dst)
                    self.refresh()
                except Exception as e:
                    QMessageBox.critical(self, t("common.error"), str(e))
                return

            # Copy / Move put into clipboard (paste elsewhere / other panel)
            if chosen.text() == (t("dirs.copy") if t("dirs.copy") != "[dirs.copy]" else "Kopyala"):
                clipboard.set("copy", sel_paths)
                return

            if chosen.text() == (t("dirs.move") if t("dirs.move") != "[dirs.move]" else "Taşı"):
                clipboard.set("move", sel_paths)
                return



    
    def _paste_clipboard_into(self, dest_dir: str) -> None:
        if not self.session or not self.session.get("files"):
            return
        files = self.session.get("files")
        clipboard = get_file_clipboard()
        clip = clipboard.get()
        if not clip or not clip.paths:
            return

        # Normalize destination directory
        dest_dir = (dest_dir or "/").strip()
        if not dest_dir.startswith("/"):
            # safety: remote paths should be absolute
            dest_dir = "/" + dest_dir
        dest_dir = dest_dir.rstrip("/") or "/"

        # Perform operation item-by-item to support multi-select
        try:
            for src in clip.paths:
                name = src.rstrip("/").split("/")[-1]
                dst = dest_dir.rstrip("/") + "/" + name

                # Best-effort dir detection
                is_dir = False
                if clip.op == "copy":
                    # Determine directory for recursive copy
                    try:
                        files.listdir(src.rstrip("/"))
                        is_dir = True
                    except Exception:
                        is_dir = src.endswith("/")
                    files.copy(src.rstrip("/"), dst, recursive=is_dir)
                else:
                    files.move(src.rstrip("/"), dst)
            # After move, clear clipboard
            if clip.op == "move":
                clipboard.clear()
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, t("common.error"), str(e))

def _delete_paths(self, paths: List[str]) -> None:
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), "Bağlantı yok.")
            return
        files = self.session["files"]
        if not paths:
            return
        # Confirm
        msg = "Seçilen öğeler silinsin mi?\n" + "\n".join([p.split("/")[-1] for p in paths[:10]])
        if len(paths) > 10:
            msg += f"\n... (+{len(paths)-10})"
        if QMessageBox.question(self, t("common.confirm") if t("common.confirm") != "[common.confirm]" else "Onay", msg) != QMessageBox.StandardButton.Yes:
            return
        for rp in paths:
            # recursive delete if dir
            recursive = False
            try:
                files.listdir(rp)
                recursive = True
            except Exception:
                recursive = False
            files.remove(rp, recursive=recursive)
        self.refresh()

    def delete_selected(self):
        # Delete from active tab view
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
    def upload_files(self):
        if not self.session or not self.session.get("files"):
            QMessageBox.warning(self, t("common.error"), "Bağlantı yok.")
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
            QMessageBox.warning(self, t("common.error"), "Bağlantı yok.")
            return
        files = self.session["files"]
        # gather from current tab view
        # try each tab, but prefer active tab
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
        target_dir = QFileDialog.getExistingDirectory(self, t("dirs.download_selected") if t("dirs.download_selected") != "[dirs.download_selected]" else "Seçilenleri İndir")
        if not target_dir:
            return
        for rp in sel:
            name = rp.rstrip("/").split("/")[-1]
            lp = os.path.join(target_dir, name)
            try:
                files.download(rp, lp)
            except Exception as e:
                QMessageBox.warning(self, t("common.error"), f"İndirilemedi: {name}\n{e}")

    def selected_paths(self, tab_key: str = "all") -> List[str]:
        view = self.views.get(tab_key, self.views["all"])
        paths = []
        for it in view.selectedItems():
            p = it.data(0, Qt.ItemDataRole.UserRole)
            if p:
                paths.append(p)
        return paths