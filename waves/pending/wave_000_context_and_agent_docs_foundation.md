# Wave 000 — Context and Agent Docs Foundation

Status: proposed  
Owner: Codex  
Priority: P0

## Goal

Establish the repository-level context, control documents, and operational rules required for a Codex Architect + Ollama Builder/Tester workflow.

## Why This Wave Exists

The later waves depend on a stable documentation and control surface. Before any runner loop, Ollama integration, or MCP bridge is added, the repository must expose a clear and minimal set of documents that define scope, routing, task ownership, and persistence rules.

Without this foundation:
- Codex may infer the wrong role and start implementing code directly.
- Builder and Tester may drift outside their intended responsibilities.
- State may fragment across prompts, terminal history, and ad hoc notes.
- Future waves will not have a single canonical place to read architecture, phase intent, and active execution context.

## Scope

In scope:
- Create or normalize the repository control documents used by the agent workflow.
- Define role boundaries for Architect, Builder, Tester, and Human.
- Define persistent workflow files for waves, tasks, reports, and state.
- Establish a minimal active context surface for Codex to read on each run.
- Ensure the repository exposes a single active wave and a deterministic execution model.

Out of scope:
- Implementing the runner loop.
- Invoking Ollama models.
- Adding MCP integration.
- Performing production code refactors unrelated to agent workflow setup.
- Building full automation or orchestration logic.

## Target Files

Primary targets:
- `AGENTS.md`
- `MASTER_CONTEXT_ACTIVE.md`
- `rules.md`
- `SESSION_RULES.md`
- `ACTIVE_WAVE.md`
- `CURRENT_WAVE.md`
- `WAVES.md`
- `PHASE_PLAN.md`
- `TASKS.md`
- `TESTING.md`
- `ARCHITECTURE.md`
- `agent_state.json`
- `reports/BUILD_REPORT.md`
- `reports/TEST_REPORT.md`
- `reports/WAVE_REPORT.md`

Secondary targets only if required:
- `README_AGENT_WORKFLOW.md`
- `waves/active/`
- `waves/pending/`
- `waves/done/`
- `runner/prompts/`

## Non-Negotiable Rules

1. Codex must be positioned as Architect / supervisor, not as the default implementer.
2. Builder must be described as implementation-only.
3. Tester must be described as verification-only and must not modify code.
4. Workflow state must live in repository files, not only in chat history or terminal memory.
5. Only one active wave may exist at a time.
6. Documents must be concise, readable, and aligned with the real repository structure.
7. This wave must not introduce fake automation that is not yet implemented.

## Required Architecture Changes

### A. Repository control surface
Create a minimal but complete set of markdown and json files that define the workflow and current execution state.

### B. Role isolation model
Document exact ownership boundaries so Architect, Builder, and Tester responsibilities are explicit and enforceable.

### C. Wave/task persistence model
Define how waves, tasks, reports, and state files are expected to interact before code automation begins.

### D. Active context model
Ensure the most important context files can be read quickly by Codex and other tools without requiring full-repo scanning.

## Tasks

- [ ] Audit the repository for existing workflow/control documents and preserve any useful conventions.
- [ ] Create or normalize `AGENTS.md` to define the agent operating model.
- [ ] Create or normalize `MASTER_CONTEXT_ACTIVE.md` to describe the current repository reality.
- [ ] Create or normalize `rules.md` and `SESSION_RULES.md` to define strict execution behavior.
- [ ] Create or normalize `ACTIVE_WAVE.md`, `CURRENT_WAVE.md`, and `WAVES.md`.
- [ ] Create or normalize `PHASE_PLAN.md`, `TASKS.md`, and `TESTING.md`.
- [ ] Create or normalize `agent_state.json` and placeholder report files.
- [ ] Ensure all file contents reflect the real TRUBA GUI repository structure and not a generic template.
- [ ] Document any assumptions or unresolved naming issues in completion notes if necessary.

## Validation

- [ ] All required workflow files exist in the repository.
- [ ] `AGENTS.md` clearly states that Codex is Architect-only by default.
- [ ] Builder and Tester roles are clearly separated and non-overlapping.
- [ ] There is a single active wave reference.
- [ ] `agent_state.json` is valid JSON.
- [ ] The documents reference the actual repository layout and terminology.
- [ ] No source-code behavior is changed in this wave unless required for doc placement.

## Done Criteria

This wave is done only when:

1. The repository has a coherent agent workflow documentation layer.
2. The role model is explicit enough that Codex can read the docs and behave correctly.
3. The active context and wave/task surfaces are in place for the next automation waves.
4. No implementation-specific orchestration logic has been prematurely introduced.

## Possible Blockers

- Existing repository docs may conflict with the new naming scheme.
- Some file names may need light renaming to match actual repo conventions.
- The project may already contain partial agent docs that require consolidation rather than replacement.

## On Completion

- Move this file to `waves/done/`.
- Mark the next wave as active in `ACTIVE_WAVE.md` and `CURRENT_WAVE.md`.
- Set the next wave to `wave_001_codex_architect_bootstrap.md`.
