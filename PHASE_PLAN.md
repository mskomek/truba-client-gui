# PHASE_PLAN.md

## Phase 1 — Agent Workflow Integration
- tailor `AGENTS.md`, wave docs, rules, and reports to the real TRUBA repo
- confirm active wave/task structure
- prepare prompt templates for Codex Architect and Ollama Builder/Tester

## Phase 2 — Runner and Ollama Bridge
- add a Python runner under `runner/`
- call local Ollama Builder and Tester models
- read and update `agent_state.json`
- parse `PASS` / `FAIL` / `BLOCKED`
- support resume after interruption

## Phase 3 — First Real Product Waves
- editor + submit flow hardening
- connection/session diagnostics improvements
- remote file manager reliability slices
- template and validation improvements

## Phase 4 — Release and Packaging Hardening
- improve release checks
- verify Windows packaging assumptions
- tighten smoke tests and pre-release validation

## Phase 5 — Optional MCP Upgrade
- expose Builder and Tester via local MCP server
- let Codex call them as tools if desired
