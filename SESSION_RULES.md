# SESSION_RULES.md

This file defines how an agent session should behave in this repository.

## Session Start

At session start, read only:
1. `MASTER_CONTEXT_ACTIVE.md`
2. `rules.md`
3. `SESSION_RULES.md`
4. `ACTIVE_WAVE.md`
5. the active wave file
6. `TASKS.md`

Then load only the source files required for the active task.

If the active wave is about workflow docs, include the relevant prompt and state files in the required source set before editing.
If the active wave is about the MCP bridge, include the local bridge server, Codex config example, and the active workflow state files before editing.

## Repository Scanning Limits

Do not recursively inspect the whole repo unless the active task truly requires it.

Default focus areas:
- `src/truba_gui/`
- `tests/`
- `templates/`
- `scripts/`
- active wave docs

Ignore unrelated areas unless needed for the active task.

## File Modification Rule

Before changing files, verify that each file is listed under **Allowed Files** in `TASKS.md`.

If a necessary file is missing from Allowed Files:
- stop
- return `BLOCKED`
- explain which file is needed and why

Workflow-doc waves still follow the same rule; the allowed-file list must explicitly name the prompt and state files being updated.

## Build / Test Evidence Rule

If you run checks, record:
- exact command
- whether it passed or failed
- concise result summary

If a check cannot run because of environment mismatch, record the exact reason.

## Windows / TRUBA Awareness

This project targets Windows users interacting with TRUBA over SSH.

Be careful with assumptions around:
- path separators
- bundled vs external binaries
- X11 availability
- Qt offscreen test mode
- platform-specific packaging scripts

## Session End

Before ending a session:
- update the correct report file
- ensure the role routing is explicit
- leave the repo in a resumable state
