# Wave 006 — Task Safety Guardrails

Status: proposed  
Owner: Codex  
Priority: P0

## Goal

Prevent Builder execution from drifting outside task scope by enforcing allowed-file boundaries, detecting unexpected diffs, and failing loudly when the task contract is violated.

## Why This Wave Exists

Local Builder models are useful but can easily overreach. Even a good prompt is not enough by itself. The runner needs mechanical safeguards so task boundaries are enforced by the system, not just requested in natural language.

## Scope

In scope:
- inspect file changes after Builder execution
- compare changed files against task-level allowed/forbidden rules
- detect unrelated file modifications
- block hidden scope creep and broad refactors
- surface violations in reports and loop decisions
- integrate the safety checks into runner flow

Out of scope:
- git branch orchestration
- worktree isolation
- sandbox/container enforcement
- MCP permissions
- semantic code-diff correctness analysis beyond file-level scope

## Target Files

Primary targets:
- `runner/runner.py`
- `TASKS.md`
- `reports/BUILD_REPORT.md`
- `reports/TEST_REPORT.md`

Secondary targets only if required:
- `AGENTS.md`
- `rules.md`
- `TESTING.md`

## Non-Negotiable Rules

1. Builder must not modify files outside the active task contract.
2. File-scope violations must be treated as real failures, not warnings.
3. The safety layer must remain deterministic and easy to debug.
4. The system must never auto-approve extra changes because they “seem related.”
5. Forbidden file modifications must always be surfaced clearly in reports.
6. Safety checks must not depend on chat memory or manual inspection.

## Required Architecture Changes

### A. Task file-boundary contract
Ensure the active task definition contains enough structure for the runner to identify allowed and forbidden file sets.

### B. Post-build diff inspection
Add a diff-check phase after Builder execution and before final routing.

### C. Violation-aware reporting
Record file-scope violations in the generated reports so Architect and Tester can reason from the same evidence.

## Tasks

- [ ] Define or normalize how allowed and forbidden file rules are read from the active task.
- [ ] Add a changed-file inspection step using a deterministic repository diff command.
- [ ] Compare modified paths against allowed-file rules.
- [ ] Detect forbidden-file modifications explicitly.
- [ ] Add clear failure messages and report entries for scope violations.
- [ ] Ensure the loop does not proceed as normal when safety checks fail.
- [ ] Decide and implement whether safety violations route to Builder or Architect.
- [ ] Add/update validation instructions for file-boundary enforcement.

## Validation

- [ ] Run a task that changes only allowed files; confirm the guardrail layer passes.
- [ ] Run a task that changes at least one forbidden file; confirm the system flags the violation.
- [ ] Run a task that changes an unrelated file not listed in allowed files; confirm the system blocks progression.
- [ ] Confirm violation details are written into `BUILD_REPORT.md` and/or `TEST_REPORT.md`.
- [ ] Confirm the loop outcome is deterministic when file-boundary enforcement fails.

## Done Criteria

This wave is done only when:

1. File-boundary rules from the active task are enforced mechanically.
2. Builder cannot silently progress after changing forbidden or unrelated files.
3. Scope violations appear in reports with enough detail for debugging.
4. The resulting behavior is stable across repeat runs.

## Possible Blockers

- Active task format may not yet expose allowed/forbidden files consistently.
- Repository diff commands may need project-specific assumptions.
- Some generated or temporary files may need explicit handling to avoid false positives.

## On Completion

- move this file to `waves/done/`
- update `ACTIVE_WAVE.md` / `CURRENT_WAVE.md`
- activate `wave_007_test_command_orchestration.md`
