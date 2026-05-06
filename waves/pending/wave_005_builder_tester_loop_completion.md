# Wave 005 — Builder/Tester Loop Completion

Status: proposed  
Owner: Codex  
Priority: P0

## Goal

Complete the deterministic Builder → Tester → Architect loop so a single active task can move through PASS, FAIL, and BLOCKED outcomes without manual file editing.

## Why This Wave Exists

Waves 002–004 establish the runner foundation and individual Ollama integrations, but the system still does not behave like a real multi-agent loop until outcomes are interpreted and routed correctly. This wave turns the separate pieces into one usable workflow.

## Scope

In scope:
- implement end-to-end loop transitions between Builder, Tester, and Architect
- parse standardized Tester outcomes (`PASS`, `FAIL`, `BLOCKED`)
- update `agent_state.json` after each step
- support controlled retry flow when Tester returns `FAIL`
- support controlled escalation back to Architect when Tester returns `BLOCKED`
- persist iteration counters and last-result metadata
- allow the loop to resume from the last active role after interruption

Out of scope:
- MCP server integration
- advanced recovery for corrupted reports
- parallel task execution
- multiple active waves
- automatic Architect invocation through Codex CLI or API

## Target Files

Primary targets:
- `runner/runner.py`
- `agent_state.json`
- `TASKS.md`
- `reports/BUILD_REPORT.md`
- `reports/TEST_REPORT.md`

Secondary targets only if required:
- `runner/prompts/builder.md`
- `runner/prompts/tester.md`
- `TESTING.md`

## Non-Negotiable Rules

1. The system must continue to support exactly one active wave and one active task.
2. The loop must never silently skip a Tester result.
3. `PASS`, `FAIL`, and `BLOCKED` must be handled explicitly and deterministically.
4. Resume behavior must come from file state, not chat state or process memory.
5. No automatic scope redefinition is allowed inside Builder or Tester logic.
6. If parsing fails, the loop must stop in a visible and debuggable way.

## Required Architecture Changes

### A. Explicit loop transition layer
Add a dedicated decision point in the runner that maps Tester results to the next role and state transition.

### B. Persistent task progress metadata
Extend runtime state so the system records at least the active role, active task id, iteration count, and last outcome.

### C. Interrupt-safe resume behavior
Ensure the runner can restart and continue from persistent state without manual reconstruction of the current step.

## Tasks

- [ ] Implement deterministic route handling for `PASS`, `FAIL`, and `BLOCKED`.
- [ ] Add/update state fields required for loop continuity and debugging.
- [ ] Make the runner persist state after each major transition.
- [ ] Add a safe stop behavior when required reports are missing or malformed.
- [ ] Ensure `PASS` returns control to Architect-facing state for the next task.
- [ ] Ensure `FAIL` routes back to Builder without changing task scope.
- [ ] Ensure `BLOCKED` routes back to Architect for scope/dependency resolution.
- [ ] Add at least one interruption/resume test path or smoke validation path.
- [ ] Update documentation if the runtime contract changes.

## Validation

- [ ] Start with a prepared active task and simulate a `PASS` result; verify state advances correctly.
- [ ] Start with a prepared active task and simulate a `FAIL` result; verify the task returns to Builder.
- [ ] Start with a prepared active task and simulate a `BLOCKED` result; verify the task returns to Architect.
- [ ] Stop the runner mid-cycle and restart; verify it resumes from persisted state.
- [ ] Confirm malformed or missing Tester output causes a visible failure rather than silent progression.

## Done Criteria

This wave is done only when:

1. A single active task can move through Builder and Tester with correct deterministic routing.
2. `agent_state.json` is sufficient to resume the loop after interruption.
3. The runner visibly handles invalid outcome parsing instead of guessing.
4. PASS/FAIL/BLOCKED behavior is documented, testable, and confirmed.

## Possible Blockers

- The current report format may be too loose to parse reliably.
- The existing state file may need a schema update.
- Builder or Tester prompts may need tightening to guarantee exact output markers.

## On Completion

- move this file to `waves/done/`
- update `ACTIVE_WAVE.md` / `CURRENT_WAVE.md`
- activate `wave_006_task_safety_guardrails.md`
