from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import socket

from truba_gui.core.debug_support import timed

import paramiko

from truba_gui.core.logging import get_logger
from truba_gui.services.command_history_store import is_sensitive_command


@dataclass
class SSHConnInfo:
    host: str
    port: int
    username: str
    password: str = ""
    key_path: str = ""
    x11_forwarding: bool = False  # UI flag; actual X11 is handled separately


class SSHClientWrapper:
    def __init__(
        self,
        info: Optional[SSHConnInfo] = None,
        logger: Optional[Callable[[str], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ):
        # Accept both `logger` and legacy `log_cb` kwarg.
        # Also allow passing SSHConnInfo as first positional arg (info).
        self.info: Optional[SSHConnInfo] = info
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp = None
        self._log = logger or log_cb
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

    def connect(self, info: Optional[SSHConnInfo] = None) -> None:
        info = info or self.info
        if info is None:
            raise ValueError('SSH connection info not provided')
        self.log(f"SSH: connecting to {info.username}@{info.host}:{info.port} ...")
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if info.key_path:
            self.log(f"SSH: using key {info.key_path}")
            pkey = paramiko.RSAKey.from_private_key_file(info.key_path)
            self.client.connect(
                hostname=info.host,
                port=info.port,
                username=info.username,
                pkey=pkey,
                timeout=15,
                allow_agent=True,
                look_for_keys=True,
            )
        else:
            self.client.connect(
                hostname=info.host,
                port=info.port,
                username=info.username,
                password=info.password,
                timeout=15,
                allow_agent=True,
                look_for_keys=True,
            )
        self.sftp = self.client.open_sftp()
        self.log("SSH: connected, SFTP ready")

    def close(self) -> None:
        self.log("SSH: closing")
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

    def run(self, command: str, *, timeout_s: Optional[float] = None) -> Tuple[int, str, str]:
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
        if out.strip():
            self.log(out.rstrip())
        if err.strip():
            self.log("STDERR:\n" + err.rstrip())
        dt = timed() - t0
        if timed_out:
            self.log(f"[timeout after {dt:.1f}s exit={code}]")
        else:
            self.log(f"[exit={code} duration={dt:.2f}s]")
        return code, out, err
