[CmdletBinding()]
param(
    [switch]$StatusOnly
)

$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is unavailable."
}
if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot ".env"))) {
    throw "Missing .env. Run scripts\init-env.ps1 first."
}

Push-Location $workspaceRoot
try {
    $runningServices = @(docker compose ps --status running --services)
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect the Compose stack." }
    if ($runningServices -notcontains "api" -or $runningServices -notcontains "postgres") {
        throw "API and PostgreSQL must be running. Run scripts\dev-up.ps1 first."
    }

    Write-Host "Declared Alembic head:"
    docker compose exec -T api alembic heads
    if ($LASTEXITCODE -ne 0) { throw "Unable to read the declared migration head." }

    Write-Host "Current database revision:"
    docker compose exec -T api alembic current
    if ($LASTEXITCODE -ne 0) { throw "Unable to read the current database revision." }

    if (-not $StatusOnly) {
        Write-Host "Applying forward-only, non-destructive migrations to head..."
        docker compose exec -T api alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed." }

        Write-Host "Database revision after upgrade:"
        docker compose exec -T api alembic current
        if ($LASTEXITCODE -ne 0) { throw "Unable to verify the upgraded revision." }
    }
} finally {
    Pop-Location
}

Write-Host "Migration check completed. No downgrade or volume deletion was performed."
