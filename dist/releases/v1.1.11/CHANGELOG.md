## v1.1.11
- Transfers: kept large multi-folder uploads and downloads responsive by moving
  recursive planning, remote probing, and delete preparation out of the GUI
  thread; transfer queues now publish bounded updates instead of creating an
  unbounded number of widgets at once.
- Transfers: added an upload preflight review with an opt-out setting, safer
  per-file conflict handling, session-accurate resume speed/ETA, and reliable
  visibility and cancellation for overlapping transfer queues.
- Jobs & outputs: made follow-path fields editable across output slots, tabs,
  and separate windows; submitting a job can now keep the current view, use the
  Outputs tab, or open split/combined follow views according to Settings.
- Directories: improved local/remote transfer integration, added an SH filter,
  and kept long shell-script output in a screen-bounded, scrollable dialog.
- Updates: show changelog entries from newest to oldest after an update.
