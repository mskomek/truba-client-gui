# Wave 001 — Agent Workflow Foundation

## Goal

Tailor the wave-based Codex + Ollama workflow files to the actual TRUBA Client GUI repository.

## Why

The repo already contains agent workflow starter files, but they should reflect the real package layout, actual validation options, and likely next engineering waves before the runner is implemented.

## Scope

This wave includes:
- adapting workflow docs to the real repo structure
- aligning testing guidance with current scripts/tests
- defining active state files and reports
- preparing the next wave for runner + Ollama integration

## Out of Scope

This wave does not include:
- implementing `runner/runner.py`
- MCP integration
- changing application source code
- changing automated test code

## Allowed Areas

- repository root workflow docs
- `reports/`
- `runner/prompts/`
- `waves/active/`
- `waves/pending/`

## Tasks

- [x] tailor workflow docs to the actual repo layout
- [x] align role definitions with TRUBA Client GUI reality
- [x] align testing guidance with existing scripts/tests
- [x] draft the next wave for runner integration
- [ ] perform final review / accept the foundation setup

## Validation

- [x] active wave points to a real file
- [x] task file matches the current wave
- [x] workflow docs mention real repo areas
- [x] next wave draft exists
- [ ] human or tester review confirms consistency

## Done Criteria

This wave is done only when:
1. tailored workflow docs are accepted
2. state files are internally consistent
3. the next wave can begin without restructuring the doc layer

## Possible Blockers

- the user may want a different naming scheme for agent files
- the runner may need a different directory layout later

## On Completion

- move this file to `waves/done/`
- activate `wave_002_runner_ollama_loop.md`
