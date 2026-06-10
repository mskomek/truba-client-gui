param(
    [string]$Version = "dev",
    [string]$ReleaseRoot = "dist/releases"
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

function Get-ChangelogSection {
    param(
        [string]$Path,
        [string]$Version
    )

    $lines = Get-Content -Path $Path
    $escapedVersion = [regex]::Escape($Version)
    $start = -1

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^##\s+v$escapedVersion\s*$") {
            $start = $i
            break
        }
    }

    if ($start -lt 0) {
        throw "Changelog section not found for v$Version in $Path"
    }

    $end = $lines.Count
    for ($i = $start + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^##\s+') {
            $end = $i
            break
        }
    }

    return ($lines[$start..($end - 1)] -join [Environment]::NewLine)
}

$releaseChangelogContent = Get-ChangelogSection -Path $changelogSrc -Version $Version

$releaseBase = Join-Path $Root $ReleaseRoot
$versionDir = Join-Path $releaseBase "v$Version"
if (Test-Path $versionDir) {
    Remove-Item $versionDir -Recurse -Force
}
New-Item -ItemType Directory -Path $versionDir -Force | Out-Null

Copy-Item -Path (Join-Path $distDir "*") -Destination $versionDir -Recurse -Force
if (Test-Path (Join-Path $Root "templates")) {
    Copy-Item -Path (Join-Path $Root "templates") -Destination $versionDir -Recurse -Force
}

$exePath = Join-Path $versionDir "truba-client-gui.exe"
if (-not (Test-Path $exePath)) {
    throw "Expected packaged exe not found: $exePath"
}

$releaseExeName = "truba-client-gui.exe"

$releaseChangelogPath = Join-Path $versionDir "CHANGELOG.md"
Set-Content -Path $releaseChangelogPath -Value $releaseChangelogContent -Encoding utf8

$releaseZipName = "truba-client-gui_windows_onedir.zip"
$releaseZipPath = Join-Path $versionDir $releaseZipName
if (Test-Path $releaseZipPath) { Remove-Item $releaseZipPath -Force }

Compress-Archive -Path (Join-Path $versionDir "*") -DestinationPath $releaseZipPath -Force

$releaseShaPath = "$releaseZipPath.sha256"
$hash = Get-FileHash $releaseZipPath -Algorithm SHA256
"$($hash.Hash)  $releaseZipName" | Set-Content -Path $releaseShaPath -Encoding ascii

Write-Host "Release artifacts:"
Write-Host " - $releaseChangelogPath"
Write-Host " - $(Join-Path $versionDir $releaseExeName)"
Write-Host " - $releaseZipPath"
Write-Host " - $releaseShaPath"
