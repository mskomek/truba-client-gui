# AGENTS.md

This repository uses a **Wave -> Task -> Verify** workflow.

The goal is to let:
- **Codex / GPT-5.5** act as **Architect**
- **Ollama local model** act as **Builder**
- **Ollama local model** act as **Tester**
- file-based state control handoffs instead of relying on chat memory

The repository is a **real Windows desktop client** for **TRUBA / Slurm / SSH / optional X11** workflows. Agents must stay grounded in that product reality.

---

## 1. Read Order

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

## 2. Agent Roles

### Architect
Default model: **Codex / GPT-5.5**

Responsibilities:
- read wave and repo state
- choose the next smallest verifiable task
- write or refine acceptance criteria
- keep scope tight
- decide PASS / FAIL follow-up routing
- update planning/state docs when needed

Architect may change:
- `TASKS.md`
- `ACTIVE_WAVE.md`
- `CURRENT_WAVE.md`
- active wave file
- `PHASE_PLAN.md`
- `MASTER_CONTEXT_ACTIVE.md`
- `reports/WAVE_REPORT.md`
- `agent_state.json`

Architect must not:
- implement source code unless the human explicitly overrides the rule
- silently expand scope
- bundle multiple unrelated fixes into one task

### Builder
Default model: **local Ollama model** such as Qwen 27B

Responsibilities:
- implement only the active task
- change only allowed files
- run the required checks
- write a factual build report

Builder may change:
- files listed under **Allowed Files** in `TASKS.md`
- `reports/BUILD_REPORT.md`

Builder must not:
- change acceptance criteria
- rewrite wave scope
- start future tasks
- modify unrelated docs or source files

### Tester
Default model: **local Ollama model** such as Qwen 35B

Responsibilities:
- verify only
- inspect changed files
- run the task checks when possible
- compare implementation against acceptance criteria
- return exactly `PASS`, `FAIL`, or `BLOCKED`

Tester may change:
- `reports/TEST_REPORT.md`

Tester must not:
- edit source code
- fix issues directly
- redefine what success means

### Human
Responsibilities:
- resolves true blockers
- approves scope changes
- decides priorities between waves
- handles secrets, credentials, and real TRUBA access when needed

---

## 3. Project Reality Constraints

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

## 4. Handoff Contract

### Architect -> Builder
Each active task must include:
- task id
- short summary
- allowed files
- forbidden files
- acceptance criteria
- required check commands
- route = Builder

### Builder -> Tester
`reports/BUILD_REPORT.md` must record:
- task id
- files changed
- commands run
- observed results
- known issues
- route = Tester

### Tester outcomes
Tester must return exactly one:
- `PASS` -> Architect selects next task
- `FAIL` -> Builder fixes within the same task scope
- `BLOCKED` -> Architect narrows or re-plans the task

---

## 5. Source-of-Truth Hierarchy

### Active execution state
- `ACTIVE_WAVE.md`
- `CURRENT_WAVE.md`
- active wave file
- `TASKS.md`
- `agent_state.json`

### Stable project guidance
- `MASTER_CONTEXT_ACTIVE.md`
- `ARCHITECTURE.md`
- `TESTING.md`
- `rules.md`
- `SESSION_RULES.md`

### Secondary / historical docs
Read only when needed:
- `README.md`
- `README_AGENT_WORKFLOW.md`
- `waves/done/*`
- release notes and changelogs

---

## 6. Scope and Safety Rules

- Prefer the **smallest safe diff**.
- Do not refactor unrelated code during a task.
- Do not touch packaging scripts unless the task explicitly requires it.
- Do not hardcode secrets or TRUBA credentials.
- Do not claim cluster behavior that was not actually validated.
- If real TRUBA access is missing, return `BLOCKED` with exact missing dependency.

---

## 7. Completion Rules

A task is complete only when:
- acceptance criteria are satisfied
- required checks were run or a real blocker was recorded
- reports were updated
- no forbidden files were modified

A wave is complete only when:
- all tasks in the wave are PASS
- wave-level validation is recorded
- the next wave can start cleanly
