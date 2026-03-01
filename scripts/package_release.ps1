param(
    [string]$Version = "dev"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$distDir = Join-Path $Root "dist/truba-client-gui"
if (-not (Test-Path $distDir)) {
    throw "Expected ONEDIR output not found: $distDir"
}

$changelogSrc = Join-Path $Root "src/truba_gui/docs/CHANGELOG.md"
$changelogOut = Join-Path $distDir "CHANGELOG.txt"
if (Test-Path $changelogSrc) {
    (Get-Content $changelogSrc -Raw) | Set-Content -Path $changelogOut -Encoding utf8
}

$zipName = "truba-client-gui_v$Version`_windows_onedir.zip"
$zipPath = Join-Path $Root "dist/$zipName"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "$distDir/*" -DestinationPath $zipPath -Force

$shaPath = "$zipPath.sha256"
$hash = Get-FileHash $zipPath -Algorithm SHA256
"$($hash.Hash)  $zipName" | Set-Content -Path $shaPath -Encoding ascii

Write-Host "Release artifacts:"
Write-Host " - $zipPath"
Write-Host " - $shaPath"
