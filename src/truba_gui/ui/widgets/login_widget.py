from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Qt, QEvent
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QHBoxLayout,
    QLineEdit, QPushButton, QCheckBox, QLabel, QFileDialog,
    QListWidget, QSplitter, QMessageBox, QPlainTextEdit, QInputDialog, QMenu
)

from truba_gui.core.i18n import t
from truba_gui.core.ui_errors import show_exception
from truba_gui.config.models import SSHConfig
from truba_gui.config.storage import load_profiles, upsert_profile, load_settings, delete_profile
from truba_gui.core.history import append_event
from truba_gui.core.logging import append_log
from truba_gui.services.slurm_mock import MockSlurmBackend
from truba_gui.services.files_mock import MockFilesBackend
from truba_gui.services.x11_runner import X11Runner
from truba_gui.ssh.client import SSHClientWrapper, SSHConnInfo
from truba_gui.services.files_ssh import SSHFilesBackend
from truba_gui.services.slurm_ssh import SSHSlurmBackend
from truba_gui.core.crypto_master import encrypt_with_master, decrypt_with_master
from truba_gui.services.terminal_emulator import TerminalEmulator
from truba_gui.ui.widgets.terminal_input import TerminalInput
from truba_gui.ui.dialogs.connection_dialog import ConnectionDialog

import shiboken6


