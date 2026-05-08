# Changelog

## v1.1.0
- Connection: removed Start Tour from the normal flow and added a dedicated Add Connection dialog plus a Settings dialog for app-level options.
- Connection console: improved login output, prompt rendering, PTY resize handling, and interactive shell routing.
- Terminal rendering: added ANSI/VT emulation so redraw, cursor movement, box drawing, and dialog-style screens render more correctly.
- Navigation: fixed saved session context editing, prevented unwanted auto-switching back to the Connection tab, and improved directory double-click plus parent-folder navigation.
- Jobs: split the Jobs area into clearer sub-tabs for accounting/details and outputs.
- Localization: fixed Turkish i18n encoding issues so translated strings render correctly.
- X11 and logs: improved X server startup checks, download flow, logging, and shutdown safety.

## 2026-01-31
- Fix: Prevent starting a second VcXsrv instance when the display port is already listening.
- X11: When X11 forwarding is enabled, GUI commands launched from the `SSH$` prompt now use the system `ssh/plink` path instead of Paramiko so apps open as separate Windows X11 windows.
- X11: Remote commands are wrapped in `bash -lc 'unset LD_LIBRARY_PATH; ...'` to avoid environment-related symbol conflicts such as `libXrender/_XGetRequest`.
- Standalone support: Added `services/xserver_manager.py` to automatically start portable VcXsrv from `~/.truba_slurm_gui/third_party/vcxsrv/XWin.exe` when no X server is available.
- Standalone X11: Removed the assumption that VcXsrv only exposes `XWin.exe`; the app now discovers `vcxsrv.exe/XWin.exe` entry points, including `third_party/vcxsrv/vcxsrv.exe` and `third_party/vcxsrv/runtime/vcxsrv.exe`, and starts them with the correct working directory.
- Logs: Added persistent log writing to `~/.truba_slurm_gui/app.log` and added a Logs tab.
- Logs: Added a Copy button to the Logs tab.
- Security: When saving a profile with "Remember password" enabled, the plain-text password is no longer written to the config; it is encrypted with PBKDF2+Fernet using a user-entered master password and stored as `password_enc` + `password_salt`.
- Security: If the password field is empty during connection and the profile has `password_enc`, the app now prompts for the master password and decrypts it for the connection.
- X11: Added a download plus silent install flow for VcXsrv from GitHub Releases when no X server is present, with user consent.
- X11: `xserver_manager` now offers a download prompt when `XWin.exe` is missing and auto-starts when it is available.
- X11: `x11_widget` and `login_widget` now call local X server checks with download support before X11 commands.
- Fix: Defined the missing `_log` callback in `X11Widget` for logging during X server download and startup.
- Fix: Replaced `QTextCursor.End` usage in the Logs tab for PySide6 compatibility.
- Fix: Made `LoginWidget.append_console` safe against `QTextEdit already deleted` errors triggered by `QProcess` signals during shutdown.
- Fix: Prevented crashes when `X11Widget` closes while a process finishes by guarding `QLabel` validity.
- Fix: Reduced false-positive X server detection by verifying that the X server process exists when port 6000 is open.

## v1.0.3

- Windows EXE hotfix: fixed `ModuleNotFoundError: No module named 'PySide6'` at startup by rebuilding with PySide6/shiboken6 available in the build environment.
- Rebuilt release artifacts and refreshed packaged `CHANGELOG.txt`.

## v1.0.2

- Added ARF-side quick action to create/edit Slurm scripts from templates in Directories.
- Added template selection flow (core/CPU/GPU/MPI) and file naming prompt before opening in Script Editor.
- Added `Save + Submit` action in Script Editor.
- On save of `.slurm/.sbatch`, app now asks whether to submit with `sbatch`.
- Added pre-save script checks (shebang, `#SBATCH`, placeholder/time/output hints).
- Added lint action in Script Editor for quick static checks.
- Improved `sbatch` error diagnostics with actionable hints for account/QOS/time/CPU/GPU issues.
- After successful submit, parsed Job ID now auto-focuses Jobs & Outputs.
- Added template override search via `TRUBA_TEMPLATE_DIR` and `~/.truba_slurm_gui/templates`.
- Updated the Generic Slurm help library with detailed tutorial content (TR/EN).

## v1.0.1

- X11 flow refactored into a dedicated `X11Runner`.
- Added Slurm accounting and job detail actions (`sacct`, `scontrol show job`).
- Added host key policy option (`accept-new` / `strict`) for SSH profiles.
- Added diagnostics bundle export from Logs tab.
- Added transfer operation journal (`transfer_journal.jsonl`).
- Added CI checks (compile, i18n key drift, smoke test).
- Added Windows release automation workflow.

## v1.0.0

- Initial public release.
