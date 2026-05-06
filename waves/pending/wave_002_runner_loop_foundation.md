# Wave 002 — Runner Loop Foundation

Status: proposed  
Owner: Codex  
Priority: P0

## Goal

Create the first deterministic orchestration loop for the TRUBA agent workflow so the project can resume by state and move cleanly between Architect, Builder, and Tester roles.

## Why This Wave Exists

The repository already has the documentation structure for wave-driven execution, but the workflow is not yet enforced by runnable orchestration code.

Before Builder, Tester, or MCP integration can be trusted, the runner must exist as a small, state-driven control loop with explicit role transitions and safe stop/resume behavior.

## Scope

In scope:

- create the first `runner/runner.py`
- load and validate `agent_state.json`
- detect the active wave and active task
- route between `ARCHITECT`, `BUILDER`, and `TESTER`
- define safe stop behavior for missing files or invalid state
- support resume from the last known role without re-initializing unrelated state
- write structured loop logs under `runner/logs/`

Out of scope:

- real Ollama model execution
- MCP server implementation
- Codex invocation automation
- rich TUI/GUI controls for the runner
- advanced retry policies beyond basic deterministic routing

## Target Files

Primary targets:
- `runner/runner.py`
- `agent_state.json`

Secondary targets only if required:
- `TASKS.md`
- `CURRENT_WAVE.md`
- `ACTIVE_WAVE.md`
- `runner/logs/`
- `README_AGENT_WORKFLOW.md`

## Non-Negotiable Rules

1. The runner must remain small, readable, and restart-safe.
2. State must live in files, not implicit runtime memory.
3. The runner must not mutate source code under `src/` in this wave.
4. Missing or malformed state must fail clearly instead of silently resetting.
5. Role transitions must be explicit and logged.

## Required Architecture Changes

### A. Create a minimal orchestration entry point
Add a first `runner/runner.py` that can be executed directly and that owns workflow control.

### B. Centralize state loading and validation
The runner must parse `agent_state.json`, verify required keys, and reject invalid values early.

### C. Add deterministic role transition handling
Implement a small decision layer that resolves the next action from the current role and last known result.

### D. Add safe logging
Write human-readable logs for each runner step so interruptions and failures can be diagnosed quickly.

## Tasks

- [ ] Create `runner/runner.py` with a minimal CLI entry point
- [ ] Add state loading for `agent_state.json`
- [ ] Validate required keys such as current wave, current task, role, iteration, and last result
- [ ] Load active task context from `TASKS.md` or fail clearly if unavailable
- [ ] Add explicit role dispatch for `ARCHITECT`, `BUILDER`, and `TESTER`
- [ ] Add a first deterministic transition map for PASS / FAIL / BLOCKED handling
- [ ] Add log file creation under `runner/logs/`
- [ ] Add safe exit behavior for malformed state or missing task context
- [ ] Document the runner entry command if needed
- [ ] Move this wave to `waves/done/` when complete

## Validation

- [ ] Confirm `runner/runner.py` imports cleanly
- [ ] Confirm the runner can read `agent_state.json`
- [ ] Confirm the runner fails clearly on malformed or incomplete state
- [ ] Confirm the runner logs the current role and next action
- [ ] Confirm the runner can resume from a non-empty iteration value
- [ ] Confirm no files under `src/` are modified by this wave

## Done Criteria

This wave is done only when:

1. `runner/runner.py` exists and can execute as the workflow entry point.
2. The runner reads state from files and routes by role deterministically.
3. Invalid state causes a clear controlled stop.
4. Basic logs are written for every run attempt.
5. No Ollama or MCP behavior is required for this wave.

## Possible Blockers

- existing repo path assumptions may conflict with the new runner location
- current task parsing rules may need to be tightened before deterministic loading is possible
- `agent_state.json` may require normalization before the runner can validate it strictly

## On Completion

- update `ACTIVE_WAVE.md`
- mark this wave complete
- set the next wave to `wave_003_ollama_builder_integration.md`
- move this file to `waves/done/`
