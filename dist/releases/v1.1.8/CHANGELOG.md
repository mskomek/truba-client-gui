## v1.1.8
- FTP transfers: fixed configured parallel transfers so multiple uploads or downloads can run at the same time instead of staying sequential.
- FTP transfers: added an embedded progress bar with percentage in the Transfers table and hid internal local setup steps from the visible queue.
- FTP transfers: verified local FTP upload, parallel download, and visible partial-file resume behavior with a temporary FTP server.
- Directories: added Ctrl+C, Ctrl+X, and Ctrl+V support for local and remote file panels, including local-to-remote upload paste and remote-to-local download paste.
- Directories: made the remote path field editable so pressing Enter navigates to the typed path, and Backspace in the remote file list moves to the parent directory.
