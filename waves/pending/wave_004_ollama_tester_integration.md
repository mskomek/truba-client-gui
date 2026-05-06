# Wave 004 — Ollama Tester Integration

Status: proposed  
Owner: Codex  
Priority: P0

## Goal

Integrate the Tester role with Ollama so the active task can be verified against acceptance criteria and return a stable PASS / FAIL / BLOCKED outcome.

## Why This Wave Exists

Builder output alone is not enough. The workflow depends on a separate verification step that does not modify code, inspects the same acceptance criteria, and produces a parseable routing decision.

This wave establishes Tester as an isolated verification role with a durable report format.

## Scope

In scope:

- add Tester prompt assembly from active task and build report context
- call Ollama for the Tester role
- capture stdout/stderr and exit behavior
- define a stable PASS / FAIL / BLOCKED result contract
- write `reports/TEST_REPORT.md`
- make Tester output parseable by the runner

Out of scope:

- full retry policy optimization
- MCP exposure
- advanced browser automation
- broad architecture refactors unrelated to Tester integration
- final end-to-end dry-run coverage beyond the Tester step itself

## Target Files

Primary targets:
- `runner/runner.py`
- `runner/prompts/tester.md`
- `reports/TEST_REPORT.md`

Secondary targets only if required:
- `reports/BUILD_REPORT.md`
- `agent_state.json`
- `TASKS.md`
- `TESTING.md`
- `runner/logs/`

## Non-Negotiable Rules

1. Tester must never modify code.
2. Tester must verify against the active task acceptance criteria.
3. Tester output must end in exactly one route class: PASS, FAIL, or BLOCKED.
4. Tester output must be durable enough for resume after interruption.
5. This wave must not add MCP behavior.

## Required Architecture Changes

### A. Add Tester prompt assembly
Build a deterministic prompt using repo rules, active task criteria, and current build report context.

### B. Add Ollama Tester execution
Run the configured local Tester model through a controlled subprocess path.

### C. Standardize result parsing
Extract one final result token: PASS, FAIL, or BLOCKED.

### D. Add Tester report persistence
Always write a test report including result, evidence, and routing decision.

## Tasks

- [ ] Add Tester execution path to `runner/runner.py`
- [ ] Create or refine `runner/prompts/tester.md`
- [ ] Load acceptance criteria and relevant build context into the Tester prompt
- [ ] Add controlled Ollama subprocess execution for the Tester model
- [ ] Capture stdout/stderr from Tester runs
- [ ] Parse the final Tester result as PASS, FAIL, or BLOCKED
- [ ] Write `reports/TEST_REPORT.md` after each Tester attempt
- [ ] Record Tester result details in runner logs
- [ ] Update state handling if needed so the runner can act on Tester outcome
- [ ] Move this wave to `waves/done/` when complete

## Validation

- [ ] Confirm the Tester prompt is assembled from active repo state
- [ ] Confirm Ollama Tester execution starts from the runner
- [ ] Confirm the result contract is exactly PASS, FAIL, or BLOCKED
- [ ] Confirm `reports/TEST_REPORT.md` is written every run
- [ ] Confirm Tester does not require code mutation to perform validation
- [ ] Confirm the runner can parse Tester output without ambiguity

## Done Criteria

This wave is done only when:

1. The runner can invoke the Tester model through Ollama.
2. Tester reads active criteria and build context from repo files.
3. Tester writes a durable report on every run.
4. PASS / FAIL / BLOCKED can be parsed reliably.
5. The project is ready for full Builder/Tester loop completion in the next wave.

## Possible Blockers

- acceptance criteria formatting in `TASKS.md` may need normalization for reliable parsing
- large Builder outputs may need summarized handoff into the Tester prompt
- ambiguous Tester responses may require stricter prompt constraints

## On Completion

- update `ACTIVE_WAVE.md`
- mark this wave complete
- set the next wave to `wave_005_builder_tester_loop_completion.md`
- move this file to `waves/done/`
