# Wave 001 — Codex Architect Bootstrap

Status: proposed  
Owner: Codex  
Priority: P0

## Goal

Bootstrap Codex as a repository-aware Architect that reads the workflow documents, selects the active wave, and produces the next smallest verifiable task without implementing code.

## Why This Wave Exists

After the documentation foundation exists, the next critical step is to make Codex behave consistently as the planning and supervision layer. The system should not yet depend on full runner automation; however, Codex must already be able to:
- understand the repository control files,
- select work from the active wave,
- break waves into concrete tasks,
- update task-facing control documents,
- route execution toward Builder.

Without this wave:
- Codex may continue to act as a general coding assistant instead of a constrained Architect.
- Waves will remain static documents instead of actionable execution units.
- Task slicing quality will vary from session to session.
- Later Builder/Tester integration will not have reliable task definitions to consume.

## Scope

In scope:
- Define the Codex-side operating pattern for Architect behavior.
- Establish prompt and document expectations for task planning.
- Ensure Codex can read active wave docs and generate the next task.
- Normalize how `TASKS.md` is written or updated.
- Define routing expectations from Architect to Builder.

Out of scope:
- Full automatic loop orchestration.
- Builder implementation execution.
- Tester execution.
- MCP integration.
- Large source-code modifications unrelated to workflow bootstrap.

## Target Files

Primary targets:
- `AGENTS.md`
- `TASKS.md`
- `ACTIVE_WAVE.md`
- `CURRENT_WAVE.md`
- `PHASE_PLAN.md`
- `MASTER_CONTEXT_ACTIVE.md`
- `runner/prompts/architect.md`
- `waves/active/`
- `waves/pending/`

Secondary targets only if required:
- `README_AGENT_WORKFLOW.md`
- `rules.md`
- `SESSION_RULES.md`
- `reports/WAVE_REPORT.md`

## Non-Negotiable Rules

1. Codex must not implement production code as part of Architect behavior.
2. Architect output must always target the smallest verifiable next task.
3. `TASKS.md` must remain the canonical active task surface.
4. Architect must define allowed files and clear acceptance criteria for each task.
5. Architect must operate within the currently active wave only.
6. Architect must not silently expand scope into future waves.
7. Any ambiguity that blocks task slicing must be surfaced explicitly.

## Required Architecture Changes

### A. Architect operating contract
Define exactly how Codex should behave when entering the repository: what to read first, what not to change, and what output to produce.

### B. Task generation contract
Define the canonical task structure inside `TASKS.md`, including task ID, goal, allowed files, forbidden files, acceptance criteria, and routing.

### C. Wave-to-task bridge
Make the active wave actionable by ensuring its contents can be translated into task-level execution steps.

### D. Prompt bootstrap surface
Add or normalize a repository prompt file that reinforces Architect-only behavior outside of chat memory.

## Tasks

- [ ] Review the active wave flow and identify the minimal information Codex must always read before planning.
- [ ] Normalize `AGENTS.md` so Architect behavior is explicit and prominent.
- [ ] Create or normalize `runner/prompts/architect.md` as a reusable Architect bootstrap prompt.
- [ ] Define the canonical `TASKS.md` task structure for this repository.
- [ ] Ensure `CURRENT_WAVE.md` and `ACTIVE_WAVE.md` guide Codex toward a single active wave.
- [ ] Add or refine routing language so Architect hands work to Builder without implementing it.
- [ ] Confirm the docs do not require unavailable automation features yet.
- [ ] Leave clear completion notes if any remaining ambiguity must be deferred to later waves.

## Validation

- [ ] Codex can determine the active wave by reading repository docs.
- [ ] Codex can generate a task entry in `TASKS.md` with acceptance criteria and file boundaries.
- [ ] The task format is consistent and reusable.
- [ ] Architect instructions explicitly forbid implementation.
- [ ] The active wave/task model is understandable without extra chat context.
- [ ] The repository contains an Architect prompt surface outside ad hoc terminal usage.

## Done Criteria

This wave is done only when:

1. Codex can reliably act as Architect in this repository.
2. A consistent task generation structure exists in `TASKS.md`.
3. The bridge from active wave to active task is documented and usable.
4. The system is ready for the next wave, where the runner loop begins consuming the planned task structure.

## Possible Blockers

- Existing task formats may conflict with the stricter Architect task schema.
- The active wave documents may be too vague and require light refinement.
- Prompt duplication between docs may need consolidation to avoid drift.

## On Completion

- Move this file to `waves/done/`.
- Mark the next wave as active in `ACTIVE_WAVE.md` and `CURRENT_WAVE.md`.
- Set the next wave to `wave_002_runner_loop_foundation.md`.
