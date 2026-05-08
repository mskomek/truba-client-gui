# TESTING.md

## Goal

Validation must be explicit, narrow, and tied to the active task.

## Common Checks In This Repo

### Existing automated test
- `python -m unittest tests/test_editor_flow.py`

### Repo validation scripts
- `python scripts/check_i18n.py`
- `python scripts/smoke_test.py`

### Lightweight checks when relevant
- import checks
- syntax / compile checks
- narrow reasoning-based inspection for Windows-specific behavior when the environment cannot execute the real flow

## Evidence Rule

Do not report PASS without recording:
- exact commands run
- concise result summary
- failures if any

## External Dependency Rule

Return `BLOCKED` when the task depends on something unavailable, for example:
- real TRUBA connectivity
- Windows-only runtime/tooling not present in the environment
- external binaries such as `plink.exe` or `VcXsrv`
- packaging/signing prerequisites

## Task-Level Guidance

Prefer the smallest sufficient check set.

Examples:
- UI/editor logic task -> run `tests/test_editor_flow.py`
- i18n task -> run `scripts/check_i18n.py`
- packaging script task -> run the safest dry-run or inspection available
- runner-managed validation tasks should use explicit, non-recursive commands
  that do not invoke `runner/runner.py` while validation is already in progress

Workflow-doc task guidance:
- validate JSON state with `python -m json.tool agent_state.json`
- review active wave, current wave, and task files for consistent wave IDs, task IDs, and allowed-file lists
- confirm the Architect prompt output fields match the task contract fields
