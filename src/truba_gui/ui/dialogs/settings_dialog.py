from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
)

from truba_gui.config.storage import (
    get_jobs_outputs_refresh_interval_seconds,
    get_lssrv_auto_refresh_enabled,
    get_transfer_parallelism,
    load_settings,
    update_settings,
)
from truba_gui.core.i18n import t


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(t("settings.dialog_title"))

        st = load_settings()

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

        self.sp_transfer_parallelism = QSpinBox()
        self.sp_transfer_parallelism.setRange(1, 10)
        self.sp_transfer_parallelism.setSingleStep(1)
        self.sp_transfer_parallelism.setValue(get_transfer_parallelism())
        self.sp_transfer_parallelism.setToolTip(t("settings.transfer_parallelism_tip"))

        form = QFormLayout()
        form.addRow(self.cb_x11_autodeps)
        form.addRow(self.cb_close_vcxsrv_on_exit)
        form.addRow(self.cb_close_x11_procs_on_exit)
        form.addRow(t("settings.jobs_outputs_refresh_interval_label"), self.sp_jobs_outputs_refresh_interval)
        form.addRow(self.cb_lssrv_auto_refresh)
        form.addRow(t("settings.transfer_parallelism_label"), self.sp_transfer_parallelism)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("settings.save"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("common.cancel"))
        self.buttons.accepted.connect(self._save_and_close)
        self.buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.buttons)

    def _save_and_close(self) -> None:
        update_settings(
            {
                "x11_autodeps": self.cb_x11_autodeps.isChecked(),
                "close_vcxsrv_on_exit": self.cb_close_vcxsrv_on_exit.isChecked(),
                "close_x11_procs_on_exit": self.cb_close_x11_procs_on_exit.isChecked(),
                "jobs_outputs_refresh_interval_seconds": int(self.sp_jobs_outputs_refresh_interval.value()),
                "lssrv_auto_refresh_enabled": self.cb_lssrv_auto_refresh.isChecked(),
                "transfer_parallelism": int(self.sp_transfer_parallelism.value()),
            }
        )
        self.accept()
