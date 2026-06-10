from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from truba_gui import __version__
from truba_gui.core.paths import app_data_dir, is_frozen_exe


GITHUB_REPOSITORY = "mskomek/truba-client-gui"
GITHUB_LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
)


@dataclass(frozen=True)
class UpdateRelease:
    version: str
    tag: str
    zip_name: str
    zip_url: str
    sha_name: str
    sha_url: str
    html_url: str


def _request(url: str, timeout: float = 30.0):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"TrubaGUI/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)+)", value or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    candidate_parts = _version_tuple(candidate)
    current_parts = _version_tuple(current)
    if not candidate_parts or not current_parts:
        return False
    width = max(len(candidate_parts), len(current_parts))
    return candidate_parts + (0,) * (width - len(candidate_parts)) > (
        current_parts + (0,) * (width - len(current_parts))
    )


def get_latest_release(timeout: float = 30.0) -> UpdateRelease:
    with _request(GITHUB_LATEST_RELEASE_API, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))

    tag = str(payload.get("tag_name") or "")
    version_match = re.search(r"(\d+(?:\.\d+)+)", tag)
    if not version_match:
        raise RuntimeError("GitHub release tag does not contain a version.")
    version = version_match.group(1)

    expected_zip = f"truba-client-gui_v{version}_windows_onedir.zip"
    expected_sha = f"{expected_zip}.sha256"
    assets = {
        str(asset.get("name") or ""): str(asset.get("browser_download_url") or "")
        for asset in payload.get("assets") or []
    }
    if not assets.get(expected_zip) or not assets.get(expected_sha):
        raise RuntimeError(
            f"Release assets are incomplete: {expected_zip} and {expected_sha} are required."
        )

    return UpdateRelease(
        version=version,
        tag=tag,
        zip_name=expected_zip,
        zip_url=assets[expected_zip],
        sha_name=expected_sha,
        sha_url=assets[expected_sha],
        html_url=str(payload.get("html_url") or ""),
    )


def _download(url: str, destination: Path, timeout: float = 120.0) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with _request(url, timeout=timeout) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def download_and_verify_release(release: UpdateRelease) -> Path:
    update_dir = app_data_dir() / "updates" / f"v{release.version}"
    zip_path = update_dir / release.zip_name
    sha_path = update_dir / release.sha_name

    _download(release.sha_url, sha_path)
    _download(release.zip_url, zip_path)

    expected = sha_path.read_text(encoding="ascii", errors="ignore").strip().split()[0]
    actual = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if not expected or actual.lower() != expected.lower():
        zip_path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded update SHA256 verification failed.")
    return zip_path


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_update_script(
    *,
    zip_path: Path,
    install_dir: Path,
    current_exe: Path,
    new_version: str,
    process_id: int,
) -> str:
    new_exe = install_dir / f"truba-client-gui_v{new_version}_windows.exe"
    staging_dir = zip_path.parent / "staging"
    backup_internal = zip_path.parent / "_internal.backup"
    install_log = zip_path.parent / "update-install.log"
    return f"""$ErrorActionPreference = "Stop"
$oldPid = {process_id}
$zipPath = {_powershell_literal(str(zip_path))}
$installDir = {_powershell_literal(str(install_dir))}
$stagingDir = {_powershell_literal(str(staging_dir))}
$backupInternal = {_powershell_literal(str(backup_internal))}
$installLog = {_powershell_literal(str(install_log))}
$currentExe = {_powershell_literal(str(current_exe))}
$newExe = {_powershell_literal(str(new_exe))}

function Write-UpdateLog([string]$Message) {{
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $installLog -Value "$timestamp $Message" -Encoding utf8
}}

Write-UpdateLog "Waiting for application process $oldPid"
Wait-Process -Id $oldPid -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

try {{
    if (Test-Path -LiteralPath $stagingDir) {{
        Remove-Item -LiteralPath $stagingDir -Recurse -Force
    }}
    New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $stagingDir -Force

    $internalDir = Join-Path $installDir "_internal"
    if (Test-Path -LiteralPath $backupInternal) {{
        Remove-Item -LiteralPath $backupInternal -Recurse -Force
    }}
    if (Test-Path -LiteralPath $internalDir) {{
        Move-Item -LiteralPath $internalDir -Destination $backupInternal
    }}

    Copy-Item -Path (Join-Path $stagingDir "*") -Destination $installDir -Recurse -Force
    if (-not (Test-Path -LiteralPath $newExe)) {{
        throw "Updated executable not found: $newExe"
    }}

    $newProcess = Start-Process -FilePath $newExe -WorkingDirectory $installDir -PassThru
    Start-Sleep -Seconds 5
    $newProcess.Refresh()
    if ($newProcess.HasExited -and $newProcess.ExitCode -ne 0) {{
        throw "Updated application exited with code $($newProcess.ExitCode)"
    }}

    if (($currentExe -ne $newExe) -and (Test-Path -LiteralPath $currentExe)) {{
        Remove-Item -LiteralPath $currentExe -Force
    }}
    if (Test-Path -LiteralPath $backupInternal) {{
        Remove-Item -LiteralPath $backupInternal -Recurse -Force
    }}
    Write-UpdateLog "Update to v{new_version} completed"
}} catch {{
    Write-UpdateLog "Update failed: $($_.Exception.Message)"
    $internalDir = Join-Path $installDir "_internal"
    if (Test-Path -LiteralPath $internalDir) {{
        Remove-Item -LiteralPath $internalDir -Recurse -Force
    }}
    if (Test-Path -LiteralPath $backupInternal) {{
        Move-Item -LiteralPath $backupInternal -Destination $internalDir
    }}
    if (($newExe -ne $currentExe) -and (Test-Path -LiteralPath $newExe)) {{
        Remove-Item -LiteralPath $newExe -Force
    }}
    if (Test-Path -LiteralPath $currentExe) {{
        Start-Process -FilePath $currentExe -WorkingDirectory $installDir
    }}
    exit 1
}}
"""


def launch_update_installer(zip_path: Path, new_version: str) -> None:
    if not is_frozen_exe():
        raise RuntimeError("Automatic installation is available only in the packaged app.")

    current_exe = Path(sys.executable).resolve()
    install_dir = current_exe.parent
    if not os.access(install_dir, os.W_OK):
        raise RuntimeError("The application folder is not writable.")

    script_path = zip_path.parent / "install_update.ps1"
    script_path.write_text(
        build_update_script(
            zip_path=zip_path.resolve(),
            install_dir=install_dir,
            current_exe=current_exe,
            new_version=new_version,
            process_id=os.getpid(),
        ),
        encoding="utf-8-sig",
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=str(install_dir),
        creationflags=creationflags,
        close_fds=True,
    )
