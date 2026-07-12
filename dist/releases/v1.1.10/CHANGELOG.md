## v1.1.10
- Updates: show the full changelog from the earliest entries on the first launch after an update and remember the last shown app version.
- File operations: ask separately for each nested file conflict during folder upload unless an apply-to-all or queue-wide choice is active, while keeping folder downloads queued off the UI thread.
- Local files: fixed Delete-key removal for non-empty folders by deleting local directories recursively after confirmation.
