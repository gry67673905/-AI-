[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is unavailable. Install and start Docker Desktop with the WSL2 backend first."
}
if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot ".env"))) {
    throw "Missing .env. Run scripts\init-env.ps1 first."
}

Push-Location $workspaceRoot
try {
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed." }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $ready = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health/ready" -TimeoutSec 5
            if ($ready.status -eq "ready") {
                Write-Host "All required services are ready."
                return
            }
        } catch {
            # Services may still be starting, especially Milvus.
        }
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)

    docker compose ps
    throw "Services did not become ready within $TimeoutSeconds seconds."
} finally {
    Pop-Location
}

