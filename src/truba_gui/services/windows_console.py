from __future__ import annotations

"""Hidden console helper for Windows.

plink.exe is a console application. When launched from a GUI process without an
attached console, it can fail with:

    "Failed to open terminal."

To keep TrubaGUI fully standalone (and avoid flashing a console window), we
allocate a console once and immediately hide it.
"""

import platform


_CONSOLE_READY = False


def ensure_hidden_console() -> None:
    global _CONSOLE_READY
    if _CONSOLE_READY:
        return
    if platform.system().lower() != "windows":
        return

    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32

        # If there is already a console, GetConsoleWindow will be non-null.
        hwnd = k32.GetConsoleWindow()
        if not hwnd:
            k32.AllocConsole()
            hwnd = k32.GetConsoleWindow()

        # Hide it.
        if hwnd:
            SW_HIDE = 0
            u32.ShowWindow(hwnd, SW_HIDE)

        _CONSOLE_READY = True
    except Exception:
        # Best-effort: if this fails, plink may still work on some systems.
        return
