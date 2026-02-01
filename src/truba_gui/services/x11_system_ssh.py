from __future__ import annotations

"""X11 forwarding helper.

Hedef
- X11 forwarding seçiliyken `xclock`, `matlab` gibi GUI komutları çalıştırıldığında,
  pencere Windows'ta (yerel X server üzerinde) **ayrı bir pencere** olarak açılsın.
- TrubaGUI içinde yeni sekme/terminal açılmasın.

Neden Paramiko değil?
- Paramiko ile X11 forwarding mümkün olsa da (request_x11 + xauth + kanal/pty),
  pratikte kırılgan ve env farklarına açık. MobaXterm / PuTTY davranışına en yakın
  yaklaşım, sistem `ssh` veya `plink` ile `-X/-Y` kullanmaktır.
"""

import os
import platform
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class X11Launch:
    program: str
    args: List[str]
    backend: str  # ssh | plink


def _package_root() -> Path:
    # .../truba_gui/services/x11_system_ssh.py -> .../truba_gui
    return Path(__file__).resolve().parents[1]


def _bundled_ssh() -> Optional[str]:
    p = _package_root() / "third_party" / "openssh" / "ssh.exe"
    return str(p) if p.exists() else None


def _bundled_plink() -> Optional[str]:
    p = _package_root() / "third_party" / "putty" / "plink.exe"
    return str(p) if p.exists() else None


def _find_ssh_program() -> Optional[str]:
    if platform.system().lower() == "windows":
        return _bundled_ssh() or shutil.which("ssh")
    return shutil.which("ssh")


def _find_plink_program() -> Optional[str]:
    if platform.system().lower() == "windows":
        return _bundled_plink() or shutil.which("plink")
    return shutil.which("plink")


def wrap_remote_cmd_clean_env(cmd: str) -> str:
    """Run remote cmd in a login shell and avoid LD_LIBRARY_PATH issues.

    Bu, sende görülen `libXrender ... undefined symbol _XGetRequest` gibi
    env kaynaklı çakışmaları azaltır.
    """
    # Use bash -lc to behave like an interactive login-ish environment
    # and unset LD_LIBRARY_PATH to prevent custom libs from breaking X libs.
    safe = cmd.replace("'", "'\''")
    # TERM warning: some clusters emit "TERM environment variable needs set" if shell rc uses tput.
    # Also unset LD_PRELOAD and LD_LIBRARY_PATH to avoid X11 lib symbol mismatches.
    return f"bash -lc 'export TERM=xterm; unset LD_LIBRARY_PATH; unset LD_PRELOAD; {safe}'"


def is_likely_x11_related_command(cmd: str) -> bool:
    """Commands that *need* X11 forwarding even if they don't open a GUI directly."""
    low = cmd.strip().lower()
    if not low:
        return False
    # Simple heuristics used for diagnostics.
    needles = ["$display", "xauth", "xdpyinfo", "xset", "xprop", "xhost"]
    return any(n in low for n in needles)


def is_likely_x11_gui_command(cmd: str) -> bool:
    s = cmd.strip()
    if not s:
        return False
    # allow explicit "x11:" prefix in future (not used now)
    low = s.lower()
    first = low.split()[0]
    gui_markers = {
        "xclock", "xeyes", "xterm", "xcalc", "xlogo",
        "matlab", "firefox", "gedit", "nautilus", "gimp",
        "paraview", "ansys", "fluent", "workbench",
    }
    if first in gui_markers:
        return True
    if first.startswith("x"):
        return True
    # Qt apps frequently: endswith .sh etc; keep conservative
    return False


def build_x11_launch(
    host: str,
    port: int,
    user: str,
    remote_cmd: str,
    *,
    trusted: bool = True,
    key_path: Optional[str] = None,
    password: Optional[str] = None,
) -> Optional[X11Launch]:
    """Build a system command to launch remote X11 app."""

    # If password auth is used, prefer plink on Windows (OpenSSH will prompt on a hidden console and hang).
    plink_prog = _find_plink_program()
    if platform.system().lower() == "windows" and password and plink_prog:
        args = ["-ssh", "-X", "-P", str(port), "-batch", "-pw", password]
        if key_path:
            args += ["-i", key_path]
        args.append(f"{user}@{host}")
        args.append(remote_cmd)
        return X11Launch(plink_prog, args, "plink")

    # Prefer OpenSSH if available.
    ssh_prog = _find_ssh_program()
    if ssh_prog:
        flag = "-Y" if trusted else "-X"
        args: List[str] = [flag, "-C", "-p", str(port)]
        # Make failures explicit and non-interactive by default
        args += ["-o", "ExitOnForwardFailure=yes", "-o", "ForwardX11=yes", "-o", "StrictHostKeyChecking=accept-new"]
        if password:
            # Don't attempt password auth here; it will prompt in a hidden console.
            args += ["-o", "BatchMode=yes"]
        if key_path:
            args += ["-i", key_path]
        args.append(f"{user}@{host}")
        args.append(remote_cmd)
        return X11Launch(ssh_prog, args, "ssh")

    if plink_prog:
        # plink supports -X for X11; -ssh is implied in modern versions but add
        args = ["-ssh", "-X", "-P", str(port), "-batch"]
        if password:
            args += ["-pw", password]
        if key_path:
            # PuTTY uses -i for private key (.ppk)
            args += ["-i", key_path]
        args.append(f"{user}@{host}")
        args.append(remote_cmd)
        return X11Launch(plink_prog, args, "plink")

    return None
