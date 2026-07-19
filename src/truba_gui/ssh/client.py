from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import socket

from truba_gui.core.debug_support import timed

import paramiko

from truba_gui.core.logging import get_logger
from truba_gui.services.command_history_store import is_sensitive_command


_ACS_MAP = {
    "j": "┘",
    "k": "┐",
    "l": "┌",
    "m": "└",
    "n": "┼",
    "q": "─",
    "t": "├",
    "u": "┤",
    "v": "┴",
    "w": "┬",
    "x": "│",
    "o": "█",
    "s": "·",
    "a": "▒",
    "f": "°",
    "g": "±",
    "h": "␋",
    "i": "␌",
    "`": "◆",
}


def _sanitize_terminal_text(text: str) -> str:
    """Remove terminal control sequences and normalize redraw-heavy output."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    alt_charset = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        code = ord(ch)
        if ch == "\x1b" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "[":
                i += 2
                while i < n and not ("@" <= text[i] <= "~"):
                    i += 1
                i += 1
                continue
            if nxt in "()":
                if i + 2 < n:
                    spec = nxt + text[i + 2]
                    if spec in ("(0", ")0"):
                        alt_charset = True
                    elif spec in ("(B", ")B"):
                        alt_charset = False
                i += 3
                continue
            if nxt in "PX^_":
                i += 2
                while i < n:
                    if text[i] == "\x1b" and i + 1 < n and text[i + 1] == "\\":
                        i += 2
                        break
                    i += 1
                continue
            if "@" <= nxt <= "_":
                i += 2
                continue
            i += 1
            continue
        if ch in ("\x0e", "\x0f"):
            alt_charset = ch == "\x0e"
            i += 1
            continue
        if code < 32 and ch not in ("\n", "\t"):
            i += 1
            continue
        if alt_charset and ch in _ACS_MAP:
            out.append(_ACS_MAP[ch])
        else:
            out.append(ch)
        i += 1
    return "".join(out)


@dataclass
class SSHConnInfo:
    host: str
    port: int
    username: str = ""
    password: str = ""
    key_path: str = ""
    host_key_policy: str = "accept-new"  # accept-new | strict
    x11_forwarding: bool = False  # UI flag; actual X11 is handled separately


class SSHClientWrapper:
    def __init__(
        self,
        info: Optional[SSHConnInfo] = None,
        logger: Optional[Callable[[str], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        shell_output_cb: Optional[Callable[[str], None]] = None,
        disconnect_cb: Optional[Callable[[str], None]] = None,
    ):
        # Accept both `logger` and legacy `log_cb` kwarg.
        # Also allow passing SSHConnInfo as first positional arg (info).
        self.info: Optional[SSHConnInfo] = info
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp = None
        self._shell_channel = None
        self._shell_thread: Optional[threading.Thread] = None
        self._shell_stop = threading.Event()
        self._shell_geometry: Tuple[int, int] = (120, 40)
        self._log = logger or log_cb
        self._shell_output_cb = shell_output_cb
        self._disconnect_cb = disconnect_cb
        self._filelog = get_logger("truba_gui.ssh")

    def log(self, msg: str) -> None:
        # File log
        try:
            self._filelog.info(msg)
        except Exception:
            pass
        # UI log (if provided)
        if self._log:
            try:
                self._log(msg)
            except Exception:
                pass

    def connect(
        self,
        info: Optional[SSHConnInfo] = None,
        *,
        shell_size: Optional[Tuple[int, int]] = None,
    ) -> None:
        info = info or self.info
        if info is None:
            raise ValueError('SSH connection info not provided')
        target = f"{info.username}@{info.host}" if info.username else info.host
        self.log(f"SSH: connecting to {target}:{info.port} ...")
        self.client = paramiko.SSHClient()
        policy = (getattr(info, "host_key_policy", "accept-new") or "accept-new").strip().lower()
        if policy == "strict":
            try:
                self.client.load_system_host_keys()
            except Exception:
                pass
            self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
            self.log("SSH: host key policy = strict")
        else:
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.log("SSH: host key policy = accept-new")

        if info.key_path:
            self.log(f"SSH: using key {info.key_path}")
            pkey = paramiko.RSAKey.from_private_key_file(info.key_path)
            self.client.connect(
                hostname=info.host,
                port=info.port,
                username=info.username or None,
                pkey=pkey,
                timeout=15,
                banner_timeout=30,
                auth_timeout=30,
                channel_timeout=30,
                allow_agent=True,
                look_for_keys=True,
            )
        else:
            self.client.connect(
                hostname=info.host,
                port=info.port,
                username=info.username or None,
                password=info.password or None,
                timeout=15,
                banner_timeout=30,
                auth_timeout=30,
                channel_timeout=30,
                allow_agent=True,
                look_for_keys=True,
            )
        transport = self.client.get_transport()
        if transport is not None:
            banner = transport.get_banner()
            if banner:
                if isinstance(banner, bytes):
                    banner = banner.decode(errors="replace")
                self.log(str(banner).rstrip("\r\n"))
        if shell_size is not None:
            cols, rows = shell_size
            self._shell_geometry = (max(1, int(cols)), max(1, int(rows)))
        self._start_shell_session()
        self.sftp = self.client.open_sftp()
        self.log("SSH: connected, SFTP ready")

    def _start_shell_session(self) -> None:
        if not self.client:
            return
        self._stop_shell_session()
        try:
            transport = self.client.get_transport()
            if transport is None or not transport.is_active():
                return
            cols, rows = self._shell_geometry
            channel = self.client.invoke_shell(term="xterm", width=cols, height=rows)
            try:
                channel.settimeout(0.2)
            except Exception:
                pass
        except Exception as exc:
            self.log(f"SSH: interactive shell unavailable ({exc})")
            return

        self._shell_channel = channel
        self._shell_stop = threading.Event()
        self._shell_thread = threading.Thread(
            target=self._shell_reader_loop,
            args=(channel,),
            name="truba_gui_ssh_shell",
            daemon=True,
        )
        self._drain_initial_shell_output(channel)
        self._shell_thread.start()
        self.log("SSH: interactive shell session started")

    def resize_shell_pty(self, cols: int, rows: int) -> None:
        cols = max(1, int(cols))
        rows = max(1, int(rows))
        self._shell_geometry = (cols, rows)
        channel = self._shell_channel
        if channel is None:
            return
        try:
            channel.resize_pty(width=cols, height=rows)
        except Exception:
            pass

    def send_shell_text(self, text: str) -> bool:
        channel = self._shell_channel
        if channel is None or getattr(channel, "closed", False):
            return False
        payload = (text or "").rstrip("\r\n")
        if not payload:
            return True
        try:
            sent = channel.send(payload + "\n")
            return sent > 0
        except Exception:
            return False

    def send_shell_input(self, data: str) -> bool:
        channel = self._shell_channel
        if channel is None or getattr(channel, "closed", False):
            return False
        payload = data or ""
        if not payload:
            return True
        try:
            sent = channel.send(payload)
            return sent > 0
        except Exception:
            return False

    def _drain_initial_shell_output(self, channel, duration: float = 0.35) -> None:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline and not self._shell_stop.is_set():
            try:
                if not channel.recv_ready():
                    time.sleep(0.05)
                    continue
                data = channel.recv(4096)
                if not data:
                    break
                self._handle_shell_output(data.decode(errors="replace"))
            except socket.timeout:
                continue
            except Exception:
                break

    def _shell_reader_loop(self, channel) -> None:
        unexpected_disconnect = False
        disconnect_reason = ""
        while not self._shell_stop.is_set():
            try:
                if channel.recv_ready():
                    data = channel.recv(4096)
                    if data:
                        self._handle_shell_output(data.decode(errors="replace"))
                    continue
                if getattr(channel, "closed", False) or channel.exit_status_ready():
                    unexpected_disconnect = True
                    disconnect_reason = "SSH shell session ended."
                    break
            except socket.timeout:
                continue
            except Exception as exc:
                if not self._shell_stop.is_set():
                    self.log(f"SSH: shell session read failed ({exc})")
                    unexpected_disconnect = True
                    disconnect_reason = str(exc)
                break
            time.sleep(0.1)
        if unexpected_disconnect and not self._shell_stop.is_set():
            try:
                self.close()
            except Exception:
                pass
            self._notify_disconnect(disconnect_reason or "SSH shell session ended.")

    def _handle_shell_output(self, text: str) -> None:
        if not text:
            return
        if self._shell_output_cb is not None:
            try:
                self._shell_output_cb(text)
                return
            except Exception:
                pass
        sanitized = _sanitize_terminal_text(text)
        if sanitized.strip():
            self.log(sanitized.rstrip("\n"))

    def _stop_shell_session(self) -> None:
        self._shell_stop.set()
        channel = self._shell_channel
        self._shell_channel = None
        thread = self._shell_thread
        self._shell_thread = None
        try:
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
        finally:
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                try:
                    thread.join(timeout=1.0)
                except Exception:
                    pass

    def _notify_disconnect(self, reason: str) -> None:
        if not self._disconnect_cb:
            return
        try:
            self._disconnect_cb(reason or "SSH bağlantısı kesildi.")
        except Exception:
            pass

    def close(self) -> None:
        self.log("SSH: closing")
        try:
            self._stop_shell_session()
        except Exception:
            pass
        try:
            if self.sftp:
                self.sftp.close()
        finally:
            self.sftp = None
        try:
            if self.client:
                self.client.close()
        finally:
            self.client = None
        self.log("SSH: closed")

    def open_transfer_sftp(self):
        """Open an isolated SFTP channel for one upload or download.

        The browsing channel in ``self.sftp`` is deliberately shared by the
        UI.  Paramiko SFTP clients are not safe to use from several transfer
        worker threads, so file transfers must obtain their own channel from
        the already authenticated transport instead.
        """
        if self.client is None:
            raise RuntimeError("SSH client not connected")
        transport = self.client.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("SSH transport is not active")
        is_authenticated = getattr(transport, "is_authenticated", None)
        if callable(is_authenticated) and not is_authenticated():
            raise RuntimeError("SSH transport is not authenticated")
        return paramiko.SFTPClient.from_transport(transport)

    def supports_transfer_sftp_channels(self) -> bool:
        """Probe whether the active connection can create isolated channels."""
        channel = None
        try:
            channel = self.open_transfer_sftp()
            return True
        except Exception:
            return False
        finally:
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass

    def run(
        self,
        command: str,
        *,
        timeout_s: Optional[float] = None,
        log_output: bool = True,
    ) -> Tuple[int, str, str]:
        if not self.client:
            raise RuntimeError("SSH client not connected")
        t0 = timed()
        # Never echo secrets into the UI/logs.
        if is_sensitive_command(command):
            self.log("SSH$ <redacted>")
        else:
            self.log(f"SSH$ {command}")
        stdin, stdout, stderr = self.client.exec_command(command)
        if timeout_s is not None:
            try:
                stdout.channel.settimeout(timeout_s)
                stderr.channel.settimeout(timeout_s)
            except Exception:
                pass
        try:
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            code = stdout.channel.recv_exit_status()
            timed_out = False
        except socket.timeout:
            out = ""
            err = ""
            code = 124
            timed_out = True
        if log_output and out.strip():
            self.log(_sanitize_terminal_text(out).rstrip("\n"))
        if log_output and err.strip():
            self.log("STDERR:\n" + _sanitize_terminal_text(err).rstrip("\n"))
        dt = timed() - t0
        if timed_out:
            self.log(f"[timeout after {dt:.1f}s exit={code}]")
        else:
            self.log(f"[exit={code} duration={dt:.2f}s]")
        return code, out, err
