from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from truba_gui.core.i18n import t
from truba_gui.config.system_profile import (
    builtin_system_template_groups,
    load_user_system_templates,
    normalize_system_settings,
    save_user_system_template,
)

ProfileData = dict[str, Any]


class ConnectionDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        initial_profile: ProfileData | None = None,
        on_save: Callable[[ProfileData], bool] | None = None,
        on_connect: Callable[[ProfileData], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._initial_profile = dict(initial_profile or {})
        self._on_save = on_save
        self._on_connect = on_connect
        self._system_template_menu: QMenu | None = None
        self._system_template_submenus: list[QMenu] = []

        self.setModal(True)
        self.setWindowTitle(t("connection.dialog_title"))

        self.profile_name = QLineEdit()
        self.host = QLineEdit()
        self.port = QLineEdit("22")
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        self.cb_save_password = QCheckBox(t("login.save_password"))
        self.cb_edit_only_password = QCheckBox(
            t("connection.password_edit_only")
        )
        self.cb_edit_only_password.setToolTip(
            t("connection.password_edit_only_tip")
        )
        self.cb_save_password.toggled.connect(
            self.cb_edit_only_password.setEnabled
        )
        self.key_path = QLineEdit()
        self.btn_browse_key = QPushButton(t("login.browse"))
        self.btn_browse_key.clicked.connect(self.pick_key)

        self.cb_x11 = QCheckBox(t("login.x11_enable"))
        self.cb_strict_hostkey = QCheckBox(t("login.strict_host_key"))

        form = QFormLayout()
        form.addRow(t("login.profile_name_label"), self.profile_name)
        form.addRow(t("login.host"), self.host)
        form.addRow(t("login.port"), self.port)
        form.addRow(t("login.username"), self.username)
        form.addRow(t("login.password"), self.password)
        form.addRow("", self.cb_save_password)
        form.addRow("", self.cb_edit_only_password)

        key_row = QHBoxLayout()
        key_row.addWidget(self.key_path)
        key_row.addWidget(self.btn_browse_key)
        form.addRow(t("login.ssh_key"), key_row)

        form.addRow("", self.cb_x11)
        form.addRow("", self.cb_strict_hostkey)

        self.system_name = QLineEdit()
        self.scratch_dir = QLineEdit()
        self.home_dir = QLineEdit()
        self.squeue_command = QLineEdit()
        self.sbatch_command = QLineEdit()
        self.scancel_command = QLineEdit()
        self.sacct_command = QLineEdit()
        self.scontrol_command = QLineEdit()
        self.status_command = QLineEdit()
        self.active_job_ids_command = QLineEdit()
        self.job_state_command = QLineEdit()

        self.btn_system_templates = QToolButton()
        self.btn_system_templates.setText(t("connection.system_templates_menu"))
        self.btn_system_templates.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_save_system_template = QPushButton(t("connection.save_system_template"))
        self.btn_save_system_template.clicked.connect(self._save_current_system_template)

        system_actions = QHBoxLayout()
        system_actions.addWidget(self.btn_system_templates)
        system_actions.addWidget(self.btn_save_system_template)
        system_actions.addStretch(1)

        system_form = QFormLayout()
        system_form.addRow(t("connection.system_name"), self.system_name)
        system_form.addRow(t("connection.system_templates"), system_actions)
        system_form.addRow(t("connection.scratch_dir"), self.scratch_dir)
        system_form.addRow(t("connection.home_dir"), self.home_dir)
        system_form.addRow(t("connection.squeue_command"), self.squeue_command)
        system_form.addRow(t("connection.sbatch_command"), self.sbatch_command)
        system_form.addRow(t("connection.scancel_command"), self.scancel_command)
        system_form.addRow(t("connection.sacct_command"), self.sacct_command)
        system_form.addRow(t("connection.scontrol_command"), self.scontrol_command)
        system_form.addRow(t("connection.status_command"), self.status_command)
        system_form.addRow(
            t("connection.active_job_ids_command"),
            self.active_job_ids_command,
        )
        system_form.addRow(
            t("connection.job_state_command"),
            self.job_state_command,
        )
        system_group = QGroupBox(t("connection.system_settings"))
        system_group.setLayout(system_form)

        self.btn_save = QPushButton(t("connection.save"))
        self.btn_save.clicked.connect(self._save_clicked)

        self.btn_save_connect = QPushButton(t("connection.save_and_connect"))
        self.btn_save_connect.clicked.connect(self._save_and_connect_clicked)

        self.btn_cancel = QPushButton(t("common.cancel"))
        self.btn_cancel.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.btn_save)
        button_row.addWidget(self.btn_save_connect)
        button_row.addWidget(self.btn_cancel)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(system_group)
        root.addLayout(button_row)

        self._load_profile(self._initial_profile)
        self._rebuild_system_template_menu()

    def _load_profile(self, profile: ProfileData) -> None:
        self.profile_name.setText(str(profile.get("name", "")))
        self.host.setText(str(profile.get("host", "")))
        self.port.setText(str(profile.get("port", 22)))
        self.username.setText(str(profile.get("username", "")))
        self.key_path.setText(str(profile.get("key_path", "")))
        self.cb_x11.setChecked(bool(profile.get("x11_forwarding", False)))
        self.cb_strict_hostkey.setChecked((profile.get("host_key_policy") or "accept-new") == "strict")
        self.cb_save_password.setChecked(bool(profile.get("save_password", False)))
        self.cb_edit_only_password.setEnabled(self.cb_save_password.isChecked())
        self.cb_edit_only_password.setChecked(
            (profile.get("password_prompt_policy") or "when-needed") == "edit-only"
        )

        system = normalize_system_settings(profile.get("system"))
        self.system_name.setText(system["name"])
        self.scratch_dir.setText(system["scratch_dir"])
        self.home_dir.setText(system["home_dir"])
        self.squeue_command.setText(system["squeue_command"])
        self.sbatch_command.setText(system["sbatch_command"])
        self.scancel_command.setText(system["scancel_command"])
        self.sacct_command.setText(system["sacct_command"])
        self.scontrol_command.setText(system["scontrol_command"])
        self.status_command.setText(system["status_command"])
        self.active_job_ids_command.setText(system["active_job_ids_command"])
        self.job_state_command.setText(system["job_state_command"])

        if profile.get("save_password") and isinstance(profile.get("password"), str) and profile.get("password"):
            self.password.setText(str(profile.get("password", "")))
        else:
            self.password.setText("")

    def _system_form_values(self) -> dict[str, str]:
        return {
            "name": self.system_name.text().strip(),
            "scratch_dir": self.scratch_dir.text().strip(),
            "home_dir": self.home_dir.text().strip(),
            "squeue_command": self.squeue_command.text().strip(),
            "sbatch_command": self.sbatch_command.text().strip(),
            "scancel_command": self.scancel_command.text().strip(),
            "sacct_command": self.sacct_command.text().strip(),
            "scontrol_command": self.scontrol_command.text().strip(),
            "status_command": self.status_command.text().strip(),
            "active_job_ids_command": self.active_job_ids_command.text().strip(),
            "job_state_command": self.job_state_command.text().strip(),
        }

    def _apply_system_template(self, template: ProfileData) -> None:
        system = normalize_system_settings(template)
        self.system_name.setText(system["name"])
        self.scratch_dir.setText(system["scratch_dir"])
        self.home_dir.setText(system["home_dir"])
        self.squeue_command.setText(system["squeue_command"])
        self.sbatch_command.setText(system["sbatch_command"])
        self.scancel_command.setText(system["scancel_command"])
        self.sacct_command.setText(system["sacct_command"])
        self.scontrol_command.setText(system["scontrol_command"])
        self.status_command.setText(system["status_command"])
        self.active_job_ids_command.setText(system["active_job_ids_command"])
        self.job_state_command.setText(system["job_state_command"])

    def _rebuild_system_template_menu(self) -> None:
        menu = QMenu(self)
        submenus: list[QMenu] = []
        for group_name, templates in builtin_system_template_groups().items():
            submenu = QMenu(group_name, menu)
            menu.addMenu(submenu)
            submenus.append(submenu)
            for template in templates:
                action = submenu.addAction(template["name"])
                action.triggered.connect(
                    lambda _checked=False, selected=dict(template): self._apply_system_template(selected)
                )
        user_templates = load_user_system_templates()
        if user_templates:
            user_menu = QMenu(t("connection.user_templates"), menu)
            menu.addMenu(user_menu)
            submenus.append(user_menu)
            for template in user_templates:
                action = user_menu.addAction(template["name"])
                action.triggered.connect(
                    lambda _checked=False, selected=dict(template): self._apply_system_template(selected)
                )
        self._system_template_menu = menu
        self._system_template_submenus = submenus
        self.btn_system_templates.setMenu(menu)

    def _save_current_system_template(self) -> None:
        default_name = self.system_name.text().strip() or t("connection.custom_system_template")
        name, ok = QInputDialog.getText(
            self,
            t("connection.save_system_template"),
            t("connection.system_template_name"),
            text=default_name,
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(
                self,
                t("common.error"),
                t("connection.system_template_name_required"),
            )
            return
        try:
            save_user_system_template(name, self._system_form_values())
        except ValueError as exc:
            QMessageBox.warning(self, t("common.error"), str(exc))
            return
        self._rebuild_system_template_menu()

    def pick_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("login.ssh_key"))
        if path:
            self.key_path.setText(path)

    def _collect_profile(self) -> ProfileData | None:
        try:
            port = int(self.port.text().strip() or "22")
        except ValueError:
            QMessageBox.warning(self, t("login.err_title"), t("login.err_port_numeric"))
            return None

        return {
            "name": self.profile_name.text().strip(),
            "host": self.host.text().strip(),
            "port": port,
            "username": self.username.text().strip(),
            "password": self.password.text(),
            "key_path": self.key_path.text().strip(),
            "host_key_policy": "strict" if self.cb_strict_hostkey.isChecked() else "accept-new",
            "x11_forwarding": self.cb_x11.isChecked(),
            "save_password": self.cb_save_password.isChecked(),
            "password_prompt_policy": (
                "edit-only"
                if self.cb_edit_only_password.isChecked()
                else "when-needed"
            ),
            "system": {
                **self._system_form_values(),
            },
        }

    def _save_clicked(self) -> None:
        profile = self._collect_profile()
        if profile is None:
            return
        if self._on_save is not None and not self._on_save(profile):
            return
        self.accept()

    def _save_and_connect_clicked(self) -> None:
        profile = self._collect_profile()
        if profile is None:
            return
        if self._on_save is not None and not self._on_save(profile):
            return
        if self._on_connect is not None and not self._on_connect(profile):
            return
        self.accept()
