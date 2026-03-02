from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter, QMessageBox,
    QDialog, QPushButton, QFileDialog, QInputDialog
)

from truba_gui.core.i18n import t
from truba_gui.core.ui_errors import show_exception
from truba_gui.core.history import append_event
from truba_gui.ui.widgets.remote_dir_panel import RemoteDirPanel


class DirectoriesWidget(QWidget):
    open_in_editor = Signal(str, str)  # path, content

    def __init__(self):
        super().__init__()
        self.session = None

        self.panel_scratch = RemoteDirPanel(title="/arf/scratch")
        self.panel_home = RemoteDirPanel(title="/arf/home")

        self.panel_scratch.open_file.connect(self.on_open_file)
        self.panel_home.open_file.connect(self.on_open_file)

        splitter = QSplitter()
        splitter.addWidget(self.panel_scratch)
        splitter.addWidget(self.panel_home)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        self.btn_new_slurm = QPushButton(
            t("dirs.new_slurm_edit") if t("dirs.new_slurm_edit") != "[dirs.new_slurm_edit]" else "Create/Edit ARF Slurm"
        )
        self.btn_new_slurm.clicked.connect(self.create_slurm_from_template)

        top = QHBoxLayout()
        top.addWidget(self.btn_new_slurm)
        top.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(splitter)

    def set_session(self, session):
        self.session = session
        self.panel_scratch.set_session(session)
        self.panel_home.set_session(session)

        if not session or not session.get("connected"):
            return
        user = session["cfg"].username or "user"
        self.panel_scratch.set_dir(f"/arf/scratch/{user}")
        self.panel_home.set_dir(f"/arf/home/{user}")

    def retranslate_ui(self):
        self.btn_new_slurm.setText(
            t("dirs.new_slurm_edit") if t("dirs.new_slurm_edit") != "[dirs.new_slurm_edit]" else "Create/Edit ARF Slurm"
        )

    def create_slurm_from_template(self):
        if not self.session or not self.session.get("connected"):
            QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
            return
        template_key = self._pick_template_key()
        if not template_key:
            return
        try:
            template_path = self._resolve_template_path(template_key)
            template_text = template_path.read_text(encoding="utf-8")
        except Exception as e:
            show_exception(self, title=t("common.error"), user_message=f"template.slurm okunamadi: {e}", exc=e, area="FILES")
            return

        default_dir = self.panel_scratch.current_dir or ""
        if not default_dir:
            cfg = self.session.get("cfg") if self.session else None
            user = getattr(cfg, "username", "") or "user"
            default_dir = f"/arf/scratch/{user}"

        name, ok = QInputDialog.getText(
            self,
            t("dirs.new_slurm_name_title") if t("dirs.new_slurm_name_title") != "[dirs.new_slurm_name_title]" else "New Slurm Script",
            t("dirs.new_slurm_name_label") if t("dirs.new_slurm_name_label") != "[dirs.new_slurm_name_label]" else "File name:",
            text="new_job.slurm",
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        if not name.lower().endswith((".slurm", ".sbatch")):
            name += ".slurm"
        target_path = default_dir.rstrip("/") + "/" + name

        files = self.session.get("files") if self.session else None
        if files is not None:
            exists = False
            try:
                exists = bool(files.exists(target_path))
            except Exception:
                exists = False
            if exists:
                ans = QMessageBox.question(
                    self,
                    t("dirs.conflict_title"),
                    (t("dirs.new_slurm_exists") if t("dirs.new_slurm_exists") != "[dirs.new_slurm_exists]" else "File already exists. Overwrite in editor?"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return

        append_event({"type": "new_slurm_from_template", "path": target_path})
        self.open_in_editor.emit(target_path, template_text)

    def _pick_template_key(self) -> str:
        options = [
            t("dirs.template_core") if t("dirs.template_core") != "[dirs.template_core]" else "Core template",
            t("dirs.template_cpu") if t("dirs.template_cpu") != "[dirs.template_cpu]" else "CPU template",
            t("dirs.template_gpu") if t("dirs.template_gpu") != "[dirs.template_gpu]" else "GPU template",
            t("dirs.template_mpi") if t("dirs.template_mpi") != "[dirs.template_mpi]" else "MPI template",
        ]
        choice, ok = QInputDialog.getItem(
            self,
            t("dirs.template_select_title") if t("dirs.template_select_title") != "[dirs.template_select_title]" else "Slurm template",
            t("dirs.template_select_label") if t("dirs.template_select_label") != "[dirs.template_select_label]" else "Template type:",
            options,
            0,
            False,
        )
        if not ok:
            return ""
        mapping = {
            options[0]: "core",
            options[1]: "cpu",
            options[2]: "gpu",
            options[3]: "mpi",
        }
        return mapping.get(choice, "core")

    @staticmethod
    def _resolve_template_path(template_key: str) -> Path:
        root = Path(__file__).resolve().parents[4]
        user_tpl = Path.home() / ".truba_slurm_gui" / "templates"
        env_tpl = Path(os.environ.get("TRUBA_TEMPLATE_DIR", "")).expanduser() if os.environ.get("TRUBA_TEMPLATE_DIR") else None
        filename_map = {
            "core": "template.slurm",
            "cpu": "template_cpu.slurm",
            "gpu": "template_gpu.slurm",
            "mpi": "template_mpi.slurm",
        }
        mapping = {
            "core": root / "template.slurm",
            "cpu": root / "templates" / "template_cpu.slurm",
            "gpu": root / "templates" / "template_gpu.slurm",
            "mpi": root / "templates" / "template_mpi.slurm",
        }
        fname = filename_map.get(template_key, "template.slurm")
        search_paths = []
        if env_tpl:
            search_paths.append(env_tpl / fname)
        search_paths.append(user_tpl / fname)
        search_paths.append(mapping.get(template_key, mapping["core"]))
        for p in search_paths:
            if p.exists():
                return p
        # Safe fallback to core template if variant file missing.
        return mapping["core"]

    def shutdown(self) -> None:
        """Best-effort shutdown for file operations (cancel in-flight batches)."""
        for p in (getattr(self, "panel_scratch", None), getattr(self, "panel_home", None)):
            try:
                if p is not None and hasattr(p, "shutdown"):
                    p.shutdown()
            except Exception:
                pass

    def on_open_file(self, path: str):
        # If directory, we don't support navigation yet (next step). For now ignore.
        if path.endswith("/"):
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(t("dirs.file_actions") if t("dirs.file_actions") != "[dirs.file_actions]" else "Dosya İşlemleri")

        btn_download = QPushButton(t("dirs.download") if t("dirs.download") != "[dirs.download]" else "İndir")
        btn_edit = QPushButton(t("dirs.edit") if t("dirs.edit") != "[dirs.edit]" else "Düzelt")
        btn_close = QPushButton(t("common.cancel"))

        row = QHBoxLayout(dlg)
        row.addWidget(QLabel(path))
        row.addStretch(1)
        row.addWidget(btn_download)
        row.addWidget(btn_edit)
        row.addWidget(btn_close)

        def do_download():
            if not self.session or not self.session.get("files"):
                QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
                return
            try:
                content = self.session["files"].read_text(path)
            except Exception as e:
                show_exception(self, title=t("common.error"), user_message=t("dirs.unreadable").format(err=e), exc=e, area="FILES")
                return
            save_path, _ = QFileDialog.getSaveFileName(self, t("dirs.save_as") if t("dirs.save_as") != "[dirs.save_as]" else "Farklı Kaydet")
            if not save_path:
                return
            try:
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                show_exception(self, title=t("common.error"), user_message=f"Kaydedilemedi: {e}", exc=e, area="FILES")
                return
            append_event({"type": "download", "remote": path, "local": save_path})
            dlg.accept()

        def do_edit():
            if not self.session or not self.session.get("files"):
                QMessageBox.warning(self, t("common.error"), t("common.no_connection"))
                return
            try:
                content = self.session["files"].read_text(path)
            except Exception as e:
                show_exception(self, title=t("common.error"), user_message=f"Okunamadı: {e}", exc=e, area="FILES")
                return
            append_event({"type": "open_editor", "path": path})
            self.open_in_editor.emit(path, content)
            dlg.accept()

        btn_download.clicked.connect(do_download)
        btn_edit.clicked.connect(do_edit)
        btn_close.clicked.connect(dlg.reject)

        dlg.exec()
