from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from truba_gui.config.storage import (
    get_jobs_outputs_refresh_interval_seconds,
    get_ftp_transfer_type,
    clear_file_association,
    get_file_associations,
    get_ftp_state,
    get_lssrv_auto_refresh_enabled,
    get_sbatch_auto_open_outputs_enabled,
    get_sbatch_follow_mode,
    get_transfer_auto_refresh_enabled,
    get_transfer_parallelism,
    load_settings,
    set_file_association,
    update_ftp_state,
    update_settings,
)
from truba_gui.core.i18n import t
from truba_gui.config.system_profile import (
    normalize_system_settings,
    truba_default_remote_paths,
)


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        session=None,
        update_remote_defaults=None,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(t("settings.dialog_title"))

        st = load_settings()
        self._update_remote_defaults = update_remote_defaults

        self.cb_x11_autodeps = QCheckBox(t("login.x11_autodeps_label"))
        self.cb_x11_autodeps.setToolTip(t("login.x11_autodeps_tip"))
        self.cb_x11_autodeps.setChecked(bool(st.get("x11_autodeps", True)))

        self.cb_close_vcxsrv_on_exit = QCheckBox(t("login.close_vcxsrv_label"))
        self.cb_close_vcxsrv_on_exit.setToolTip(t("login.close_vcxsrv_tip"))
        self.cb_close_vcxsrv_on_exit.setChecked(bool(st.get("close_vcxsrv_on_exit", True)))

        self.cb_close_x11_procs_on_exit = QCheckBox(t("login.close_x11_procs_label"))
        self.cb_close_x11_procs_on_exit.setToolTip(t("login.close_x11_procs_tip"))
        self.cb_close_x11_procs_on_exit.setChecked(bool(st.get("close_x11_procs_on_exit", True)))

        self.sp_jobs_outputs_refresh_interval = QSpinBox()
        self.sp_jobs_outputs_refresh_interval.setRange(1, 3600)
        self.sp_jobs_outputs_refresh_interval.setSingleStep(1)
        self.sp_jobs_outputs_refresh_interval.setValue(get_jobs_outputs_refresh_interval_seconds())
        self.sp_jobs_outputs_refresh_interval.setToolTip(t("settings.jobs_outputs_refresh_interval_tip"))

        self.cb_lssrv_auto_refresh = QCheckBox(t("settings.lssrv_auto_refresh_label"))
        self.cb_lssrv_auto_refresh.setChecked(get_lssrv_auto_refresh_enabled())
        self.cb_lssrv_auto_refresh.setToolTip(t("settings.lssrv_auto_refresh_tip"))

        self.cb_sbatch_auto_open_outputs = QCheckBox(
            t("settings.sbatch_auto_open_outputs_label")
        )
        self.cb_sbatch_auto_open_outputs.setChecked(
            get_sbatch_auto_open_outputs_enabled()
        )
        self.cb_sbatch_auto_open_outputs.setToolTip(
            t("settings.sbatch_auto_open_outputs_tip")
        )

        self.cb_sbatch_follow_mode = QComboBox()
        self.cb_sbatch_follow_mode.addItem(
            t("settings.sbatch_follow_mode_tabs"),
            "new_tabs_split",
        )
        self.cb_sbatch_follow_mode.addItem(
            t("settings.sbatch_follow_mode_window_combined"),
            "new_window_combined",
        )
        self.cb_sbatch_follow_mode.addItem(
            t("settings.sbatch_follow_mode_windows_split"),
            "new_windows_split",
        )
        self.cb_sbatch_follow_mode.addItem(
            t("settings.sbatch_follow_mode_outputs_tab"),
            "outputs_tab",
        )
        for mode, tip_key in {
            "new_tabs_split": "settings.sbatch_follow_mode_tabs_tip",
            "new_window_combined": "settings.sbatch_follow_mode_window_combined_tip",
            "new_windows_split": "settings.sbatch_follow_mode_windows_split_tip",
            "outputs_tab": "settings.sbatch_follow_mode_outputs_tab_tip",
        }.items():
            index = self.cb_sbatch_follow_mode.findData(mode)
            if index >= 0:
                self.cb_sbatch_follow_mode.setItemData(
                    index,
                    t(tip_key),
                    Qt.ItemDataRole.ToolTipRole,
                )
        follow_mode_index = self.cb_sbatch_follow_mode.findData(
            get_sbatch_follow_mode()
        )
        self.cb_sbatch_follow_mode.setCurrentIndex(max(0, follow_mode_index))
        self.cb_sbatch_follow_mode.setToolTip(
            t("settings.sbatch_follow_mode_tip")
        )

        self.sp_transfer_parallelism = QSpinBox()
        self.sp_transfer_parallelism.setRange(1, 10)
        self.sp_transfer_parallelism.setSingleStep(1)
        self.sp_transfer_parallelism.setValue(get_transfer_parallelism())
        self.sp_transfer_parallelism.setToolTip(t("settings.transfer_parallelism_tip"))

        self.cb_transfer_auto_refresh = QCheckBox(
            t("settings.transfer_auto_refresh_label")
        )
        self.cb_transfer_auto_refresh.setChecked(
            get_transfer_auto_refresh_enabled()
        )
        self.cb_transfer_auto_refresh.setToolTip(
            t("settings.transfer_auto_refresh_tip")
        )

        self.cb_ftp_transfer_type = QComboBox()
        self.cb_ftp_transfer_type.addItem(t("ftp.mode_auto"), "auto")
        self.cb_ftp_transfer_type.addItem(t("ftp.mode_binary"), "binary")
        self.cb_ftp_transfer_type.addItem(t("ftp.mode_ascii"), "ascii")
        transfer_type_index = self.cb_ftp_transfer_type.findData(get_ftp_transfer_type())
        self.cb_ftp_transfer_type.setCurrentIndex(max(0, transfer_type_index))
        self.cb_ftp_transfer_type.setToolTip(t("settings.ftp_transfer_type_tip"))
        ftp_state = get_ftp_state()
        self.ftp_local_dir = QLineEdit(str(ftp_state.get("local_dir") or ""))
        self.ftp_local_dir.setToolTip(t("settings.ftp_local_dir_tip"))
        self.btn_ftp_local_dir_browse = QPushButton(t("settings.ftp_local_dir_browse"))
        self.btn_ftp_local_dir_browse.clicked.connect(self._browse_ftp_local_dir)
        ftp_local_dir_row = QHBoxLayout()
        ftp_local_dir_row.addWidget(self.ftp_local_dir, 1)
        ftp_local_dir_row.addWidget(self.btn_ftp_local_dir_browse)

        self.cb_ftp_active_remote = QComboBox()
        self.cb_ftp_active_remote.addItem(t("ftp.scratch"), "scratch")
        self.cb_ftp_active_remote.addItem(t("ftp.home"), "home")
        active_remote_index = self.cb_ftp_active_remote.findData(
            ftp_state.get("active_remote") or "scratch"
        )
        self.cb_ftp_active_remote.setCurrentIndex(max(0, active_remote_index))
        self.cb_ftp_active_remote.setToolTip(t("settings.ftp_active_remote_tip"))
        self._file_associations = get_file_associations()

        connection_group = QGroupBox(t("settings.connection_section"))
        connection_form = QFormLayout(connection_group)
        connection_form.addRow(self.cb_x11_autodeps)
        connection_form.addRow(self.cb_close_vcxsrv_on_exit)
        connection_form.addRow(self.cb_close_x11_procs_on_exit)

        jobs_group = QGroupBox(t("settings.jobs_outputs_section"))
        jobs_form = QFormLayout(jobs_group)
        jobs_form.addRow(
            t("settings.jobs_outputs_refresh_interval_label"),
            self.sp_jobs_outputs_refresh_interval,
        )
        jobs_form.addRow(self.cb_lssrv_auto_refresh)
        jobs_form.addRow(self.cb_sbatch_auto_open_outputs)
        jobs_form.addRow(
            t("settings.sbatch_follow_mode_label"),
            self.cb_sbatch_follow_mode,
        )

        ftp_group = QGroupBox(t("settings.ftp_section"))
        ftp_form = QFormLayout(ftp_group)
        cfg = (session or {}).get("cfg") if session else None
        system = normalize_system_settings(
            getattr(cfg, "system_settings", None) if cfg else None
        )
        self.ftp_scratch_dir = QLineEdit(system["scratch_dir"])
        self.ftp_home_dir = QLineEdit(system["home_dir"])
        self._initial_scratch_dir = self.ftp_scratch_dir.text().strip()
        self._initial_home_dir = self.ftp_home_dir.text().strip()
        profile_available = bool(
            session
            and session.get("connected")
            and session.get("profile_name")
            and update_remote_defaults
        )
        self.ftp_scratch_dir.setEnabled(profile_available)
        self.ftp_home_dir.setEnabled(profile_available)
        ftp_form.addRow(t("settings.ftp_scratch_default"), self.ftp_scratch_dir)
        ftp_form.addRow(t("settings.ftp_home_default"), self.ftp_home_dir)
        ftp_form.addRow(t("settings.ftp_local_dir_label"), ftp_local_dir_row)
        ftp_form.addRow(
            t("settings.ftp_active_remote_label"),
            self.cb_ftp_active_remote,
        )
        ftp_form.addRow(
            t("settings.ftp_transfer_type_label"),
            self.cb_ftp_transfer_type,
        )
        ftp_form.addRow(
            t("settings.transfer_parallelism_label"),
            self.sp_transfer_parallelism,
        )
        ftp_form.addRow(self.cb_transfer_auto_refresh)
        self.btn_ftp_reset_defaults = QPushButton(
            t("settings.ftp_reset_defaults")
        )
        self.btn_ftp_reset_defaults.setEnabled(profile_available)
        self.btn_ftp_reset_defaults.clicked.connect(self._reset_ftp_defaults)
        ftp_form.addRow(self.btn_ftp_reset_defaults)

        associations_group = QGroupBox(t("settings.file_associations_section"))
        associations_layout = QVBoxLayout(associations_group)
        self.file_associations_list = QListWidget()
        associations_layout.addWidget(self.file_associations_list)
        association_buttons = QHBoxLayout()
        self.btn_change_file_association = QPushButton(
            t("settings.file_association_change")
        )
        self.btn_clear_file_association = QPushButton(
            t("settings.file_association_clear")
        )
        self.btn_change_file_association.clicked.connect(
            self._change_selected_file_association
        )
        self.btn_clear_file_association.clicked.connect(
            self._clear_selected_file_association
        )
        association_buttons.addWidget(self.btn_change_file_association)
        association_buttons.addWidget(self.btn_clear_file_association)
        associations_layout.addLayout(association_buttons)
        self._refresh_file_association_list()

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("settings.save"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("common.cancel"))
        self.buttons.accepted.connect(self._save_and_close)
        self.buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(connection_group)
        root.addWidget(jobs_group)
        root.addWidget(ftp_group)
        root.addWidget(associations_group)
        root.addWidget(self.buttons)

    def _save_and_close(self) -> None:
        update_settings(
            {
                "x11_autodeps": self.cb_x11_autodeps.isChecked(),
                "close_vcxsrv_on_exit": self.cb_close_vcxsrv_on_exit.isChecked(),
                "close_x11_procs_on_exit": self.cb_close_x11_procs_on_exit.isChecked(),
                "jobs_outputs_refresh_interval_seconds": int(self.sp_jobs_outputs_refresh_interval.value()),
                "lssrv_auto_refresh_enabled": self.cb_lssrv_auto_refresh.isChecked(),
                "sbatch_auto_open_outputs": self.cb_sbatch_auto_open_outputs.isChecked(),
                "sbatch_follow_mode": str(
                    self.cb_sbatch_follow_mode.currentData() or "new_tabs_split"
                ),
                "transfer_parallelism": int(self.sp_transfer_parallelism.value()),
                "transfer_auto_refresh_enabled": self.cb_transfer_auto_refresh.isChecked(),
                "ftp_transfer_type": str(
                    self.cb_ftp_transfer_type.currentData() or "auto"
                ),
            }
        )
        if self._update_remote_defaults is not None and self.ftp_scratch_dir.isEnabled():
            scratch = self.ftp_scratch_dir.text().strip()
            home = self.ftp_home_dir.text().strip()
            if scratch != self._initial_scratch_dir or home != self._initial_home_dir:
                self._update_remote_defaults(scratch, home)
        update_ftp_state(
            local_dir=self.ftp_local_dir.text().strip(),
            active_remote=str(self.cb_ftp_active_remote.currentData() or "scratch"),
        )
        self.accept()

    def _browse_ftp_local_dir(self) -> None:
        current = self.ftp_local_dir.text().strip() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(
            self,
            t("settings.ftp_local_dir_select"),
            current,
        )
        if folder:
            self.ftp_local_dir.setText(folder)

    def _reset_ftp_defaults(self) -> None:
        defaults = truba_default_remote_paths()
        self.ftp_scratch_dir.setText(defaults["scratch_dir"])
        self.ftp_home_dir.setText(defaults["home_dir"])
        if self._update_remote_defaults is not None:
            self._update_remote_defaults(
                defaults["scratch_dir"],
                defaults["home_dir"],
            )

    def _refresh_file_association_list(self) -> None:
        self.file_associations_list.clear()
        for extension, program in sorted(self._file_associations.items()):
            self.file_associations_list.addItem(f"{extension} -> {program}")
        empty = not self._file_associations
        self.btn_change_file_association.setEnabled(not empty)
        self.btn_clear_file_association.setEnabled(not empty)

    def _selected_file_association_extension(self) -> str:
        item = self.file_associations_list.currentItem()
        if item is None:
            return ""
        return item.text().split(" -> ", 1)[0].strip()

    def _change_selected_file_association(self) -> None:
        extension = self._selected_file_association_extension()
        if not extension:
            QMessageBox.information(
                self,
                t("common.info"),
                t("settings.file_association_none_selected"),
            )
            return
        program, _ = QFileDialog.getOpenFileName(
            self,
            t("files.open_with_select_program"),
            self._file_associations.get(extension, ""),
            t("files.open_with_program_filter"),
        )
        if not program:
            return
        self._file_associations = set_file_association(extension, program)
        self._refresh_file_association_list()

    def _clear_selected_file_association(self) -> None:
        extension = self._selected_file_association_extension()
        if not extension:
            QMessageBox.information(
                self,
                t("common.info"),
                t("settings.file_association_none_selected"),
            )
            return
        self._file_associations = clear_file_association(extension)
        self._refresh_file_association_list()
