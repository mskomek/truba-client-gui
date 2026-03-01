from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QProcess

from truba_gui.core.i18n import t
from truba_gui.services.putty_manager import ensure_plink_available
from truba_gui.services.x11_system_ssh import (
    build_x11_launch,
    is_likely_x11_gui_command,
    is_likely_x11_related_command,
    wrap_remote_cmd_clean_env,
)
from truba_gui.services.xserver_manager import ensure_x_server_running, stop_x_server_started_by_app


class X11Runner:
    """Single-responsibility X11 execution manager.

    Handles:
    - dependency preflight (plink + local X server)
    - command routing for likely X11 commands
    - QProcess lifecycle + cleanup
    """

    def __init__(self, *, log_cb: Callable[[str], None], parent=None):
        self._log = log_cb
        self._parent = parent
        self._bg_procs: list[QProcess] = []

    def preflight(self, *, enabled: bool, parent=None, allow_download: bool = True) -> bool:
        if not enabled:
            return True
        p = parent or self._parent
        if not ensure_plink_available(log=self._log, parent=p):
            return False
        if not ensure_x_server_running(self._log, parent=p, allow_download=allow_download):
            return False
        return True

    def should_handle(self, info, cmd: str) -> bool:
        if not info:
            return False
        x11_enabled = bool(getattr(info, "x11_forwarding", False))
        if not x11_enabled:
            return False
        return bool(is_likely_x11_gui_command(cmd) or is_likely_x11_related_command(cmd))

    def run_if_x11(self, info, cmd: str, *, parent=None) -> bool:
        if not self.should_handle(info, cmd):
            return False

        p = parent or self._parent
        if not ensure_x_server_running(self._log, parent=p, allow_download=True):
            self._log("X11: Yerel X server (VcXsrv) baslatilamadi.")
            return True

        remote_cmd = wrap_remote_cmd_clean_env(cmd)
        launch = build_x11_launch(
            host=info.host,
            port=info.port,
            user=info.username,
            remote_cmd=remote_cmd,
            trusted=True,
            key_path=(getattr(info, "key_path", None) or None),
            password=(getattr(info, "password", None) or None),
            host_key_policy=(getattr(info, "host_key_policy", "accept-new") or "accept-new"),
        )
        if not launch:
            self._log(
                "X11 baslatici bulunamadi. Windows'ta plink.exe (PuTTY) gerekli.\n"
                "Standalone modda program plink.exe'yi kullanici dizinine indirir:\n"
                " - ~/.truba_slurm_gui/third_party/putty/plink.exe"
            )
            return True

        proc = QProcess(p)
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

        cmd_show = " ".join([launch.program] + launch.args)

        def _on_finished(code, _status):
            self._log(t("login.x11_finished").format(code=code))
            try:
                self._bg_procs.remove(proc)
            except Exception:
                pass
            try:
                from truba_gui.services.process_registry import unregister

                pid = int(proc.processId() or 0)
                if pid:
                    unregister(pid)
            except Exception:
                pass

        def _on_started():
            try:
                from truba_gui.services.process_registry import register

                pid = int(proc.processId() or 0)
                if pid:
                    register(pid, kind=f"x11_{launch.backend}", cmd=cmd_show)
            except Exception:
                pass

        proc.finished.connect(_on_finished)
        proc.started.connect(_on_started)
        self._log(t("login.x11_started").format(cmd=cmd_show))
        self._bg_procs.append(proc)
        proc.start()
        return True

    def shutdown(self, *, close_x11_procs: bool, close_vcxsrv: bool) -> None:
        if close_x11_procs:
            for p in list(self._bg_procs):
                try:
                    if p.state() != QProcess.ProcessState.NotRunning:
                        p.terminate()
                        p.waitForFinished(1000)
                except Exception:
                    pass
                try:
                    from truba_gui.services.process_registry import unregister

                    pid = int(p.processId() or 0)
                    if pid:
                        unregister(pid)
                except Exception:
                    pass
            self._bg_procs.clear()

        if close_vcxsrv:
            try:
                stop_x_server_started_by_app(log=self._log)
            except Exception:
                pass

    def _append_process_io(self, proc: QProcess, *, err: bool) -> None:
        data = bytes(proc.readAllStandardError() if err else proc.readAllStandardOutput()).decode(errors="replace")
        if not data.strip():
            return
        if err:
            self._log(t("login.stderr").format(data=data.rstrip()))
        else:
            self._log(data.rstrip())
