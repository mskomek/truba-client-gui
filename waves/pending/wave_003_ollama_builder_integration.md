# Wave 003 — Ollama Builder Integration

Status: proposed  
Owner: Codex  
Priority: P0

## Goal

Integrate the Builder role with Ollama so the active task can be executed through a controlled local model call and produce a stable build report.

## Why This Wave Exists

The workflow cannot progress beyond planning until Builder becomes runnable. The local Builder model is intended to be the cheap implementation engine, but it must be invoked through a strict, repeatable interface instead of free-form manual prompting.

This wave turns the Builder role into a deterministic local execution step.

## Scope

In scope:

- add Builder prompt assembly from active task files
- call Ollama for the Builder role
- capture stdout/stderr and exit behavior
- add timeout handling for Builder runs
- write `reports/BUILD_REPORT.md`
- persist enough metadata for the runner to continue after interruption

Out of scope:

- Tester integration
- PASS / FAIL / BLOCKED routing finalization
- MCP exposure
- multi-model fallback logic
- advanced sandboxing beyond the current repo rules

## Target Files

Primary targets:
- `runner/runner.py`
- `runner/prompts/builder.md`
- `reports/BUILD_REPORT.md`

Secondary targets only if required:
- `agent_state.json`
- `TASKS.md`
- `README_AGENT_WORKFLOW.md`
- `runner/logs/`

## Non-Negotiable Rules

1. Builder must implement only the active task.
2. Builder prompt assembly must read task scope and acceptance criteria from repository files.
3. Ollama execution must be wrapped with timeout and error handling.
4. Builder output must be persisted to a report file even on failure.
5. This wave must not implement Tester or MCP behavior.

## Required Architecture Changes

### A. Add Builder prompt assembly
Create a deterministic way to combine repo rules, active task context, and Builder instructions.

### B. Add Ollama subprocess execution
Run the configured local Builder model through a controlled subprocess call.

### C. Add Builder report persistence
Always write a build report with model output, command details, and execution outcome.

### D. Preserve runner continuity
Store enough result metadata so the workflow can resume without losing Builder state.

## Tasks

- [ ] Add Builder execution path to `runner/runner.py`
- [ ] Create or refine `runner/prompts/builder.md`
- [ ] Load active task content and allowed-file context into the Builder prompt
- [ ] Add controlled Ollama subprocess execution for the Builder model
- [ ] Add timeout handling and visible failure reporting
- [ ] Capture stdout/stderr from Builder runs
- [ ] Write `reports/BUILD_REPORT.md` after each Builder attempt
- [ ] Record Builder outcome details in runner logs
- [ ] Update state handling if needed so interrupted runs can resume cleanly
- [ ] Move this wave to `waves/done/` when complete

## Validation

- [ ] Confirm the Builder prompt is generated from repo state rather than ad hoc text
- [ ] Confirm Ollama Builder execution starts from the runner
- [ ] Confirm timeout or subprocess failure is reported clearly
- [ ] Confirm `reports/BUILD_REPORT.md` is written on success and failure
- [ ] Confirm Builder output is recoverable after interruption
- [ ] Confirm no Tester-only or MCP-only code is introduced here

## Done Criteria

This wave is done only when:

1. The runner can invoke the Builder model through Ollama.
2. The Builder prompt is assembled from repository files and active task context.
3. A build report is written every time Builder runs.
4. Failures are explicit and logged.
5. The workflow is ready for Tester integration in the next wave.

## Possible Blockers

- local Ollama model naming may differ from the assumed Builder model
- active task parsing may need cleanup before prompt assembly is reliable
- long outputs may require truncation or summary rules for report stability

## On Completion

- update `ACTIVE_WAVE.md`
- mark this wave complete
- set the next wave to `wave_004_ollama_tester_integration.md`
- move this file to `waves/done/`
