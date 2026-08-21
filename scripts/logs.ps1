[CmdletBinding()]
param(
    [ValidateRange(10, 5000)]
    [int]$Tail = 200
)

$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Push-Location $workspaceRoot
try {
    docker compose logs --tail $Tail
} finally {
    Pop-Location
}

