# WAVES.md

Last updated: 2026-05-06

## Purpose

Waves are the top-level execution slices for this repository.

A wave should represent one coherent area of work, for example:
- agent workflow infrastructure
- connection/session reliability
- editor + submit flow hardening
- remote file manager improvements
- packaging/release readiness

## Directories

- `waves/pending/`
- `waves/active/`
- `waves/done/`

Only one wave should be active at a time.

## Recommended Wave Shape

Each wave should include:
- goal
- why
- scope
- out of scope
- allowed areas
- concrete task checklist
- validation checklist
- done criteria
- blockers

## Good Wave Examples For This Repo

- `wave_002_runner_loop_foundation.md`
- `wave_003_editor_submit_flow_hardening.md`
- `wave_004_connection_diagnostics.md`
- `wave_005_file_manager_reliability.md`

## Naming

Use:
- `wave_XXX_short_description.md`

## Completion

When a wave is complete:
1. mark its task checklist accurately
2. record validation evidence in `reports/WAVE_REPORT.md` if needed
3. move the wave file to `waves/done/`
4. activate the next pending wave
