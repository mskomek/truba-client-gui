# Changelog

## 2026-05-08
- Connection: removed the Start Tour from the normal flow and added a dedicated Add Connection dialog plus a Settings dialog for app-level options.
- Connection console: improved login output, prompt rendering, PTY resize handling, and interactive shell routing.
- Terminal rendering: added ANSI/VT emulation so redraw, cursor movement, box drawing, and dialog-style screens render more correctly.
- Navigation: fixed saved session context editing, prevented unwanted auto-switching back to the Connection tab, and improved directory double-click plus parent-folder navigation.
- Jobs: split the Jobs area into clearer sub-tabs for accounting/details and outputs.
- Localization: fixed Turkish i18n encoding issues so translated strings render correctly.

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
- Updated Generic Slurm help library with detailed tutorial content (TR/EN).

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
