[CmdletBinding()]
param(
    [switch]$InstallDependencies,
    [switch]$SkipAndroid
)

$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendRoot = Join-Path $workspaceRoot "backend"
$backendPython = Join-Path $backendRoot ".venv\Scripts\python.exe"

$syntaxErrors = @()
foreach ($scriptFile in Get-ChildItem -LiteralPath (Join-Path $workspaceRoot "scripts") -Filter "*.ps1" -File) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $scriptFile.FullName,
        [ref]$tokens,
        [ref]$errors
    )
    foreach ($parseError in @($errors)) {
        $syntaxErrors += "$($scriptFile.Name):$($parseError.Extent.StartLineNumber): $($parseError.Message)"
    }
}
if ($syntaxErrors.Count -gt 0) {
    throw "PowerShell syntax validation failed:`n$($syntaxErrors -join "`n")"
}
Write-Host "PowerShell scripts passed AST syntax validation."

if (-not (Test-Path -LiteralPath $backendPython)) {
    if (-not $InstallDependencies) {
        throw "Backend virtual environment is missing. Re-run with -InstallDependencies."
    }
    & py -3.13 -m venv (Join-Path $backendRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the backend virtual environment." }
}

if ($InstallDependencies) {
    & $backendPython -m pip install --requirement (Join-Path $backendRoot "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed." }
}

Push-Location $backendRoot
try {
    & $backendPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }
} finally {
    Pop-Location
}

foreach ($nodeProject in @("mock-gov-api", "mcp-server")) {
    $projectRoot = Join-Path $workspaceRoot $nodeProject
    Push-Location $projectRoot
    try {
        if ($InstallDependencies) {
            npm ci --ignore-scripts
            if ($LASTEXITCODE -ne 0) { throw "$nodeProject dependency installation failed." }
        }
        npm run check
        if ($LASTEXITCODE -ne 0) { throw "$nodeProject syntax check failed." }
        npm test
        if ($LASTEXITCODE -ne 0) { throw "$nodeProject tests failed." }
    } finally {
        Pop-Location
    }
}

if (-not $SkipAndroid) {
    $installedGradle = "D:\AndroidDev\gradle-8.14.5\bin\gradle.bat"
    $gradle = if (Test-Path -LiteralPath $installedGradle) {
        $installedGradle
    } else {
        Join-Path $workspaceRoot "android\gradlew.bat"
    }
    Push-Location (Join-Path $workspaceRoot "android")
    try {
        & $gradle :app:lintDebug :app:testDebugUnitTest :app:assembleDebug
        if ($LASTEXITCODE -ne 0) { throw "Android lint, tests, or build failed." }
    } finally {
        Pop-Location
    }
}

Write-Host "All requested source-level checks passed."
