$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$agent = Join-Path $repo "runner\local_agent.py"

Push-Location $repo
try {
    foreach ($entry in @(
        @{ Role = "implementer"; Model = "qwen3.5:4b" },
        @{ Role = "validator"; Model = "qwen3.5:9b" }
    )) {
        $evidence = Join-Path ([System.IO.Path]::GetTempPath()) (
            "truba_{0}_agent_health_{1}.json" -f $entry.Role, [guid]::NewGuid().ToString("N")
        )
        try {
            $process = Start-Process -FilePath "python" -ArgumentList @(
                $agent,
                "--health",
                "--role", $entry.Role,
                "--model", $entry.Model,
                "--timeout", "180",
                "--evidence-file", $evidence
            ) -WorkingDirectory $repo -WindowStyle Hidden -Wait -PassThru
            if (-not (Test-Path -LiteralPath $evidence)) {
                throw "$($entry.Role)_local did not produce health evidence"
            }
            $result = Get-Content -Raw -LiteralPath $evidence | ConvertFrom-Json
            $result | ConvertTo-Json -Depth 8
            if ($process.ExitCode -ne 0 -or $result.status -ne "PASS") {
                throw "$($entry.Role)_local tool health failed with exit code $($process.ExitCode)"
            }
        }
        finally {
            Remove-Item -LiteralPath $evidence -Force -ErrorAction SilentlyContinue
        }
    }
}
finally {
    Pop-Location
}