class _TerminalConsole(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._key_handler = None

    def set_key_handler(self, handler) -> None:
        self._key_handler = handler

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        handler = self._key_handler
        if handler is not None and handler(event):
            return
        super().keyPressEvent(event)


class _ConnectionWorker(QObject):
    finished = Signal(object)
    failed = Signal(str, object)

    def __init__(self, cfg: SSHConfig, shell_size: tuple[int, int], log_cb, shell_output_cb, disconnect_cb=None):
        super().__init__()
        self._cfg = cfg
        self._shell_size = shell_size
        self._log_cb = log_cb
        self._shell_output_cb = shell_output_cb
        self._disconnect_cb = disconnect_cb

    def run(self) -> None:
        try:
            conn = SSHConnInfo(
                host=self._cfg.host,
                port=self._cfg.port,
                username=self._cfg.username,
                password=self._cfg.password,
                key_path=self._cfg.key_path,
                host_key_policy=self._cfg.host_key_policy,
                x11_forwarding=self._cfg.x11_forwarding,
            )
            ssh = SSHClientWrapper(
                conn,
                log_cb=self._log_cb,
                shell_output_cb=self._shell_output_cb,
                disconnect_cb=self._disconnect_cb,
            )
            ssh.connect(shell_size=self._shell_size)
            slurm = SSHSlurmBackend(ssh)
            files = SSHFilesBackend(ssh)
            self.finished.emit({
                "cfg": self._cfg,
                "ssh": ssh,
                "slurm": slurm,
                "files": files,
            })
        except Exception as exc:
            self.failed.emit(str(exc), exc)


class LoginWidget(QWidget):
    """
    Sol: Profil listesi
    Sağ: Bağlantı formu + Kaydet + Konsol + SSH terminal komutu çalıştırma
    """
    session_changed = Signal(object)
    console_message = Signal(str)
    shell_output_message = Signal(str)
    ssh_disconnected = Signal(str)

    def __init__(self):
        super().__init__()
        self._x11_runner = X11Runner(log_cb=self.append_console, parent=self)

        # ---- Left: profiles
        self.profiles_list = QListWidget()
        self.profiles_list.itemSelectionChanged.connect(self.on_profile_selected)
        self.profiles_list.itemDoubleClicked.connect(self._on_profile_double_clicked)
        self.profiles_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.profiles_list.customContextMenuRequested.connect(self.show_profile_context_menu)

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
        self.cb_strict_hostkey = QCheckBox("Strict host key checking")

        # Simulation / dry-run option removed from UI.
        # (If a legacy profile contains a 'dry_run' field, it is ignored.)

        self.btn_save = QPushButton(t("login.save") if t("login.save") != "[login.save]" else "Kaydet")
        self.btn_save.clicked.connect(self.save_profile)

        self.btn_add_connection = QPushButton(t("login.add_connection"))
        self.btn_add_connection.clicked.connect(self.open_add_connection_dialog)

        self.btn_connect = QPushButton(t("login.connect_selected"))
        self.btn_connect.clicked.connect(self.connect_selected_profile)

        self.status_label = QLabel(t("login.status_disconnected") if t("login.status_disconnected") != "[login.status_disconnected]" else "Bağlı değil")

        # ---- Console
        self.console = _TerminalConsole(self)
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.console.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.console.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        ph = t("login.console_placeholder")
        self.console.setPlaceholderText(ph)
        self.console.viewport().installEventFilter(self)
        self.console.set_key_handler(self._forward_console_key_event)

        # ---- SSH terminal line
        self.cmd_in = TerminalInput()
        self.cmd_in.setPlaceholderText(t("login.command_placeholder"))
        self.btn_run_cmd = QPushButton(t("login.run_command") if t("login.run_command") != "[login.run_command]" else "Çalıştır")
        self.btn_run_cmd.clicked.connect(self.cmd_in.submit_current)
        self.cmd_in.command_submitted.connect(self.run_command_text)
        self.cmd_in.reconnect_requested.connect(self._prompt_reconnect)

        cmd_row = QHBoxLayout()
        cmd_row.addWidget(self.cmd_in)
        cmd_row.addWidget(self.btn_run_cmd)

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
        form.addRow(t("login.ssh_key") if t("login.ssh_key") != "[login.ssh_key]" else "SSH Anahtar", key_row)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_connect)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        action_row = QHBoxLayout()
        action_row.addWidget(self.btn_add_connection)
        action_row.addWidget(self.btn_connect)
        action_row.addStretch(1)
        right_lay.addLayout(action_row)
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
        self._console_log_lines: list[str] = []
        self._terminal_emulator = TerminalEmulator(columns=self._console_shell_geometry()[0], rows=self._console_shell_geometry()[1])
        self._terminal_emulation_enabled = True
        self._last_shell_geometry: tuple[int, int] | None = None
        self._connect_thread: QThread | None = None
        self._connect_worker: _ConnectionWorker | None = None
        self._connect_in_progress = False
        self._pending_old_ssh = None
        self._reconnect_prompt_open = False
        self._master_password_cache = ""
        self.console_message.connect(self._append_console_to_widget)
        self.shell_output_message.connect(self._append_shell_output_to_widget)
        self.ssh_disconnected.connect(self._handle_ssh_disconnected)

        self.refresh_profiles()
        self.btn_connect.setEnabled(False)
        self.cmd_in.set_connected(False)

    def shutdown_external_processes(self) -> None:
        """Called by MainWindow on app exit."""
        try:
            st = load_settings()
        except Exception:
            st = {}

        self._x11_runner.shutdown(
            close_x11_procs=bool(st.get("close_x11_procs_on_exit", True)),
            close_vcxsrv=bool(st.get("close_vcxsrv_on_exit", True)),
        )

        try:
            ssh = self._session.get("ssh") if hasattr(self, "_session") else None
            if ssh is not None:
                ssh.close()
        except Exception:
            pass

        # Wipe connection secrets from in-memory session (best-effort).
        try:
            cfg = self._session.get("cfg") if hasattr(self, "_session") else None
            if cfg is not None:
                try:
                    cfg.password = ""
                except Exception:
                    pass
            ssh = self._session.get("ssh") if hasattr(self, "_session") else None
            if ssh is not None and getattr(ssh, "info", None) is not None:
                try:
                    ssh.info.password = ""
                except Exception:
                    pass
        except Exception:
            pass

        self._master_password_cache = ""

    # ---- public helpers
    def append_console(self, msg: str) -> None:
        # Route writes through a Qt signal so background SSH reader threads
        # and QProcess callbacks stay on the GUI thread.
        try:
            self.console_message.emit(msg)
        except RuntimeError:
            pass

    def append_shell_output(self, msg: str) -> None:
        try:
            self.shell_output_message.emit(msg)
        except RuntimeError:
            pass

    def _render_console_view(self) -> None:
        try:
            lines = list(self._console_log_lines)
            terminal_text = ""
            if self._terminal_emulation_enabled:
                terminal_text = self._terminal_emulator.render().rstrip("\n")
            if terminal_text:
                if lines:
                    lines.append("")
                lines.extend(terminal_text.splitlines())
            text = "\n".join(lines)
            self.console.blockSignals(True)
            try:
                self.console.setPlainText(text)
                cursor = self.console.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                self.console.setTextCursor(cursor)
                self.console.ensureCursorVisible()
            finally:
                self.console.blockSignals(False)
        except Exception:
            pass

    def _append_log_line(self, msg: str) -> None:
        text = (msg or "").rstrip("\n")
        self._console_log_lines.extend(text.splitlines() or [""])
        self._render_console_view()

    def _append_console_to_widget(self, msg: str) -> None:
        # Guard against "Internal C++ object already deleted" during shutdown.
        try:
            if hasattr(self, "console") and shiboken6.isValid(self.console):
                self._append_log_line(msg)
        except RuntimeError:
            pass
        append_log(msg)

    def _append_shell_output_to_widget(self, msg: str) -> None:
        try:
            if not hasattr(self, "console") or not shiboken6.isValid(self.console):
                return
            if not self._terminal_emulation_enabled:
                self._append_log_line(msg)
                return
            self._terminal_emulator.feed(msg or "")
            self._render_console_view()
        except Exception as exc:
            self._terminal_emulation_enabled = False
            self._append_log_line(f"[terminal emulator disabled: {exc}]")
            fallback = (msg or "").rstrip("\n")
            if fallback:
                self._append_log_line(fallback)

    def eventFilter(self, obj, event) -> bool:
        try:
            if obj is getattr(self.console, "viewport", lambda: None)():
                if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                    self._sync_shell_geometry()
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _terminal_key_sequence(self, event) -> str | None:
        key = event.key()
        mods = event.modifiers()
        text = event.text() or ""

        if mods & Qt.KeyboardModifier.ControlModifier and text:
            ch = text.upper()[0]
            if "@" <= ch <= "_":
                return chr(ord(ch) - 64)

        special_map = {
            Qt.Key.Key_Return: "\r",
            Qt.Key.Key_Enter: "\r",
            Qt.Key.Key_Tab: "\t",
            Qt.Key.Key_Backtab: "\x1b[Z",
            Qt.Key.Key_Backspace: "\x7f",
            Qt.Key.Key_Escape: "\x1b",
            Qt.Key.Key_Left: "\x1b[D",
            Qt.Key.Key_Right: "\x1b[C",
            Qt.Key.Key_Up: "\x1b[A",
            Qt.Key.Key_Down: "\x1b[B",
            Qt.Key.Key_Home: "\x1b[H",
            Qt.Key.Key_End: "\x1b[F",
            Qt.Key.Key_Delete: "\x1b[3~",
            Qt.Key.Key_PageUp: "\x1b[5~",
            Qt.Key.Key_PageDown: "\x1b[6~",
            Qt.Key.Key_Insert: "\x1b[2~",
        }
        if key in special_map:
            return special_map[key]

        if len(text) == 1 and not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)):
            return text

        return None

    def _forward_console_key_event(self, event) -> bool:
        try:
            ssh = self._session.get("ssh") if hasattr(self, "_session") else None
            if not ssh:
                return False
            seq = self._terminal_key_sequence(event)
            if not seq:
                return False
            if hasattr(ssh, "send_shell_input") and ssh.send_shell_input(seq):
                event.accept()
                return True
        except Exception:
            pass
        return False

    def _console_shell_geometry(self) -> tuple[int, int]:
        try:
            viewport = self.console.viewport()
            size = viewport.size()
            fm = self.console.fontMetrics()
            char_width = max(1, fm.horizontalAdvance("M"))
            line_height = max(1, fm.lineSpacing())
            width = size.width()
            height = size.height()
            if width < char_width * 4 or height < line_height * 2:
                return (120, 40)
            cols = max(20, width // char_width)
            rows = max(5, height // line_height)
            return (cols, rows)
        except Exception:
            return (120, 40)

    def _sync_shell_geometry(self) -> None:
        try:
            ssh = self._session.get("ssh") if hasattr(self, "_session") else None
            if not ssh or not hasattr(ssh, "resize_shell_pty"):
                return
            cols, rows = self._console_shell_geometry()
            if self._last_shell_geometry == (cols, rows):
                return
            ssh.resize_shell_pty(cols, rows)
            try:
                self._terminal_emulator.resize(cols, rows)
            except Exception:
                pass
            self._last_shell_geometry = (cols, rows)
        except Exception:
            pass

    def _begin_connect_async(self, cfg: SSHConfig, old_ssh) -> bool:
        if self._connect_in_progress:
            return False
        self._connect_in_progress = True
        self._pending_old_ssh = old_ssh
        self._terminal_emulation_enabled = True
        try:
            cols, rows = self._console_shell_geometry()
            self._terminal_emulator.reset()
            self._terminal_emulator.resize(cols, rows)
        except Exception:
            pass
        self.btn_connect.setEnabled(False)
        self.btn_add_connection.setEnabled(False)
        self.status_label.setText("Bağlanılıyor")
        self.cmd_in.set_connected(False)

        thread = QThread(self)
        worker = _ConnectionWorker(
            cfg,
            self._console_shell_geometry(),
            self.append_console,
            self.append_shell_output,
            self._notify_ssh_disconnected,
        )
        self._connect_thread = thread
        self._connect_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_connect_finished)
        worker.failed.connect(self._on_connect_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_connect_thread_finished)
        thread.start()
        return True

    def _on_connect_thread_finished(self) -> None:
        self._connect_in_progress = False
        self._connect_thread = None
        self._connect_worker = None
        self._pending_old_ssh = None
        self.btn_add_connection.setEnabled(True)
        self.btn_connect.setEnabled(bool(self._selected_profile_name()))

    def _on_connect_finished(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        ssh = data.get("ssh")
        slurm = data.get("slurm")
        files = data.get("files")
        cfg = data.get("cfg")
        old_ssh = self._pending_old_ssh
        try:
            if old_ssh is not None and old_ssh is not ssh:
                try:
                    old_ssh.close()
                except Exception:
                    pass
            self._session = {"connected": True, "cfg": cfg, "ssh": ssh, "slurm": slurm, "files": files}
            self.status_label.setText(t("login.status_connected") if t("login.status_connected") != "[login.status_connected]" else "Bağlı")
            self.cmd_in.set_connected(True)
            self.append_console("SSH bağlantısı kuruldu.")
            self._sync_shell_geometry()
            try:
                self.console.setFocus()
            except Exception:
                pass
            if isinstance(cfg, SSHConfig):
                append_event({"type": "connect", "host": cfg.host, "user": cfg.username, "dry_run": cfg.dry_run})
            self.session_changed.emit(self._session)
        finally:
            self.btn_add_connection.setEnabled(True)
            self.btn_connect.setEnabled(bool(self._selected_profile_name()))

    def _on_connect_failed(self, message: str, exc: object) -> None:
        self.status_label.setText(t("login.status_disconnected") if t("login.status_disconnected") != "[login.status_disconnected]" else "Bağlı değil")
        self.cmd_in.set_connected(False)
        self.append_console(t("login.conn_error_prefix").format(err=message))
        if "SSH protocol banner" in message or "banner" in message.lower():
            self.append_console(
                "İpucu: SSH sunucusu banner döndürmeden önce gecikiyor olabilir; VPN/ağ, port ve uzak sshd erişimini kontrol edin."
            )
        show_exception(self, title=t("login.conn_error_title"), user_message=message, exc=exc if isinstance(exc, BaseException) else None, area="SSH")
        self.btn_add_connection.setEnabled(True)
        self.btn_connect.setEnabled(bool(self._selected_profile_name()))

    # ---- profiles
    def refresh_profiles(self, select_name: str | None = None) -> None:
        self.profiles_list.clear()
        self.btn_connect.setEnabled(False)
        profiles = load_profiles()
        for p in profiles:
            name = p.get("name", "")
            if name:
                self.profiles_list.addItem(name)
        if select_name:
            items = self.profiles_list.findItems(select_name, Qt.MatchFlag.MatchExactly)
            if items:
                self.profiles_list.setCurrentItem(items[0])

    def on_profile_selected(self) -> None:
        item = self.profiles_list.currentItem()
        if not item:
            self.btn_connect.setEnabled(False)
            return
        name = item.text()
        profiles = load_profiles()
        prof = next((p for p in profiles if p.get("name") == name), None)
        if not prof:
            self.btn_connect.setEnabled(False)
            return
        self._load_profile_into_fields(prof)
        self.btn_connect.setEnabled(True)

    def _ask_master_password(self, *, confirm: bool) -> str | None:
        """Ask user for a master password. Returns None if canceled."""
        if self._master_password_cache:
            return self._master_password_cache

        title = "Şifreleme Parolası"
        prompt = "Kaydedilen şifreleri şifrelemek/çözmek için bir ana parola girin."
        pw, ok = QInputDialog.getText(self, title, prompt, QLineEdit.EchoMode.Password)
        if not ok:
            return None
        pw = (pw or "").strip()
        if not pw:
            QMessageBox.warning(self, t("login.err_title"), t("login.err_master_empty"))
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
                QMessageBox.warning(self, t("login.err_title"), t("login.err_master_mismatch"))
                return None
        self._master_password_cache = pw
        return pw

    def _decrypt_saved_password(self, prof: dict) -> str | None:
        """Decrypt a saved password and retry if the cached master password is wrong."""
        token = prof.get("password_enc")
        salt = prof.get("password_salt")
        if not token or not salt:
            return ""

        used_cached_master = bool(self._master_password_cache)
        master = self._ask_master_password(confirm=False)
        if master is None:
            return None

        try:
            return decrypt_with_master(master, token, salt)
        except Exception:
            if used_cached_master:
                self._master_password_cache = ""
                master = self._ask_master_password(confirm=False)
                if master is None:
                    return None
                try:
                    return decrypt_with_master(master, token, salt)
                except Exception:
                    pass

        self._master_password_cache = ""
        QMessageBox.critical(self, t("login.err_title"), t("login.err_master_wrong"))
        return None

    def pick_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("login.ssh_key") if t("login.ssh_key") != "[login.ssh_key]" else "SSH Anahtar Seç")
        if path:
            self.key_path.setText(path)

    def _load_profile_into_fields(self, prof: dict) -> None:
        self.profile_name.setText(prof.get("name", ""))
        self.host.setText(prof.get("host", ""))
        self.port.setText(str(prof.get("port", 22)))
        self.username.setText(prof.get("username", ""))
        self.key_path.setText(prof.get("key_path", ""))
        self.cb_x11.setChecked(bool(prof.get("x11_forwarding", False)))
        self.cb_strict_hostkey.setChecked((prof.get("host_key_policy") or "accept-new") == "strict")
        # legacy field: prof.get("dry_run") ignored

        save_pw = bool(prof.get("save_password", False))
        self.cb_save_password.setChecked(save_pw)
        # Never auto-fill decrypted password.
        # If legacy plain password exists, show it; if encrypted, keep empty.
        if save_pw and isinstance(prof.get("password"), str) and prof.get("password"):
            self.password.setText(prof.get("password", ""))
        else:
            self.password.setText("")

    def _load_profile_by_name(self, name: str) -> dict | None:
        profiles = load_profiles()
        return next((p for p in profiles if p.get("name") == name), None)

    def open_add_connection_dialog(self) -> None:
        selected = self._selected_profile_name()
        initial = self._load_profile_by_name(selected) if selected else None
        dlg = ConnectionDialog(
            self,
            initial_profile=initial,
            on_save=self._save_profile_from_dialog,
            on_connect=self._save_and_connect_from_dialog,
        )
        dlg.exec()

    def open_edit_connection_dialog(self, profile_name: str | None = None) -> None:
        name = (profile_name or self._selected_profile_name()).strip()
        if not name:
            return
        initial = self._load_profile_by_name(name)
        if not initial:
            return
        dlg = ConnectionDialog(
            self,
            initial_profile=initial,
            on_save=self._save_profile_from_dialog,
            on_connect=self._save_and_connect_from_dialog,
        )
        dlg.setWindowTitle(t("connection.edit_dialog_title") if t("connection.edit_dialog_title") != "[connection.edit_dialog_title]" else "Edit Connection")
        self._editing_profile_original_name = name
        try:
            dlg.exec()
        finally:
            self._editing_profile_original_name = ""

    def _selected_profile_name(self) -> str:
        item = self.profiles_list.currentItem()
        return item.text().strip() if item else ""

    def show_profile_context_menu(self, pos) -> None:
        item = self.profiles_list.itemAt(pos)
        if not item:
            return
        self.profiles_list.setCurrentItem(item)
        menu = QMenu(self)
        act_connect = menu.addAction(t("login.connect") if t("login.connect") != "[login.connect]" else "Bağlan")
        act_edit = menu.addAction(t("connection.edit_action") if t("connection.edit_action") != "[connection.edit_action]" else "Edit")
        chosen = menu.exec(self.profiles_list.mapToGlobal(pos))
        if chosen == act_connect:
            self.connect_selected_profile()
            return
        if chosen == act_edit:
            self.open_edit_connection_dialog(item.text())

    def _on_profile_double_clicked(self, item) -> None:
        if item is None:
            return
        self.profiles_list.setCurrentItem(item)
        self.connect_selected_profile()

    def _save_profile_from_dialog(self, profile: dict) -> bool:
        self._load_profile_into_fields(profile)
        return self.save_profile()

    def _save_and_connect_from_dialog(self, profile: dict) -> bool:
        self._load_profile_into_fields(profile)
        if not self.save_profile():
            return False
        return self.connect_clicked()

    def connect_selected_profile(self) -> bool:
        name = self._selected_profile_name()
        if not name:
            return False
        prof = self._load_profile_by_name(name)
        if not prof:
            return False
        self._load_profile_into_fields(prof)
        return self.connect_clicked()

    def save_profile(self) -> bool:
        name = self.profile_name.text().strip()
        if not name:
            # auto name: user@host
            name = f"{self.username.text().strip()}@{self.host.text().strip()}"
            self.profile_name.setText(name)

        try:
            port = int(self.port.text().strip() or "22")
        except ValueError:
            QMessageBox.warning(self, t("login.err_title"), t("login.err_port_numeric"))
            return False

        prof = {
            "name": name,
            "host": self.host.text().strip(),
            "port": port,
            "username": self.username.text().strip(),
            "key_path": self.key_path.text().strip(),
            "host_key_policy": "strict" if self.cb_strict_hostkey.isChecked() else "accept-new",
            "x11_forwarding": self.cb_x11.isChecked(),
            # dry_run removed
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
                    return False
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
        original_name = getattr(self, "_editing_profile_original_name", "").strip()
        if original_name and original_name != name:
            delete_profile(original_name)
        self.refresh_profiles(select_name=name)
        append_event({"type": "profile_save", "name": name})
        self.append_console(f"Profil kaydedildi: {name}")
        return True

    # ---- connect / command
    def connect_clicked(self) -> bool:
        try:
            port = int(self.port.text().strip() or "22")
        except ValueError:
            QMessageBox.warning(self, t("login.err_title"), t("login.err_port_numeric"))
            return False

        old_ssh = self._session.get("ssh") if hasattr(self, "_session") else None

        # If password is not typed but profile has encrypted password, ask master and decrypt.
        password = self.password.text()
        if not password:
            name = (self.profile_name.text() or "").strip()
            if name:
                prof = next((p for p in load_profiles() if p.get("name") == name), None)
                if prof and prof.get("save_password") and prof.get("password_enc") and prof.get("password_salt"):
                    password = self._decrypt_saved_password(prof)
                    if password is None:
                        return False

        cfg = SSHConfig(
            host=self.host.text().strip(),
            port=port,
            username=self.username.text().strip(),
            password=password,
            key_path=self.key_path.text().strip(),
            host_key_policy=("strict" if self.cb_strict_hostkey.isChecked() else "accept-new"),
            x11_forwarding=self.cb_x11.isChecked(),
            dry_run=False,
        )

        if not cfg.host or not cfg.username:
            QMessageBox.warning(self, t("login.err_title"), t("login.err_host_user_required"))
            return False

        # X11 preflight: if X11 forwarding is enabled and the user asked for
        # auto dependency management, ensure plink and VcXsrv are available
        # BEFORE connecting.
        app_settings = load_settings()
        if cfg.x11_forwarding and (not cfg.dry_run) and bool(app_settings.get("x11_autodeps", True)):
            if not self._x11_runner.preflight(enabled=True, parent=self, allow_download=True):
                QMessageBox.warning(self, t("login.x11_title"), t("login.err_x11_plink_needed"))
                return False

        self.append_console(f"Bağlanılıyor: {cfg.username}@{cfg.host}:{cfg.port}")
        try:
            if cfg.dry_run:
                ssh = None
                slurm = MockSlurmBackend()
                files = MockFilesBackend()
                self.status_label.setText(t("login.status_mock") if t("login.status_mock") != "[login.status_mock]" else "Mock mod")
                self.append_console("Mock bağlantı aktif.")
            else:
                return self._begin_connect_async(cfg, old_ssh)
        except Exception as e:
            self.status_label.setText(t("login.status_disconnected") if t("login.status_disconnected") != "[login.status_disconnected]" else "Bağlı değil")
            self.append_console(t("login.conn_error_prefix").format(err=e))
            msg = str(e)
            if "SSH protocol banner" in msg or "banner" in msg.lower():
                self.append_console(
                    "İpucu: SSH sunucusu banner döndürmeden önce gecikiyor olabilir; VPN/ağ, port ve uzak sshd erişimini kontrol edin."
                )
            show_exception(self, title=t("login.conn_error_title"), user_message=str(e), exc=e, area="SSH")
            return False
        return True

    def run_command(self) -> None:
        # Button compatibility: TerminalInput handles history + clear
        if hasattr(self.cmd_in, 'submit_current'):
            self.cmd_in.submit_current()
            return
        cmd = self.cmd_in.text().strip()
        if not cmd:
            return
        self.cmd_in.clear()
        self.run_command_text(cmd)

    def run_command_text(self, cmd: str) -> None:
        cmd = (cmd or '').strip()
        if not cmd:
            return
        ssh = self._session.get("ssh")
        if not ssh or not self._session.get("connected", False):
            if cmd.lower() == "r":
                self._prompt_reconnect()
                return
            self.append_console("SSH bagli degil (Mock modda komut calistirilmaz).")
            return

        info = getattr(ssh, "info", None)
        if self._x11_runner.run_if_x11(info, cmd, parent=self):
            append_event({"type": "x11_cmd", "cmd": cmd})
            return

        # Normal terminal commands go through the live shell session.
        try:
            if hasattr(ssh, "send_shell_text") and ssh.send_shell_text(cmd):
                append_event({"type": "ssh_cmd", "cmd": cmd})
                return
            raise RuntimeError("interactive shell unavailable")
        except Exception as e:
            if self._session.get("connected", False):
                self._handle_ssh_disconnected(str(e) or "SSH bağlantısı kesildi.")
            self.append_console(t("login.cmd_error").format(err=e))

    def _notify_ssh_disconnected(self, reason: str) -> None:
        try:
            self.ssh_disconnected.emit(reason or "SSH bağlantısı kesildi.")
        except Exception:
            pass

    def _handle_ssh_disconnected(self, reason: str) -> None:
        if not self._session.get("connected", False):
            return
        self._session["connected"] = False
        self.status_label.setText(t("login.status_disconnected") if t("login.status_disconnected") != "[login.status_disconnected]" else "Bağlı değil")
        self.cmd_in.set_connected(False)
        notice = t("login.reconnect_notice").format(reason=reason or "")
        if notice != "[login.reconnect_notice]":
            self.append_console(notice)
        self.session_changed.emit(self._session)
        self._prompt_reconnect()

    def _prompt_reconnect(self) -> None:
        if self._connect_in_progress:
            return
        if self._session.get("connected", False):
            return
        if getattr(self, "_reconnect_prompt_open", False):
            return
        self._reconnect_prompt_open = True
        try:
            ans = QMessageBox.question(
                self,
                t("login.reconnect_prompt_title"),
                t("login.reconnect_prompt_message"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans == QMessageBox.StandardButton.Yes:
                self.append_console(t("login.reconnect_started"))
                self.connect_clicked()
        finally:
            self._reconnect_prompt_open = False

    def retranslate_ui(self):
        """Update user-facing texts when language changes."""
        try:
            self.cb_x11.setText(t("login.x11_enable"))
            self.cb_strict_hostkey.setText("Strict host key checking")
            # dry-run removed
            self.cb_save_password.setText(t("login.save_password"))
            self.btn_browse_key.setText(t("login.browse"))
            self.btn_save.setText(t("login.save"))
            self.console.setPlaceholderText(t("login.console_placeholder"))
            self.cmd_in.setPlaceholderText(t("login.command_placeholder"))
            self.btn_run_cmd.setText(t("login.run_command"))
            self.btn_add_connection.setText(t("login.add_connection"))
            self.btn_connect.setText(t("login.connect_selected"))
        except Exception:
            pass
