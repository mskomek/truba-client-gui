# rules.md

Last updated: 2026-05-06

## Mission

This repository exists to make real **TRUBA / Slurm / SSH** workflows easier to execute from a desktop GUI without hiding what the system is doing.

The application must remain useful for:
- connection setup
- remote file browsing and editing
- Slurm script preparation
- job submission
- queue / accounting inspection
- diagnostics and troubleshooting
- optional X11 launch workflows

## Architecture Rules

### UI must stay thin
- widgets and dialogs should focus on interaction and display
- heavy logic should move into `services/`, `ssh/`, `config/`, or `core/`
- Slurm command composition or parsing should not be buried in UI classes when it can be reused elsewhere

### Services should stay explicit
- remote file operations belong in file services
- Slurm operations belong in Slurm services
- external process helpers belong in dedicated service modules
- parsing logic should be reusable and testable

### External tools must stay visible
The application may rely on external tools such as:
- `plink.exe`
- `VcXsrv`
- SSH subsystem tools

When those tools are used:
- commands should be understandable
- stderr should not be silently swallowed
- logs should help explain what failed

## Responsiveness Rule

Long-running operations must not freeze the GUI.

Examples:
- SSH connect
- remote directory load
- file upload/download
- `sbatch`, `squeue`, `sacct`
- X11 helper startup
- packaging helpers if surfaced through the app

## Logging and Diagnostics

- Silent failure is unacceptable.
- Logs should help reconstruct user-visible failures.
- Error dialogs should contain actionable clues when possible.
- Startup and shutdown paths should remain defensive.

## Security and Secrets

- never commit credentials, private keys, tokens, or real secrets
- never hardcode TRUBA host credentials
- local persistence changes must remain reviewable
- commands can be logged, but secrets must not leak into logs

## i18n Rule

Visible UI strings should use the language resource system.
If a task adds new visible strings, update both language files consistently unless the task explicitly limits scope.

## Testing Rule

Every task must define checks.
Common checks for this repo include:
- `python -m unittest tests/test_editor_flow.py`
- `python scripts/check_i18n.py`
- `python scripts/smoke_test.py`
- import / syntax checks
- narrow manual reasoning for Windows-only flows when platform execution is unavailable

Do not claim success without recording what was checked.

## Scope Control

- prefer narrow diffs
- do not mix release work with UI logic changes unless required
- do not touch `third_party/` assets unless the task explicitly requires it
- do not edit docs, tests, and source together unless the task truly needs all of them

## Wave Discipline

- only one wave is active at a time
- tasks come from the active wave only
- future-wave ideas go into future wave docs, not into current implementation
