# Source Performance Debug Mode

Run from the repository root:

```powershell
.\scripts\run_performance_debug.ps1
```

Optional thresholds:

```powershell
.\scripts\run_performance_debug.ps1 -SlowMs 150 -IntervalMs 50
```

Reports are written to `reports/performance/session-*.jsonl`. Each session
contains startup checkpoints, event-loop delays above the configured threshold,
and the 50 `src/truba_gui` functions with the highest cumulative runtime.

This tool is disabled by default, loaded from outside `src`, and blocked when
the application is running as a frozen executable. PyInstaller also explicitly
excludes its private module name.
