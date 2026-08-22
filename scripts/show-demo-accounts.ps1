[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $workspaceRoot ".env"

if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Missing .env. Run scripts\init-env.ps1 first."
}

$values = @{}
foreach ($line in Get-Content -LiteralPath $envPath) {
    if ($line -match '^([A-Z0-9_]+)=(.*)$') {
        $values[$Matches[1]] = $Matches[2]
    }
}

$required = @(
    "DEMO_ADMIN_USERNAME",
    "DEMO_ADMIN_PASSWORD",
    "DEMO_STAFF_USERNAME",
    "DEMO_STAFF_PASSWORD"
)
foreach ($name in $required) {
    if ([string]::IsNullOrWhiteSpace([string]$values[$name])) {
        throw "Missing $name. Re-run scripts\init-env.ps1 to upgrade the local environment."
    }
}

Write-Warning "These credentials are only for the loopback local demo. Never use them in a cloud deployment."
@(
    [pscustomobject]@{
        role = "ADMIN"
        username = $values["DEMO_ADMIN_USERNAME"]
        password = $values["DEMO_ADMIN_PASSWORD"]
    }
    [pscustomobject]@{
        role = "STAFF"
        username = $values["DEMO_STAFF_USERNAME"]
        password = $values["DEMO_STAFF_PASSWORD"]
    }
) | Format-Table -AutoSize
