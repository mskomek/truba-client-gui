# TASKS.md

## Active Wave

wave_001_agent_workflow_foundation

---

## TASK-001.1 — Tailor the agent workflow docs to the real TRUBA repo

Status: READY_FOR_TESTER

### Goal

Replace generic workflow docs with versions that reflect the actual TRUBA GUI repository structure, current tests, and likely future waves.

### Allowed Files

- AGENTS.md
- MASTER_CONTEXT_ACTIVE.md
- rules.md
- SESSION_RULES.md
- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- WAVES.md
- wave_template.md
- ARCHITECTURE.md
- PHASE_PLAN.md
- TESTING.md
- TASKS.md
- README_AGENT_WORKFLOW.md
- waves/active/wave_001_agent_workflow_foundation.md
- waves/pending/wave_002_runner_ollama_loop.md
- reports/BUILD_REPORT.md
- reports/TEST_REPORT.md
- reports/WAVE_REPORT.md
- agent_state.json

### Forbidden Files

- `src/**`
- `tests/**`
- `templates/**`
- `scripts/**`
- packaging artifacts
- third-party binaries/assets

### Acceptance Criteria

- Workflow docs mention the real repo layout (`src/truba_gui`, `scripts`, `templates`, `tests`).
- Architect, Builder, and Tester responsibilities are tailored to this project.
- Testing guidance references real existing checks in this repo.
- Wave guidance includes sensible next waves for this TRUBA GUI project.
- State/docs remain internally consistent.

### Required Check Commands

- review the updated markdown/json files for path and role consistency

### Route

Tester
