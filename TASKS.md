# TASKS.md

## Active Wave

none

## TASK-022.1 — Add ANSI/VT terminal emulation to the connection console

Status: PASS

### Summary

Render interactive SSH shell output through a small ANSI/VT emulation layer so redraw, dialog, and box-drawing output behave more like a real terminal.

### Goal

Improve terminal correctness for login banners, whiptail/dialog screens, cursor movement, and redraw-heavy shell output without rewriting the shell session architecture.

### Dependencies

- TASK-021.1 must be PASS

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- agent_state.json
- waves/done/wave_022_ansi_vt_terminal_emulation.md
- src/truba_gui/ssh/client.py
- src/truba_gui/ui/widgets/login_widget.py
- src/truba_gui/services/terminal_emulator.py
- requirements.txt

### Forbidden Files

- `tests/**`
- `scripts/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other `src/**` files not listed above

### Acceptance Criteria

- Interactive shell output is processed through an ANSI/VT-aware helper instead of being blindly appended as plain text.
- Box drawing, cursor movement, carriage return, and clear/redraw behavior improve visibly for login/banner and dialog-style screens.
- The emulation helper stays small and isolated from the UI widget.
- Fallback behavior remains safe if the emulator cannot be used.

### Required Check Commands

- `python -m py_compile src/truba_gui/ui/widgets/login_widget.py src/truba_gui/ssh/client.py`
- `python -c "import sys; sys.path.insert(0, 'src'); from truba_gui.ui.widgets.login_widget import LoginWidget; from truba_gui.ssh.client import SSHClientWrapper; print('wave 022 imports ok')"`

### Route

Done

## TASK-021.1 — Unify interactive shell input with the live SSH shell session

Status: PASS

### Summary

Route the terminal input flow through the live interactive SSH shell session so login output, prompt, and user-entered commands share one visible stream.

### Goal

Make the Connection console behave like a single interactive shell session for user commands while preserving the backend service paths that still need `exec_command()`.

### Dependencies

- TASK-020.1 must be PASS

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- agent_state.json
- waves/pending/wave_021_interactive_shell_session_architecture.md
- waves/active/wave_021_interactive_shell_session_architecture.md
- src/truba_gui/ssh/client.py
- src/truba_gui/ui/widgets/login_widget.py
- src/truba_gui/ui/widgets/terminal_input.py

### Forbidden Files

- `tests/**`
- `scripts/**`
- `templates/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other `src/**` files not listed above

### Acceptance Criteria

- The Connection terminal input sends commands into the live interactive SSH shell session.
- Login banner, prompt, user input, and shell output share one visible console stream.
- The interactive terminal path no longer depends on `exec_command()` for ordinary user-entered console commands.
- Disconnect and reconnect still close and reopen the interactive shell safely.
- Backend service flows for jobs/files remain available and are not forced through the terminal shell.

### Required Check Commands

- `python -m py_compile src/truba_gui/ui/widgets/login_widget.py src/truba_gui/ui/widgets/terminal_input.py src/truba_gui/ssh/client.py`
- `python -c "import sys; sys.path.insert(0, 'src'); from truba_gui.ui.widgets.login_widget import LoginWidget; from truba_gui.ui.widgets.terminal_input import TerminalInput; from truba_gui.ssh.client import SSHClientWrapper; print('wave 021 imports ok')"`

### Route

Builder

## TASK-020.1 — Stabilize console rendering and PTY resize plumbing

Status: PASS

### Summary

Upgrade the Connection console render baseline and add PTY resize plumbing so the interactive shell stays aligned with terminal geometry.

### Goal

Make the login console use fixed-width, no-wrap rendering and keep interactive shell geometry synchronized with widget size changes.

### Dependencies

- none

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- agent_state.json
- waves/done/wave_020_console_stabilization_and_pty_resize.md
- src/truba_gui/ui/widgets/login_widget.py
- src/truba_gui/ui/widgets/terminal_input.py
- src/truba_gui/ssh/client.py

### Forbidden Files

- `tests/**`
- `scripts/**`
- `templates/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other `src/**` files not listed above

### Acceptance Criteria

- Connection console opens with a fixed-width font and no wrap.
- Login console update path remains stable and does not crash on shutdown.
- SSH interactive shell can receive PTY geometry updates from the UI.
- Initial shell geometry is set when the shell session starts.
- Existing save/connect behavior still works.

### Required Check Commands

- `python -m py_compile src/truba_gui/ui/widgets/login_widget.py src/truba_gui/ui/widgets/terminal_input.py src/truba_gui/ssh/client.py`
- `python -c "import sys; sys.path.insert(0, 'src'); from truba_gui.ui.widgets.login_widget import LoginWidget; from truba_gui.ssh.client import SSHClientWrapper, SSHConnInfo; print('wave 020 imports ok')"`

### Route

Builder

## TASK-019.1 — Add right-click edit for saved connection sessions

Status: PASS

### Summary

Add a right-click context menu to the saved session list in the Connection area so users can open an edit dialog for the selected profile/session.

### Goal

Right-clicking a saved connection/session should show an Edit action that opens a prefilled dialog for modifying and saving the selected session details.

### Dependencies

- none

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- waves/pending/wave_019_connection_saved_session_context_edit.md
- waves/active/wave_019_connection_saved_session_context_edit.md
- src/truba_gui/ui/widgets/login_widget.py
- src/truba_gui/i18n/en.json
- src/truba_gui/i18n/tr.json

### Forbidden Files

- `tests/**`
- `scripts/**`
- `templates/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other `src/**` files not listed above

### Acceptance Criteria

- Right-clicking a saved session in the Connection list shows an Edit action.
- Choosing Edit opens a separate dialog populated with the selected session's current data.
- Saving from the edit dialog updates the saved profile/session correctly.
- Existing selection and connect behavior still works after the change.

### Required Check Commands

- `python -m py_compile src/truba_gui/ui/widgets/login_widget.py`
- `python -m json.tool src/truba_gui/i18n/en.json`
- `python -m json.tool src/truba_gui/i18n/tr.json`
- `python -c "import sys; sys.path.insert(0, 'src'); from truba_gui.ui.widgets.login_widget import LoginWidget; print('login widget import ok')"`

### Route

Builder

## TASK-018.1 — Repair Turkish i18n encoding so visible UI text renders correctly

Status: PASS

### Summary

Fix the corrupted Turkish translation resource text so the app renders readable Turkish labels, tabs, menus, and messages without mojibake.

### Goal

Restore correct UTF-8 Turkish UI strings in the localization resources and confirm the English resource remains valid.

### Dependencies

- none

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- waves/pending/wave_018_fix_turkish_i18n_encoding.md
- waves/active/wave_018_fix_turkish_i18n_encoding.md
- src/truba_gui/i18n/tr.json
- src/truba_gui/i18n/en.json

### Forbidden Files

- `tests/**`
- `scripts/**`
- `templates/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other `src/**` files not listed above

### Acceptance Criteria

- Turkish UI strings in `src/truba_gui/i18n/tr.json` render with correct UTF-8 characters instead of mojibake.
- Visible labels, menus, tabs, and dialogs can load readable Turkish text from the translation resource.
- English translation loading remains valid.
- The fix is done at the resource/source level rather than by patching individual widgets one by one.

### Required Check Commands

- `python -m json.tool src/truba_gui/i18n/tr.json`
- `python -m json.tool src/truba_gui/i18n/en.json`
- `python -c "import sys; sys.path.insert(0, 'src'); from truba_gui.core.i18n import load_language, t; load_language('tr'); print(t('tabs.login')); print(t('login.connect'))"`

### Route

Builder

## TASK-017.1 — Split Jobs into details and outputs subtabs

Status: PASS

### Summary

Reorganize the Jobs area into two lower subtabs so job operations, accounting/details, and scratch browsing stay together while output watching is isolated in its own tab.

### Goal

The Jobs tab should expose a details-oriented subtab containing jobs, accounting, details, and scratch content, plus a second subtab dedicated to outputs only.

### Dependencies

- none

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- waves/pending/wave_017_jobs_subtabs_accounting_and_outputs.md
- waves/active/wave_017_jobs_subtabs_accounting_and_outputs.md
- src/truba_gui/ui/widgets/jobs_outputs_widget.py

### Forbidden Files

- `tests/**`
- `scripts/**`
- `templates/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other `src/**` files not listed above

### Acceptance Criteria

- Jobs content is split into two lower subtabs inside the Jobs area.
- The first subtab contains the jobs list, accounting/details controls, and the scratch directory panel.
- The second subtab contains the output watching controls and live output panels only.
- Existing refresh, cancel, scratch open, and output binding behavior still works after the move.
- The public `JobsOutputsWidget` surface used by the rest of the app remains stable.

### Required Check Commands

- `python -m py_compile src/truba_gui/ui/widgets/jobs_outputs_widget.py`
- `python -c "from pathlib import Path; active = Path('ACTIVE_WAVE.md').read_text(encoding='utf-8'); current = Path('CURRENT_WAVE.md').read_text(encoding='utf-8'); assert 'wave_017_jobs_subtabs_accounting_and_outputs' in active; assert 'wave_017_jobs_subtabs_accounting_and_outputs' in current; print('wave pointers aligned')"`

### Route

Builder

## TASK-016.1 — Enter folders on double-click and add parent navigation in Directories

Status: PASS

### Summary

Make the Directories tab behave like a normal remote file browser by opening folders on double-click, keeping file actions reachable, and adding a visible parent/up control.

### Goal

Double-clicking a folder should navigate into that folder, double-clicking a file should keep the existing file-action flow, and the user should be able to return to the parent directory from the top toolbar.

### Dependencies

- TASK-015.1 must be PASS

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- agent_state.json
- waves/pending/wave_016_directories_navigation_double_click_and_parent_button.md
- waves/ongoing/wave_016_directories_navigation_double_click_and_parent_button.md
- waves/done/wave_016_directories_navigation_double_click_and_parent_button.md
- src/truba_gui/ui/widgets/remote_dir_panel.py

### Forbidden Files

- `tests/**`
- `scripts/**`
- `templates/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other src/** files not listed above

### Acceptance Criteria

- Double-clicking a folder in Directories changes the current remote directory into that folder.
- The list refreshes to show the folder contents after navigation.
- A visible parent/up control returns the user to the containing directory.
- File-specific actions remain reachable and do not trigger when the user is trying to enter a folder.
- Double-clicking folders does not open the file action dialog.

### Required Check Commands

- `python -m py_compile src/truba_gui/ui/widgets/remote_dir_panel.py`
- `python -m json.tool agent_state.json`
- `python -c "from pathlib import Path; active = Path('ACTIVE_WAVE.md').read_text(encoding='utf-8'); current = Path('CURRENT_WAVE.md').read_text(encoding='utf-8'); assert 'wave_016_directories_navigation_double_click_and_parent_button' in active; assert 'wave_016_directories_navigation_double_click_and_parent_button' in current; print('wave pointers aligned')"`

### Route

Builder

## TASK-015.1 — Prevent quick tour from reselecting the Connection tab during unrelated UI refreshes

Status: PASS

### Summary

Keep the currently selected tab stable when the quick tour overlay refreshes its geometry during window move, resize, show, or similar non-user tab events.

### Goal

Preserve explicit user navigation to the Connection/Login tab while stopping the tour overlay from forcing that tab back into view just to compute its highlight target.

### Dependencies

- TASK-014.1 must be PASS

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- agent_state.json
- waves/pending/wave_015_do_not_auto_switch_to_connection_tab.md
- waves/ongoing/wave_015_do_not_auto_switch_to_connection_tab.md
- src/truba_gui/ui/dialogs/quick_tour.py

### Forbidden Files

- `tests/**`
- `scripts/**`
- `templates/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other src/** files not listed above

### Acceptance Criteria

- Moving or resizing the main window does not auto-switch the current tab back to Connection/Login.
- Ordinary refreshes from the quick tour overlay do not force the Connection/Login tab to become active.
- Explicit user clicks or normal navigation to the Connection/Login tab still work.
- The tour overlay continues to refresh its geometry without needing to change tabs just to compute the target, when the target is already available.

### Required Check Commands

- `python -m py_compile src/truba_gui/ui/dialogs/quick_tour.py`
- `python -m json.tool agent_state.json`
- `python -c "from pathlib import Path; active = Path('ACTIVE_WAVE.md').read_text(encoding='utf-8'); current = Path('CURRENT_WAVE.md').read_text(encoding='utf-8'); assert 'wave_015_do_not_auto_switch_to_connection_tab' in active; assert 'wave_015_do_not_auto_switch_to_connection_tab' in current; print('wave pointers aligned')"`

### Route

Builder

## TASK-014.1 — Show real SSH login output and prompt after connect

Status: PASS

### Summary

Open a PTY-backed SSH shell session on connect so the console shows genuine remote login/banner/prompt output, while preserving the existing command execution path for normal remote commands.

### Goal

Make the post-login console feel like a real SSH session by streaming the remote shell's startup text without faking MOTD/banner content locally.

### Dependencies

- TASK-013.1 must be PASS

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- agent_state.json
- waves/done/wave_014_real_ssh_login_banner_console.md
- src/truba_gui/ssh/client.py
- src/truba_gui/ui/widgets/login_widget.py

### Forbidden Files

- `tests/**`
- `scripts/**`
- `templates/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other src/** files not listed above

### Acceptance Criteria

- Connecting over SSH opens a PTY-backed shell session that can stream genuine remote login/banner/prompt output into the console.
- The app does not fabricate banner or MOTD text locally.
- Existing `exec_command`-based command execution remains usable for normal commands.
- SSH resources are cleaned up on shutdown so the shell session does not leak.

### Required Check Commands

- `python -m py_compile src/truba_gui/ssh/client.py src/truba_gui/ui/widgets/login_widget.py`
- `python -c "from truba_gui.ssh.client import SSHClientWrapper, SSHConnInfo; print('ssh client import ok')"`

### Route

Builder

## TASK-013.1 — Move app-wide connection settings into a Settings dialog

Status: PASS

### Summary

Move the three app-wide connection lifecycle/tooling settings out of the inline login widget and into a dedicated Settings dialog while keeping the same storage keys and runtime behavior intact.

### Goal

Give the app a visible top-right Settings action and keep the connection/login UI focused on connection-specific inputs.

### Dependencies

- TASK-012.1 must be PASS

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- agent_state.json
- waves/done/wave_013_settings_dialog_and_app_settings_migration.md
- src/truba_gui/ui/main_window.py
- src/truba_gui/ui/widgets/login_widget.py
- src/truba_gui/ui/dialogs/settings_dialog.py
- src/truba_gui/i18n/en.json
- src/truba_gui/i18n/tr.json

### Forbidden Files

- `tests/**`
- `scripts/**`
- `templates/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other src/** files not listed above

### Acceptance Criteria

- A visible Settings button/action is present in the main window top-right action area.
- Clicking Settings opens a dedicated dialog containing the three app-wide settings.
- The three app-wide settings no longer appear inline in `login_widget`.
- The existing `x11_autodeps`, `close_vcxsrv_on_exit`, and `close_x11_procs_on_exit` keys still load and save through the shared settings storage helpers.
- Connection and shutdown behavior still honors the saved settings.
- Existing profile save/connect behavior remains intact.

### Required Check Commands

- `python -m py_compile src/truba_gui/ui/main_window.py src/truba_gui/ui/widgets/login_widget.py src/truba_gui/ui/dialogs/settings_dialog.py`
- `python -c "from pathlib import Path; import json; json.loads(Path('src/truba_gui/i18n/en.json').read_text(encoding='utf-8')); json.loads(Path('src/truba_gui/i18n/tr.json').read_text(encoding='utf-8')); print('i18n ok')"`

### Route

Builder

## TASK-012.1 — Refactor Connection tab to use an Add Connection dialog

Status: PASS

### Summary

Refactor the current Connection area so the full connection/profile form is no longer always visible inline. Instead, the user should manage connection creation through a dedicated Add Connection action that opens a dialog.

### Goal

The Connection tab should stay useful for saved profile selection, console output, and connection-related actions while moving profile creation into a dedicated dialog.

### Dependencies

- TASK-011.1 must be PASS

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- agent_state.json
- waves/pending/wave_012_connection_tab_add_connection_dialog.md
- waves/ongoing/wave_012_connection_tab_add_connection_dialog.md
- src/truba_gui/app.py
- src/truba_gui/ui/main_window.py
- src/truba_gui/ui/widgets/login_widget.py
- src/truba_gui/ui/dialogs/connection_dialog.py
- src/truba_gui/i18n/en.json
- src/truba_gui/i18n/tr.json

### Forbidden Files

- `tests/**`
- `scripts/**`
- `templates/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other src/** files not listed above

### Acceptance Criteria

- No inline full connection form remains permanently visible in the Connection tab.
- A visible Add Connection button/action is present in the Connection area.
- Clicking Add Connection opens a dedicated connection dialog.
- The dialog contains the profile and connection fields needed for profile creation and connect flow.
- Saving a profile still works.
- Connect flow still works after the refactor.
- The main Connection tab remains usable for profile selection, console viewing, and related actions.

### Required Check Commands

- `python -m py_compile src/truba_gui/app.py src/truba_gui/ui/main_window.py src/truba_gui/ui/widgets/login_widget.py src/truba_gui/ui/dialogs/connection_dialog.py`
- `python -c "from truba_gui.app import main; print('app entry imports')"`

### Route

Builder

## TASK-011.1 — Remove Start Tour from normal user flow

Status: PASS

### Summary

Remove the Start Tour entry points from the normal app experience so the main UI stays clean and the tour is no longer launched automatically.

### Goal

The app should not show Start Tour in the main top action area or Help menu, and startup should not auto-open the tour.

### Dependencies

- TASK-010.1 must be PASS

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- TASKS.md
- agent_state.json
- waves/done/wave_011_remove_start_tour.md
- waves/ongoing/wave_011_remove_start_tour.md
- src/truba_gui/app.py
- src/truba_gui/ui/main_window.py
- src/truba_gui/ui/dialogs/help_dialog.py
- src/truba_gui/ui/dialogs/quick_tour.py
- src/truba_gui/i18n/en.json
- src/truba_gui/i18n/tr.json

### Forbidden Files

- tests/**
- scripts/**
- templates/**
- packaging artifacts
- third-party binaries/assets
- runner/runner.py
- runner/mcp_server.py
- any other src/** files not listed above

### Acceptance Criteria

- No visible Start Tour button in the main top action area.
- No Start Tour entry appears in the standard Help menu flow.
- The app does not auto-launch a tour on startup.
- Main window and startup flow still open normally after the cleanup.
- Any unneeded labels or wiring tied only to normal-flow Start Tour usage are cleaned up safely.

### Required Check Commands

- `python -m py_compile src/truba_gui/app.py src/truba_gui/ui/main_window.py src/truba_gui/ui/dialogs/help_dialog.py`
- `python -c "from truba_gui.app import main; print('app entry imports')"`

### Route

Builder

## TASK-010.1 — Build a read-only MCP bridge for workflow state and reports

Status: PASS

### Summary

Create a localhost-only MCP bridge that exposes the active workflow state and report files without any write or shell execution capability.

### Goal

Let Codex inspect the current wave, active task, build report, and test report through a safe read-only MCP server and a matching Codex config example.

### Dependencies

- TASK-009.1 must be PASS

### Allowed Files

- .codex/config.toml
- ACTIVE_WAVE.md
- AGENTS.md
- CURRENT_WAVE.md
- MASTER_CONTEXT_ACTIVE.md
- README_AGENT_WORKFLOW.md
- SESSION_RULES.md
- TASKS.md
- agent_state.json
- reports/BUILD_REPORT.md
- reports/TEST_REPORT.md
- reports/WAVE_REPORT.md
- runner/mcp_server.py
- waves/done/wave_010_mcp_bridge_foundation.md
- waves/ongoing/wave_010_mcp_bridge_foundation.md

### Forbidden Files

- `src/**`
- `tests/**`
- `templates/**`
- `scripts/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py

### Acceptance Criteria

- `runner/mcp_server.py` can start a localhost-only streamable HTTP MCP server.
- `get_state()`, `get_active_task()`, `get_current_wave()`, `read_build_report()`, and `read_test_report()` return read-only data from the repository state.
- `.codex/config.toml` shows a valid local MCP connection entry for the bridge.
- `AGENTS.md`, `MASTER_CONTEXT_ACTIVE.md`, and `SESSION_RULES.md` describe the read-only trust boundary.
- No write-capable or shell-executing bridge path is introduced.

### Required Check Commands

- `python -m py_compile runner/mcp_server.py`
- `python -c "from runner.mcp_server import get_state, get_active_task, get_current_wave; print(get_state()['current_wave']); print(get_active_task()['task_id']); print(get_current_wave()['wave_id'])"`
- `python -c "from pathlib import Path; print(Path('.codex/config.toml').read_text(encoding='utf-8'))"`

### Route

Builder

---

## Task Contract Standard

Every task definition in this file must include:
- task id
- summary
- goal
- dependencies
- allowed files
- forbidden files
- acceptance criteria
- required check commands
- route

## TASK-009.1 — Run the first end-to-end dry run on a small docs task

Status: PASS

### Summary

Use the existing Architect -> Builder -> Tester runner flow on a small, real documentation task so the workflow can be observed end to end.

### Goal

Update a narrow set of workflow docs through the full loop and record the state and report transitions that result.

### Dependencies

- TASK-008.1 must be PASS

### Allowed Files

- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- MASTER_CONTEXT_ACTIVE.md
- PHASE_PLAN.md
- README_AGENT_WORKFLOW.md
- SESSION_RULES.md
- TASKS.md
- agent_state.json
- reports/BUILD_REPORT.md
- reports/TEST_REPORT.md
- reports/WAVE_REPORT.md
- runner/logs/**
- waves/ongoing/wave_009_first_end_to_end_dry_run.md
- waves/done/wave_009_first_end_to_end_dry_run.md

### Forbidden Files

- `src/**`
- `tests/**`
- `templates/**`
- `scripts/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py

### Acceptance Criteria

- The selected docs task stays small and isolated.
- Builder updates the allowed docs and writes `reports/BUILD_REPORT.md`.
- Tester verifies the same task contract and writes `reports/TEST_REPORT.md`.
- `agent_state.json` shows the expected Architect -> Builder -> Tester transitions.
- `reports/WAVE_REPORT.md` captures the dry run outcome.
- The wave remains resumable from file state after each transition.

### Required Check Commands

- `python -m json.tool agent_state.json`
- `python -c "from pathlib import Path; assert Path('README_AGENT_WORKFLOW.md').exists(); assert Path('PHASE_PLAN.md').exists(); print('docs task targets present')"`
- `python -c "from pathlib import Path; text=Path('TASKS.md').read_text(encoding='utf-8'); assert 'TASK-009.1' in text; print('task entry present')"`

### Route

Builder

---

## TASK-008.1 — Tighten the Architect workflow contract

Status: PASS

### Goal

Make the Architect prompt, task contract, and session guidance consistent with the repo's wave workflow.

### Summary

Standardize the Architect-facing workflow docs so the next active task can be prepared with a parseable, repo-specific handoff format.

### Dependencies

- TASK-007.1 must be PASS

### Allowed Files

- AGENTS.md
- ACTIVE_WAVE.md
- ARCHITECTURE.md
- CURRENT_WAVE.md
- agent_state.json
- MASTER_CONTEXT_ACTIVE.md
- PHASE_PLAN.md
- reports/BUILD_REPORT.md
- reports/WAVE_REPORT.md
- reports/TEST_REPORT.md
- README_AGENT_WORKFLOW.md
- SESSION_RULES.md
- TASKS.md
- TESTING.md
- runner/prompts/architect.md
- runner/logs/**
- waves/ongoing/wave_008_codex_architect_flow.md
- waves/done/wave_008_codex_architect_flow.md

### Forbidden Files

- `src/**`
- `tests/**`
- `templates/**`
- `scripts/**`
- packaging artifacts
- third-party binaries/assets
- runner/runner.py

### Acceptance Criteria

- The Architect prompt outputs `SUMMARY`, `GOAL`, `DEPENDENCIES`, `FILES_ALLOWED`, `FILES_FORBIDDEN`, `ACCEPTANCE_CRITERIA`, `TEST_COMMANDS`, and `ROUTE`.
- `TASKS.md` includes a standard task contract section and an example task that follows it.
- `ACTIVE_WAVE.md`, `CURRENT_WAVE.md`, `TASKS.md`, and `agent_state.json` point to the same active wave and task.
- The active wave file lives in `waves/ongoing/` while active and can be moved to `waves/done/` cleanly when complete.
- The workflow docs make it clear that Codex acts as Architect, not Builder.

### Required Check Commands

- `python -m json.tool agent_state.json`
- `python -c "from pathlib import Path; files=['ACTIVE_WAVE.md','CURRENT_WAVE.md','TASKS.md','runner/prompts/architect.md']; assert all(Path(f).exists() for f in files); print('workflow docs present')"`
- `python -c "from pathlib import Path; text=Path('TASKS.md').read_text(encoding='utf-8'); assert 'Task Contract Standard' in text and 'SUMMARY' in text; print('task contract present')"`

### Route

Builder

---

## TASK-005.1 — Implement deterministic Builder/Tester/Architect loop completion

Status: PASS

### Goal

Complete the deterministic Builder -> Tester -> Architect loop so a single active task can move through PASS, FAIL, and BLOCKED outcomes without manual file editing.

### Dependencies

- TASK-004.1 must be PASS

### Allowed Files

- runner/runner.py
- agent_state.json
- reports/BUILD_REPORT.md
- reports/TEST_REPORT.md
- runner/logs/**

### Forbidden Files

- `src/**`
- `tests/**`
- `templates/**`
- `scripts/**`
- packaging artifacts
- third-party binaries/assets
- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- waves/**

### Acceptance Criteria

- The runner can route deterministically between Builder, Tester, and Architect based on PASS, FAIL, and BLOCKED.
- The runner persists task progress metadata after each major transition.
- The runner can resume from file state without guessing the next role.
- PASS, FAIL, and BLOCKED outcomes are handled explicitly and logged.
- Missing or malformed terminal outcomes fail visibly instead of silently progressing.
- The loop remains single-wave and single-task only.

### Required Check Commands

- `python -m py_compile runner/runner.py`
- `python runner/runner.py`

### Route

Builder

---

## TASK-004.1 — Implement deterministic Ollama Tester execution

Status: PASS

### Goal

Add the Tester execution path to the runner so the active task can be verified by the local Ollama Tester model, captured, and written to a test report.

### Dependencies

- TASK-003.1 must be PASS

### Allowed Files

- runner/runner.py
- runner/prompts/tester.md
- reports/TEST_REPORT.md
- agent_state.json
- runner/logs/**

### Forbidden Files

- `src/**`
- `tests/**`
- `templates/**`
- `scripts/**`
- packaging artifacts
- third-party binaries/assets
- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- waves/**

### Acceptance Criteria

- The runner can assemble a deterministic Tester prompt from repo state and the active task.
- The runner can invoke the configured Ollama Tester process with timeout handling.
- Tester stdout, stderr, and exit behavior are captured in a stable report.
- `reports/TEST_REPORT.md` is written on success and failure.
- The runner persists enough metadata for a resumed Tester attempt.
- The Tester outcome is parsed as exactly one of PASS, FAIL, or BLOCKED.

### Required Check Commands

- `python -m py_compile runner/runner.py`
- `python runner/runner.py`

### Route

Tester

---

## TASK-003.1 — Implement deterministic Ollama Builder execution

Status: PASS

### Goal

Add the Builder execution path to the runner so the active task can be handed to the local Ollama Builder model, captured, and written to a build report.

### Dependencies

- TASK-002.1 must be PASS

### Allowed Files

- runner/runner.py
- runner/prompts/builder.md
- reports/BUILD_REPORT.md
- agent_state.json
- runner/logs/**

### Forbidden Files

- `src/**`
- `tests/**`
- `templates/**`
- `scripts/**`
- packaging artifacts
- third-party binaries/assets
- ACTIVE_WAVE.md
- CURRENT_WAVE.md
- waves/**

### Acceptance Criteria

- The runner can assemble a deterministic Builder prompt from repo state and the active task.
- The runner can invoke the configured Ollama Builder process with timeout handling.
- Builder stdout, stderr, and exit behavior are captured in a stable report.
- `reports/BUILD_REPORT.md` is written on success and failure.
- The runner persists enough metadata for a resumed Builder attempt.
- No Tester or MCP behavior is introduced in this task.

### Required Check Commands

- `python -m py_compile runner/runner.py`
- `python runner/runner.py`

### Route

Builder

## TASK-001.1 — Tailor the agent workflow docs to the real TRUBA repo

Status: PASS

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
- waves/done/wave_001_agent_workflow_foundation.md
- waves/active/wave_002_runner_loop_foundation.md
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

---

## TASK-002.1 — Build the deterministic runner loop foundation

Status: PASS

### Goal

Create the first deterministic orchestration loop for the TRUBA agent workflow so the project can resume by state and move cleanly between Architect, Builder, and Tester roles.

### Dependencies

- TASK-001.1 must be PASS

### Allowed Files

- runner/runner.py
- agent_state.json
- runner/logs/**
- reports/BUILD_REPORT.md

### Forbidden Files

- `src/**`
- `tests/**`
- `templates/**`
- `scripts/**`
- packaging artifacts
- third-party binaries/assets

### Acceptance Criteria

- `runner/runner.py` exists and can execute as the workflow entry point.
- The runner reads `agent_state.json` and routes by role deterministically.
- Invalid state causes a clear controlled stop.
- Basic logs are written for every run attempt.
- No files under `src/` are modified by this wave.

### Required Check Commands

- `python -m py_compile runner/runner.py`
- `python runner/runner.py`

### Route

Builder
