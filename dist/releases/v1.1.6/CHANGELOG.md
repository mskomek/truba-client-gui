## v1.1.6
- Connection profiles: grouped TRUBA directories and Slurm commands as editable per-profile system defaults.
- Authentication: allowed profiles without a username or password and added an option to reuse saved Windows-protected credentials without prompting until the profile is edited.
- Activity control: paused `squeue`, `tail`, `lssrv`, accounting, and log refresh operations while their tabs are not visible.
- Responsiveness: moved remote polling and command execution off the GUI thread, prevented overlapping requests, and reduced duplicate SSH/log rendering work.
- Connection console: added right-click paste from the system clipboard into the live SSH shell.
- Directories: added a context-menu action to copy the full remote path including the file name.
- Jobs files: added a refresh button to the Files subtab and F5 refresh support for file panels in Jobs and Directories.
