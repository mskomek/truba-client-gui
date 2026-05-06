# Changelog

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
