# Wave 007 — Test Command Orchestration

Status: proposed  
Owner: Codex  
Priority: P0

## Goal

Execute task-level validation commands deterministically so Builder and Tester decisions are grounded in real command results rather than model claims.

## Why This Wave Exists

Acceptance criteria are only useful if the required validation commands actually run. The system needs a controlled mechanism to read test commands from the active task, execute them safely, capture outputs, and feed the results back into reports and routing.

## Scope

In scope:
- parse required validation/test commands from the active task
- execute commands from the runner using controlled subprocess behavior
- capture exit codes, stdout, and stderr
- write command outputs into reports or log references
- ensure failed validation commands affect loop outcome
- support project-relevant commands such as pytest or smoke checks

Out of scope:
- distributed test execution
- parallel command execution
- remote TRUBA cluster job submission as part of the validation layer
- performance benchmarking framework
- MCP command routing

## Target Files

Primary targets:
- `runner/runner.py`
- `TASKS.md`
- `TESTING.md`
- `reports/BUILD_REPORT.md`
- `reports/TEST_REPORT.md`

Secondary targets only if required:
- `scripts/check_i18n.py`
- `scripts/smoke_test.py`
- `tests/`

## Non-Negotiable Rules

1. Validation commands must come from the active task contract, not ad hoc guessing.
2. Command execution must be explicit, logged, and reproducible.
3. Failed validation commands must influence task outcome.
4. The system must never treat “tests not run” as equivalent to “tests passed.”
5. Dangerous command execution patterns must be avoided.
6. Validation output must be available for Architect review through reports or logs.

## Required Architecture Changes

### A. Active-task validation command reader
Add a parser or structured reader that extracts required commands from the active task definition.

### B. Controlled command executor
Implement a safe subprocess execution layer with timeout, captured output, and non-silent failures.

### C. Report integration for command evidence
Make command results part of the persistent evidence used by Tester and Architect.

## Tasks

- [ ] Define how required commands are represented and read from the active task.
- [ ] Add a controlled subprocess execution path for validation commands.
- [ ] Capture and persist exit code, stdout, stderr, and timeout/error state.
- [ ] Decide where command logs live and reference them from reports if needed.
- [ ] Ensure failed commands are surfaced in Builder and Tester evidence.
- [ ] Update prompts or reports so models can read real command evidence.
- [ ] Add at least one project-relevant validation path using existing test or smoke commands.

## Validation

- [ ] Run a task whose validation command succeeds and confirm the success is recorded.
- [ ] Run a task whose validation command fails and confirm the failure is recorded and affects routing.
- [ ] Confirm command output is visible in reports or linked logs.
- [ ] Confirm timeout/error behavior is visible and deterministic.
- [ ] Confirm “no test command found” is handled explicitly rather than silently ignored.

## Done Criteria

This wave is done only when:

1. Required validation commands can be read from the active task and executed by the runner.
2. Success and failure outcomes are persisted as evidence.
3. Builder/Tester flow is grounded in real command results, not only model narrative.
4. The implementation supports at least one real project validation command path.

## Possible Blockers

- Task formatting may not yet represent validation commands consistently.
- Existing scripts/tests may need minor normalization for deterministic runner use.
- Long-running commands may require timeout tuning.

## On Completion

- move this file to `waves/done/`
- update `ACTIVE_WAVE.md` / `CURRENT_WAVE.md`
- activate the next planned wave
