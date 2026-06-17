param(
    [int]$SlowMs = 250,
    [int]$IntervalMs = 100
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:TRUBA_GUI_PERF_DEBUG = "1"
$env:TRUBA_GUI_PERF_SLOW_MS = "$SlowMs"
$env:TRUBA_GUI_PERF_INTERVAL_MS = "$IntervalMs"
$env:PYTHONPATH = Join-Path $Root "src"

Set-Location $Root
$venvPython = Join-Path $Root ".venv/Scripts/python.exe"
if (Test-Path $venvPython) {
    & $venvPython -m truba_gui
} else {
    python -m truba_gui
}
