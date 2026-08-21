$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is unavailable."
}

Push-Location $workspaceRoot
try {
    docker compose down
    if ($LASTEXITCODE -ne 0) { throw "docker compose down failed." }
    Write-Host "Services stopped. Named data volumes were preserved."
} finally {
    Pop-Location
}

