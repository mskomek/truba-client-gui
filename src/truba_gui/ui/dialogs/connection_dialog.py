from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from truba_gui.core.i18n import t

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

        self.setModal(True)
        self.setWindowTitle(t("connection.dialog_title"))

        self.profile_name = QLineEdit()
        self.host = QLineEdit()
        self.port = QLineEdit("22")
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        self.cb_save_password = QCheckBox(t("login.save_password"))
        self.key_path = QLineEdit()
        self.btn_browse_key = QPushButton(t("login.browse"))
        self.btn_browse_key.clicked.connect(self.pick_key)

        self.cb_x11 = QCheckBox(t("login.x11_enable"))
        self.cb_strict_hostkey = QCheckBox("Strict host key checking")

        form = QFormLayout()
        form.addRow(t("login.profile_name_label"), self.profile_name)
        form.addRow(t("login.host"), self.host)
        form.addRow(t("login.port"), self.port)
        form.addRow(t("login.username"), self.username)
        form.addRow(t("login.password"), self.password)
        form.addRow("", self.cb_save_password)

        key_row = QHBoxLayout()
        key_row.addWidget(self.key_path)
        key_row.addWidget(self.btn_browse_key)
        form.addRow(t("login.ssh_key"), key_row)

        form.addRow("", self.cb_x11)
        form.addRow("", self.cb_strict_hostkey)

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
        root.addLayout(button_row)

        self._load_profile(self._initial_profile)

    def _load_profile(self, profile: ProfileData) -> None:
        self.profile_name.setText(str(profile.get("name", "")))
        self.host.setText(str(profile.get("host", "")))
        self.port.setText(str(profile.get("port", 22)))
        self.username.setText(str(profile.get("username", "")))
        self.key_path.setText(str(profile.get("key_path", "")))
        self.cb_x11.setChecked(bool(profile.get("x11_forwarding", False)))
        self.cb_strict_hostkey.setChecked((profile.get("host_key_policy") or "accept-new") == "strict")
        self.cb_save_password.setChecked(bool(profile.get("save_password", False)))

        if profile.get("save_password") and isinstance(profile.get("password"), str) and profile.get("password"):
            self.password.setText(str(profile.get("password", "")))
        else:
            self.password.setText("")

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
