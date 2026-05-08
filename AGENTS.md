# AGENTS.md

This repository uses a **Codex orchestrator -> local implementer -> local validator** workflow.

The goal in this project is:
- keep the main **Codex** session focused on planning, decomposition, wave reading, and orchestration,
- push **implementation and verification work** to **local Ollama-backed subagents** by default,
- preserve a narrow, auditable, file-based workflow for waves and tasks.

This repository is a **real Windows desktop client** for **TRUBA / Slurm / SSH / optional X11** workflows.
Agents must stay grounded in that product reality.

---

## 1. Default Delegation Policy

Unless the human explicitly overrides it, the main Codex session must follow this policy:

1. **Understand the request first.**
2. If the request requires **editing files**, **changing UI**, **changing strings**, **running a wave**,
   **adding tests**, or **modifying behavior**, the main Codex session should **not implement directly**.
3. The main Codex session should:
   - define the smallest safe bounded task,
   - delegate implementation to `implementer_local`,
   - delegate verification to `validator_local`,
   - then summarize the outcome for the human.
4. The main Codex session may answer directly only when the request is purely:
   - explanatory,
   - architectural,
   - planning-only,
   - or repository-reading with no file changes.

This is the default behavior for prompts such as:
- "şu sekmedeki fontları büyüt"
- "şunları yaz"
- "bu dialogu düzelt"
- "wave_011'i uygula"
- "şu butonun metnini değiştir"

---

## 2. Read Order

For normal task execution, read in this order:

1. `MASTER_CONTEXT_ACTIVE.md`
2. `rules.md`
3. `SESSION_RULES.md`
4. `ACTIVE_WAVE.md`
5. the wave file referenced by `ACTIVE_WAVE.md`
6. `TASKS.md`
7. only the source files needed for the active task

Do **not** scan the whole repository by default.
Do **not** read finished waves unless the active task requires history.

---

## 3. Agent Roles

### Main Codex Session (Architect / Orchestrator)

Responsibilities:
- understand the human request,
- read the relevant repo and workflow context,
- choose the next smallest safe bounded unit of work,
- decide whether the request is planning-only or requires file edits,
- delegate implementation to `implementer_local`,
- delegate verification to `validator_local`,
- summarize results and next steps for the human.

Must not by default:
- implement source changes directly,
- bypass validation for code-changing tasks,
- silently expand scope,
- merge multiple unrelated changes into one implementation handoff.

### `implementer_local`

Default runtime:
- local Ollama-backed model,
- write-capable sandbox,
- narrow implementation scope.

Responsibilities:
- make the requested code or file changes,
- stay within the assigned scope,
- prefer the smallest safe diff,
- run lightweight relevant checks when possible,
- report exactly what changed.

Must not:
- redefine acceptance criteria,
- broaden scope,
- validate with false confidence,
- rewrite unrelated areas.

### `validator_local`

Default runtime:
- local Ollama-backed model,
- read-only sandbox,
- strict verification role.

Responsibilities:
- verify scope, correctness, and requested outcome,
- run read-safe checks when possible,
- return `PASS`, `FAIL`, or `BLOCKED` style feedback with evidence,
- state clearly when environment limitations reduce confidence.

Must not:
- edit source code,
- fix issues directly,
- redefine what success means.

### Human

Responsibilities:
- resolve real blockers,
- approve scope changes,
- choose priorities between waves,
- handle secrets, credentials, and real TRUBA access when needed.

---

## 4. Wave Execution Rule

When the human gives a **wave file** or says to execute a wave:

1. The main Codex session reads the wave and current workflow state.
2. It identifies the next bounded, verifiable slice.
3. It delegates implementation of that slice to `implementer_local`.
4. It delegates verification to `validator_local`.
5. It reports:
   - what was implemented,
   - whether validation passed,
   - what remains in the wave.

Do not treat a wave as permission to perform a giant uncontrolled rewrite.
Default to bounded slices unless the human explicitly requests a full-wave pass.

---

## 5. Project Reality Constraints

This repo is not a toy orchestrator repo.
It is a **PySide6 desktop application** with real packaging and real external integrations.

Key areas:
- `src/truba_gui/ui/` -> windows, dialogs, widgets
- `src/truba_gui/services/` -> Slurm, files, process helpers, X11 helpers
- `src/truba_gui/ssh/` -> SSH client layer
- `src/truba_gui/config/` -> local config and persistence
- `src/truba_gui/core/` -> i18n, logging, diagnostics, app utilities
- `templates/` -> Slurm script templates
- `scripts/` -> validation, smoke, release helpers
- `tests/` -> automated verification

Agents must keep changes aligned with these boundaries.

---

## 6. MCP Bridge Guidance

When workflow state or reports matter, the main Codex session should prefer the
local read-only MCP bridge.

Current intent of the bridge:
- read workflow state,
- read active task/wave context,
- read build/test/wave reports.

The bridge must remain read-only unless a later wave explicitly introduces
write-capable tools with a separate trust review.

---

## 7. Scope and Safety Rules

- Prefer the **smallest safe diff**.
- Do not refactor unrelated code during a narrow task.
- Do not touch packaging or release scripts unless the task requires it.
- Do not hardcode secrets or TRUBA credentials.
- Do not claim cluster behavior that was not actually validated.
- If real TRUBA access is missing, return `BLOCKED` with the exact missing dependency.
- If PySide6, SSH access, or Windows-only behaviors cannot be tested in the current environment,
  state that explicitly.

---

## 8. Completion Rules

A task is complete only when:
- requested behavior is implemented,
- verification was attempted,
- limitations are recorded honestly,
- no unrelated files were changed.

A delegated implementation cycle is complete only when:
1. `implementer_local` has finished,
2. `validator_local` has produced a verdict,
3. the main Codex session has summarized the result.
