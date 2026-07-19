param(
    [string[]]$RequiredModels = @("qwen3.5:9b", "qwen3.5:4b"),
    [switch]$PullMissingModels
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Write-Status([string]$Label, [string]$Message) {
    Write-Host ("[{0}] {1}" -f $Label, $Message)
}

function Test-OllamaApi {
    try {
        $version = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -Method Get -TimeoutSec 3
        return $version
    } catch {
        return $null
    }
}

function Start-OllamaServe {
    $existing = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Status "INFO" "Ollama process is already running."
        return
    }

    $ollamaExe = (Get-Command ollama -ErrorAction Stop).Source
    Write-Status "INFO" "Starting Ollama server in the background."
    Start-Process -FilePath $ollamaExe -ArgumentList @("serve") -WindowStyle Hidden | Out-Null
}

function Get-OllamaModels {
    try {
        $models = Invoke-RestMethod -Uri "http://127.0.0.1:11434/v1/models" -Method Get -TimeoutSec 10
        return @($models.data | ForEach-Object { $_.id })
    } catch {
        return @()
    }
}

function Ensure-Model([string]$ModelName, [string[]]$AvailableModels, [switch]$Pull) {
    if ($AvailableModels -contains $ModelName) {
        Write-Status "OK" "Model present: $ModelName"
        return $true
    }

    if (-not $Pull) {
        Write-Status "WARN" "Model missing: $ModelName"
        return $false
    }

    Write-Status "INFO" "Pulling model: $ModelName"
    & ollama pull $ModelName
    if ($LASTEXITCODE -ne 0) {
        Write-Status "FAIL" "Model pull failed: $ModelName"
        return $false
    }
    Write-Status "OK" "Model pulled: $ModelName"
    return $true
}

try {
    $ollama = Get-Command ollama -ErrorAction Stop
    Write-Status "OK" "Ollama command found: $($ollama.Source)"
} catch {
    Write-Status "FAIL" "Ollama command not found on PATH."
    exit 2
}

$apiVersion = Test-OllamaApi
if (-not $apiVersion) {
    Write-Status "INFO" "Ollama API is not reachable on 127.0.0.1:11434; starting the server."
    Start-OllamaServe

    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        $apiVersion = Test-OllamaApi
        if ($apiVersion) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        Write-Status "FAIL" "Ollama API did not become ready."
        exit 3
    }
}

Write-Status "OK" ("Ollama API ready: {0}" -f ($apiVersion.version | ForEach-Object { $_ }))

$models = Get-OllamaModels
if (-not $models) {
    Write-Status "WARN" "Could not read the model list from the API."
}

$allOk = $true
foreach ($model in $RequiredModels) {
    $ok = Ensure-Model -ModelName $model -AvailableModels $models -Pull:$PullMissingModels
    if (-not $ok) {
        $allOk = $false
    }
}

Write-Host ""
Write-Status "INFO" "Codex agent config"
Write-Status "INFO" "  .codex/agents/implementer_local.toml"
Write-Status "INFO" "  .codex/agents/validator_local.toml"
Write-Status "INFO" "  .codex/config.toml uses the local_ollama_truba provider"

if ($allOk) {
    Write-Status "OK" "Ollama bootstrap check passed."
    exit 0
}

Write-Status "WARN" "Ollama bootstrap check completed with missing models."
if ($PullMissingModels) {
    exit 4
}
exit 1
