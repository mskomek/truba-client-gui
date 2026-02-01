from __future__ import annotations

from PySide6.QtCore import Signal, QProcess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QHBoxLayout,
    QLineEdit, QPushButton, QCheckBox, QLabel, QFileDialog,
    QListWidget, QSplitter, QMessageBox, QTextEdit, QInputDialog
)

from truba_gui.core.i18n import t
from truba_gui.config.models import SSHConfig
from truba_gui.config.storage import load_profiles, upsert_profile
from truba_gui.core.history import append_event
from truba_gui.core.logging import append_log
from truba_gui.services.slurm_mock import MockSlurmBackend
from truba_gui.services.files_mock import MockFilesBackend
from truba_gui.services.x11_system_ssh import (
    build_x11_launch,
    is_likely_x11_gui_command,
    is_likely_x11_related_command,
    wrap_remote_cmd_clean_env,
)
from truba_gui.services.xserver_manager import ensure_x_server_running
from truba_gui.ssh.client import SSHClientWrapper, SSHConnInfo
from truba_gui.services.files_ssh import SSHFilesBackend
from truba_gui.services.slurm_ssh import SSHSlurmBackend
from truba_gui.core.crypto_master import encrypt_with_master, decrypt_with_master

import shiboken6


class LoginWidget(QWidget):
    """
    Sol: Profil listesi
    Sağ: Bağlantı formu + Kaydet + Konsol + SSH terminal komutu çalıştırma
    """
    session_changed = Signal(object)

    def __init__(self):
        super().__init__()
        # Keep background QProcess instances (X11 ssh/plink) alive to ensure
        # stdout/stderr signals are delivered (avoid GC surprises).
        self._bg_procs: list[QProcess] = []

        # ---- Left: profiles
        self.profiles_list = QListWidget()
        self.profiles_list.itemSelectionChanged.connect(self.on_profile_selected)

        # ---- Right: form
        self.profile_name = QLineEdit()
        self.host = QLineEdit()
        self.port = QLineEdit("22")
        self.username = QLineEdit()

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        self.cb_save_password = QCheckBox(t("login.save_password") if t("login.save_password") != "[login.save_password]" else "Şifreyi kaydet")
        self.key_path = QLineEdit()
        self.btn_browse_key = QPushButton(t("login.browse") if t("login.browse") != "[login.browse]" else "Seç")
        self.btn_browse_key.clicked.connect(self.pick_key)

        self.cb_x11 = QCheckBox(t("login.x11_enable") if t("login.x11_enable") != "[login.x11_enable]" else "X11 Forwarding")
        self.cb_dry = QCheckBox(t("login.dry_run") if t("login.dry_run") != "[login.dry_run]" else "Simülasyon / Dry-Run")

        self.btn_save = QPushButton(t("login.save") if t("login.save") != "[login.save]" else "Kaydet")
        self.btn_save.clicked.connect(self.save_profile)

        self.btn_connect = QPushButton(t("login.connect") if t("login.connect") != "[login.connect]" else "Bağlan")
        self.btn_connect.clicked.connect(self.connect_clicked)

        self.status_label = QLabel(t("login.status_disconnected") if t("login.status_disconnected") != "[login.status_disconnected]" else "Bağlı değil")

        # ---- Console
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        ph = t("login.console_placeholder")
        if ph.startswith("["):
            ph = "Bağlantı ve SSH mesajları burada görünecek..."
        self.console.setPlaceholderText(ph)

        # ---- SSH terminal line
        self.cmd_in = QLineEdit()
        self.cmd_in.setPlaceholderText(t("login.command_placeholder") if t("login.command_placeholder") != "[login.command_placeholder]" else "Komut yaz ve Enter/Çalıştır")
        self.btn_run_cmd = QPushButton(t("login.run_command") if t("login.run_command") != "[login.run_command]" else "Çalıştır")
        self.btn_run_cmd.clicked.connect(self.run_command)
        self.cmd_in.returnPressed.connect(self.run_command)

        cmd_row = QHBoxLayout()
        cmd_row.addWidget(self.cmd_in)
        cmd_row.addWidget(self.btn_run_cmd)

        form = QFormLayout()
        form.addRow("Profil Adı", self.profile_name)
        form.addRow(t("login.host"), self.host)
        form.addRow(t("login.port"), self.port)
        form.addRow(t("login.username"), self.username)
        form.addRow(t("login.password"), self.password)
        form.addRow("", self.cb_save_password)

        key_row = QHBoxLayout()
        key_row.addWidget(self.key_path)
        key_row.addWidget(self.btn_browse_key)
        form.addRow(t("login.ssh_key") if t("login.ssh_key") != "[login.ssh_key]" else "SSH Anahtar", key_row)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_connect)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.addLayout(form)
        right_lay.addWidget(self.cb_x11)
        right_lay.addWidget(self.cb_dry)
        right_lay.addLayout(btn_row)
        right_lay.addWidget(self.status_label)
        right_lay.addWidget(QLabel(t("login.console_title") if t("login.console_title") != "[login.console_title]" else "Konsol"))
        right_lay.addWidget(self.console)
        right_lay.addLayout(cmd_row)

        splitter = QSplitter()
        splitter.addWidget(self.profiles_list)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        root = QVBoxLayout(self)
        root.addWidget(splitter)

        self._session = {"connected": False, "cfg": SSHConfig(), "ssh": None, "slurm": None, "files": None}

        self.refresh_profiles()

    # ---- public helpers
    def append_console(self, msg: str) -> None:
        # This method can be called by QProcess signals even while the widget
        # is closing. Guard against "Internal C++ object already deleted".
        try:
            if hasattr(self, "console") and shiboken6.isValid(self.console):
                self.console.append(msg)
        except RuntimeError:
            pass
        append_log(msg)

    # ---- profiles
    def refresh_profiles(self) -> None:
        self.profiles_list.clear()
        profiles = load_profiles()
        for p in profiles:
            name = p.get("name", "")
            if name:
                self.profiles_list.addItem(name)

    def on_profile_selected(self) -> None:
        item = self.profiles_list.currentItem()
        if not item:
            return
        name = item.text()
        profiles = load_profiles()
        prof = next((p for p in profiles if p.get("name") == name), None)
        if not prof:
            return
        self.profile_name.setText(prof.get("name", ""))
        self.host.setText(prof.get("host", ""))
        self.port.setText(str(prof.get("port", 22)))
        self.username.setText(prof.get("username", ""))
        self.key_path.setText(prof.get("key_path", ""))
        self.cb_x11.setChecked(bool(prof.get("x11_forwarding", False)))
        self.cb_dry.setChecked(bool(prof.get("dry_run", False)))

        save_pw = bool(prof.get("save_password", False))
        self.cb_save_password.setChecked(save_pw)
        # Never auto-fill decrypted password.
        # If legacy plain password exists, show it; if encrypted, keep empty.
        if save_pw and isinstance(prof.get("password"), str) and prof.get("password"):
            self.password.setText(prof.get("password", ""))
        else:
            self.password.setText("")

    def _ask_master_password(self, *, confirm: bool) -> str | None:
        """Ask user for a master password. Returns None if canceled."""
        title = "Şifreleme Parolası"
        prompt = "Kaydedilen şifreleri şifrelemek/çözmek için bir ana parola girin."
        pw, ok = QInputDialog.getText(self, title, prompt, QLineEdit.EchoMode.Password)
        if not ok:
            return None
        pw = (pw or "").strip()
        if not pw:
            QMessageBox.warning(self, "Hata", "Ana parola boş olamaz.")
            return None
        if confirm:
            pw2, ok2 = QInputDialog.getText(
                self,
                title,
                "Ana parolayı tekrar girin (doğrulama):",
                QLineEdit.EchoMode.Password,
            )
            if not ok2:
                return None
            if pw2 != pw:
                QMessageBox.warning(self, "Hata", "Ana parolalar eşleşmiyor.")
                return None
        return pw

    def pick_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("login.ssh_key") if t("login.ssh_key") != "[login.ssh_key]" else "SSH Anahtar Seç")
        if path:
            self.key_path.setText(path)

    def save_profile(self) -> None:
        name = self.profile_name.text().strip()
        if not name:
            # auto name: user@host
            name = f"{self.username.text().strip()}@{self.host.text().strip()}"
            self.profile_name.setText(name)

        try:
            port = int(self.port.text().strip() or "22")
        except ValueError:
            QMessageBox.warning(self, "Hata", "Port sayısal olmalı.")
            return

        prof = {
            "name": name,
            "host": self.host.text().strip(),
            "port": port,
            "username": self.username.text().strip(),
            "key_path": self.key_path.text().strip(),
            "x11_forwarding": self.cb_x11.isChecked(),
            "dry_run": self.cb_dry.isChecked(),
            "save_password": self.cb_save_password.isChecked(),
        }

        # Password storage (encrypted):
        # - Do not store plaintext in config.
        # - When saving with "save password", ask for a master password and encrypt.
        if self.cb_save_password.isChecked():
            plain = self.password.text() or ""
            if plain:
                master = self._ask_master_password(confirm=True)
                if master is None:
                    return
                enc = encrypt_with_master(master, plain)
                prof["password_enc"] = enc.token
                prof["password_salt"] = enc.salt
            else:
                # keep existing encrypted password if present (when editing profile)
                current = next((p for p in load_profiles() if p.get("name") == name), None)
                if current and current.get("password_enc") and current.get("password_salt"):
                    prof["password_enc"] = current.get("password_enc")
                    prof["password_salt"] = current.get("password_salt")

            # Always clear legacy plaintext field
            prof["password"] = ""
        else:
            prof["password"] = ""
            prof.pop("password_enc", None)
            prof.pop("password_salt", None)

        upsert_profile(prof)
        self.refresh_profiles()
        append_event({"type": "profile_save", "name": name})
        self.append_console(f"Profil kaydedildi: {name}")

    # ---- connect / command
    def connect_clicked(self) -> None:
        try:
            port = int(self.port.text().strip() or "22")
        except ValueError:
            QMessageBox.warning(self, "Hata", "Port sayısal olmalı.")
            return

        # If password is not typed but profile has encrypted password, ask master and decrypt.
        password = self.password.text()
        if not password:
            name = (self.profile_name.text() or "").strip()
            if name:
                prof = next((p for p in load_profiles() if p.get("name") == name), None)
                if prof and prof.get("save_password") and prof.get("password_enc") and prof.get("password_salt"):
                    master = self._ask_master_password(confirm=False)
                    if master is None:
                        return
                    try:
                        password = decrypt_with_master(master, prof["password_enc"], prof["password_salt"])
                    except Exception:
                        QMessageBox.critical(self, "Hata", "Ana parola yanlış veya kayıtlı şifre çözülemedi.")
                        return

        cfg = SSHConfig(
            host=self.host.text().strip(),
            port=port,
            username=self.username.text().strip(),
            password=password,
            key_path=self.key_path.text().strip(),
            x11_forwarding=self.cb_x11.isChecked(),
            dry_run=self.cb_dry.isChecked(),
        )

        if not cfg.host or not cfg.username:
            QMessageBox.warning(self, "Hata", "Host ve kullanıcı adı gerekli.")
            return

        self.append_console(f"Bağlanılıyor: {cfg.username}@{cfg.host}:{cfg.port}")
        try:
            if cfg.dry_run:
                ssh = None
                slurm = MockSlurmBackend()
                files = MockFilesBackend()
                self.status_label.setText(t("login.status_mock") if t("login.status_mock") != "[login.status_mock]" else "Mock mod")
                self.append_console("Mock bağlantı aktif.")
            else:
                conn = SSHConnInfo(
                    host=cfg.host,
                    port=cfg.port,
                    username=cfg.username,
                    password=cfg.password,
                    key_path=cfg.key_path,
                    x11_forwarding=cfg.x11_forwarding,
                )
                ssh = SSHClientWrapper(conn, log_cb=self.append_console)
                ssh.connect()
                slurm = SSHSlurmBackend(ssh)
                files = SSHFilesBackend(ssh)
                self.status_label.setText(t("login.status_connected") if t("login.status_connected") != "[login.status_connected]" else "Bağlı")
                self.append_console("SSH bağlantısı kuruldu.")
        except Exception as e:
            self.status_label.setText(t("login.status_disconnected") if t("login.status_disconnected") != "[login.status_disconnected]" else "Bağlı değil")
            self.append_console(f"Bağlantı hatası: {e}")
            QMessageBox.critical(self, "Bağlantı hatası", str(e))
            return

        self._session = {"connected": True, "cfg": cfg, "ssh": ssh, "slurm": slurm, "files": files}
        append_event({"type": "connect", "host": cfg.host, "user": cfg.username, "dry_run": cfg.dry_run})
        self.session_changed.emit(self._session)

    def run_command(self) -> None:
        cmd = self.cmd_in.text().strip()
        if not cmd:
            return
        self.cmd_in.clear()

        ssh = self._session.get("ssh")
        if not ssh:
            self.append_console("SSH bağlı değil (Mock modda komut çalıştırılmaz).")
            return

        info = getattr(ssh, "info", None)
        x11_enabled = bool(getattr(info, "x11_forwarding", False))

        # X11 is special: use system ssh/plink so the GUI window is separate (like MobaXterm).
        if x11_enabled and (is_likely_x11_gui_command(cmd) or is_likely_x11_related_command(cmd)):
            # Ensure a local X server exists (VcXsrv). If one is already listening on :0, we reuse it.
            if not ensure_x_server_running(self.append_console, parent=self, allow_download=True):
                self.append_console("X11: Yerel X server (VcXsrv) başlatılamadı.")
                return

            remote_cmd = wrap_remote_cmd_clean_env(cmd)
            launch = build_x11_launch(
                host=info.host,
                port=info.port,
                user=info.username,
                remote_cmd=remote_cmd,
                trusted=True,
                key_path=(info.key_path or None),
                password=(info.password or None),
            )
            if not launch:
                self.append_console(
                    "X11 başlatıcı bulunamadı. Windows'ta ssh.exe (OpenSSH) veya plink.exe (PuTTY) gerekli.\n"
                    "Tam standalone için (opsiyonel):\n"
                    " - src/truba_gui/third_party/openssh/ssh.exe\n"
                    " - src/truba_gui/third_party/putty/plink.exe"
                )
                return

            proc = QProcess(self)
            # Make sure local DISPLAY is set for Windows OpenSSH + VcXsrv (PuTTY sets this implicitly).
            try:
                from PySide6.QtCore import QProcessEnvironment

                env = QProcessEnvironment.systemEnvironment()
                if (not env.contains("DISPLAY")) or (not env.value("DISPLAY")):
                    env.insert("DISPLAY", "localhost:0.0")
                proc.setProcessEnvironment(env)
            except Exception:
                pass
            proc.setProgram(launch.program)
            proc.setArguments(launch.args)
            proc.readyReadStandardError.connect(lambda: self._append_process_io(proc, err=True))
            proc.readyReadStandardOutput.connect(lambda: self._append_process_io(proc, err=False))
            def _on_finished(code, _status):
                self.append_console(f"[X11 bitti] code={code}")
                try:
                    self._bg_procs.remove(proc)
                except Exception:
                    pass
            proc.finished.connect(_on_finished)

            cmd_show = " ".join([launch.program] + launch.args)
            self.append_console("X11 başlatıldı:\n" + cmd_show + "\nBeklenen: pencere Windows'ta ayrı açılır.")
            self._bg_procs.append(proc)
            proc.start()

            append_event({"type": "x11_cmd", "cmd": cmd})
            return

        # Normal (non-X11) commands via Paramiko
        try:
            ssh.run(cmd)
            append_event({"type": "ssh_cmd", "cmd": cmd})
        except Exception as e:
            self.append_console(f"Komut hatası: {e}")

    def _append_process_io(self, proc: QProcess, *, err: bool) -> None:
        data = bytes(proc.readAllStandardError() if err else proc.readAllStandardOutput()).decode(errors="replace")
        if data.strip():
            if err:
                self.append_console("STDERR:\n" + data.rstrip())
            else:
                self.append_console(data.rstrip())
