# Changelog

## v1.1.9
- FTP: added a plain FTP backend, configurable default local folder and startup remote panel, and normal-download targeting of the current local panel.
- FTP transfers: added retry for selected failed transfers, selected-item queue removal, live parallelism changes, recursive folder downloads, and safer per-transfer backend sessions.
- Directories: added multi-field search for remote panels, closable directory tabs, local Delete/Home/End/Page key handling, and focused F5 refresh behavior.
- Jobs outputs: added independent follow tabs/windows for output and error files, editable followed paths, and menu targets for assigning files into existing follow views.
- Slurm submission: added settings for whether sbatch switches to Outputs and where parsed output/error files should open after submission.
- Interface: removed remaining fallback UI strings from updated menus, settings, transfer tables, and file panels in Turkish and English.

## v1.1.8
- FTP transfers: fixed configured parallel transfers so multiple uploads or downloads can run at the same time instead of staying sequential.
- FTP transfers: added an embedded progress bar with percentage in the Transfers table and hid internal local setup steps from the visible queue.
- FTP transfers: verified local FTP upload, parallel download, and visible partial-file resume behavior with a temporary FTP server.
- Directories: added Ctrl+C, Ctrl+X, and Ctrl+V support for local and remote file panels, including local-to-remote upload paste and remote-to-local download paste.
- Directories: made the remote path field editable so pressing Enter navigates to the typed path, and Backspace in the remote file list moves to the parent directory.

## v1.1.7
- Directories: added data-aware sorting for Name, Size, Type, and Modified columns while keeping parent and folder rows in the expected positions.
- Live output: kept Output 1 and Output 2 pinned to the newest content during live follow while preserving manual scrolling when follow is paused.
- Live output: reduced SSH and fallback output loading to the latest 200 lines per file.

## v1.1.6
- Connection profiles: grouped TRUBA directories and Slurm commands as editable per-profile system defaults.
- Authentication: allowed profiles without a username or password and added an option to reuse saved Windows-protected credentials without prompting until the profile is edited.
- Activity control: paused `squeue`, `tail`, `lssrv`, accounting, and log refresh operations while their tabs are not visible.
- Responsiveness: moved remote polling and command execution off the GUI thread, prevented overlapping requests, and reduced duplicate SSH/log rendering work.
- Connection console: added right-click paste from the system clipboard into the live SSH shell.
- Directories: added a context-menu action to copy the full remote path including the file name.
- Directories: added New Folder and New File buttons plus a right-click New submenu for creating remote items in the current or selected directory.
- Jobs files: added a refresh button to the Files subtab and F5 refresh support for file panels in Jobs and Directories.

## v1.1.5
- Connection profiles: grouped TRUBA directories and Slurm commands as editable per-profile system defaults.
- Authentication: allowed profiles without a username or password and added an option to reuse saved Windows-protected credentials without prompting until the profile is edited.
- Activity control: paused `squeue`, `tail`, `lssrv`, accounting, and log refresh operations while their tabs are not visible.
- Responsiveness: moved remote polling and command execution off the GUI thread, prevented overlapping requests, and reduced duplicate SSH/log rendering work.

## v1.1.4
- Interface: added the current version to the top bar and switched Jobs, Accounting, `lssrv`, and terminal output areas to dark monospace rendering.
- Updates: added automatic startup checks, a visible download/install progress dialog, and stable versionless release asset names.
- Localization: completed the Turkish and English UI text audit and translated previously hardcoded interface messages.
- Live output: improved Output 1 and Output 2 following with one-second refresh, missing-file retries, automatic bottom scrolling, and a 500-line limit.
- Output controls: added per-panel search plus pause and resume controls without losing the active followed files.
- Job monitoring: added Windows notifications for completed and failed Slurm jobs.

## v1.1.3
- Jobs files: added translated context-menu actions to follow any selected file in Output 1 or Output 2, with independent active sources for both panels.
- Jobs outputs: keep retrying Slurm output and error files while they are waiting to be created.
- Live output: refresh followed files every second, automatically scroll to the newest content, and load at most the latest 500 lines.

## v1.1.2
- Updates: added an in-app GitHub Releases update check, SHA256-verified ZIP download, automatic Windows restart/install flow, install logging, and rollback protection.
- Releases: GitHub Actions now publishes the versioned onedir ZIP and SHA256 as GitHub Release assets.

## v1.1.1
- Jobs outputs: resolved Slurm `%x`, `%j`, and `%A` placeholders so parsed output and error files are followed with `tail`.
- Jobs files: fixed the Output-1 and Output-2 context-menu actions to switch to Outputs, load immediately, and continue live polling.
- Saved profiles: cached the encryption master password only in memory for the application session, cleared it on shutdown, and re-prompted when a profile uses a different master password.

## v1.1.0
- Connection: removed Start Tour from the normal flow and added a dedicated Add Connection dialog plus a Settings dialog for app-level options.
- Saved profiles: added direct connection on double-click and a Connect action to the context menu.
- Connection console: improved login output, prompt rendering, PTY resize handling, and interactive shell routing.
- Terminal rendering: added ANSI/VT emulation so redraw, cursor movement, box drawing, and dialog-style screens render more correctly.
- Navigation: fixed saved session context editing, prevented unwanted auto-switching back to the Connection tab, and improved directory double-click plus parent-folder navigation.
- Jobs: split the Jobs area into clearer Job Details, Files, and Outputs sub-tabs.
- Jobs refresh: added a configurable refresh interval with a 15-second default and an optional persisted setting to refresh `lssrv` on the same timer.
- TRUBA status: added refreshable `lssrv` output with terminal-style rendering in Job Details.
- Slurm submission: added a translated Directories context-menu action for remote `.slurm` and `.sbatch` files.
- Slurm submission: changed SSH-backed `sbatch` execution to run from the remote script's parent directory.
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
