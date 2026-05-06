# README_AGENT_WORKFLOW.md

This repository now contains a wave-based agent workflow tailored to the actual **TRUBA Client GUI** codebase.

## Intended Roles

- **Architect** -> Codex / GPT-5.5
- **Builder** -> local Ollama model such as Qwen 27B
- **Tester** -> local Ollama model such as Qwen 35B

## Active State Files

- `ACTIVE_WAVE.md`
- `CURRENT_WAVE.md`
- `TASKS.md`
- `agent_state.json`

## Main Guidance Files

- `AGENTS.md`
- `MASTER_CONTEXT_ACTIVE.md`
- `rules.md`
- `SESSION_RULES.md`
- `ARCHITECTURE.md`
- `TESTING.md`

## Next Recommended Step

Implement **Phase 2**:
- create `runner/runner.py`
- wire Builder and Tester calls to Ollama
- parse PASS / FAIL / BLOCKED
- support resume from `agent_state.json`

## Suggested First Real Product Waves

After the runner exists, start with one of:
- connection/session diagnostics
- editor + Slurm submit flow hardening
- file manager reliability improvements
