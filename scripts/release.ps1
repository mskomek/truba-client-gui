param(
    [string]$Version = "dev"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$spec = "build/windows/truba-client-gui.spec"
Write-Host "Building with PyInstaller spec: $spec"
pyinstaller -y --clean $spec
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Clean build failed, retrying without --clean"
    pyinstaller -y $spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }
}

$distDir = Join-Path $Root "dist/truba-client-gui"
if (-not (Test-Path $distDir)) {
    throw "Expected ONEDIR output not found: $distDir"
}

$changelogSrc = Join-Path $Root "src/truba_gui/docs/CHANGELOG.md"
if (-not (Test-Path $changelogSrc)) {
    throw "Expected changelog source not found: $changelogSrc"
}

$distChangelogPath = Join-Path $distDir "CHANGELOG.txt"
Copy-Item -Path $changelogSrc -Destination $distChangelogPath -Force

$releaseChangelogName = "CHANGELOG_v$Version.md"
$releaseChangelogPath = Join-Path $Root "dist/$releaseChangelogName"
Copy-Item -Path $changelogSrc -Destination $releaseChangelogPath -Force

$releaseExeName = "truba-client-gui_v$Version`_windows.exe"
$releaseExePath = Join-Path $Root "dist/$releaseExeName"
Copy-Item -Path (Join-Path $distDir "truba-client-gui.exe") -Destination $releaseExePath -Force

$releaseZipName = "truba-client-gui_v$Version`_windows_onedir.zip"
$releaseZipPath = Join-Path $Root "dist/$releaseZipName"
if (Test-Path $releaseZipPath) { Remove-Item $releaseZipPath -Force }

Compress-Archive -Path "$distDir/*" -DestinationPath $releaseZipPath -Force

$releaseShaPath = "$releaseZipPath.sha256"
$hash = Get-FileHash $releaseZipPath -Algorithm SHA256
"$($hash.Hash)  $releaseZipName" | Set-Content -Path $releaseShaPath -Encoding ascii

Write-Host "Release artifacts:"
Write-Host " - $releaseChangelogPath"
Write-Host " - $releaseExePath"
Write-Host " - $releaseZipPath"
Write-Host " - $releaseShaPath"
