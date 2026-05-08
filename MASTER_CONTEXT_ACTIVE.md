# MASTER_CONTEXT_ACTIVE.md

Last updated: 2026-05-06

## Project Summary

This repository is a **client-side Windows GUI** for **TRUBA and similar Slurm-based HPC systems**.

Primary product goals:
- manage SSH-based remote workflows
- prepare and submit Slurm jobs safely
- inspect queue and accounting state
- browse and edit remote files
- support optional X11 launches through external tools
- keep logs, diagnostics, and user-visible errors understandable

This is not an official TRUBA product.
It must still reflect **real TRUBA / Slurm usage patterns**.

## Current Codebase Shape

Main package:
- `src/truba_gui/`

Important subareas:
- `ui/` -> PySide6 windows, dialogs, widgets
- `services/` -> file, Slurm, process, X11, PuTTY helpers
- `ssh/` -> SSH client wrappers
- `config/` -> persistence and UI preference storage
- `core/` -> logging, i18n, diagnostics, paths, resource helpers
- `docs/` -> embedded help content
- `i18n/` -> visible language strings

Repo-level supporting areas:
- `templates/` -> Slurm templates
- `scripts/` -> smoke / validation / release helpers
- `tests/` -> automated tests

## Product Direction

Near-term direction:
- keep the desktop app stable and understandable
- improve reliability of SSH / Slurm / file workflows
- make diagnostics observable instead of hidden
- avoid UI blocking during remote operations
- support repeatable release / packaging flows for Windows users

## Technical Direction

Preferred layering:
- UI widgets and windows stay thin
- reusable logic moves into services / core / ssh
- Slurm parsing and submission rules are explicit
- external tool interaction remains inspectable
- validation should be scriptable where possible

## Agent Workflow Goal

This repo now includes a Codex + Ollama workflow layer so that future work can be executed as:
- one active wave
- one small active task
- Builder implementation
- Tester verification
- file-based resume

## Quality Priorities

1. correctness of real user workflows
2. safe scope control
3. observability and logging
4. non-blocking GUI behavior
5. i18n consistency
6. packaging and release quality

## Current Focus

Current setup focus:
- tailor the agent workflow files to the actual TRUBA GUI repo
- keep Architect task definitions small, explicit, and parseable
- prepare the repo for future wave-driven implementation
- keep the next real engineering wave small and verifiable
- add a read-only localhost MCP bridge for state and report inspection
