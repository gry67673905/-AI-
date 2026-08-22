[CmdletBinding()]
param(
    [string]$KeyListPath = ""
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($KeyListPath)) {
    $KeyListPath = Join-Path $PSScriptRoot "..\..\key-list.txt"
}
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $workspaceRoot ".env"

function New-LocalSecret {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    } finally {
        $generator.Dispose()
    }
    return -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

if (Test-Path -LiteralPath $envPath) {
    $existingLines = @(Get-Content -LiteralPath $envPath)
    $existingNames = @(
        $existingLines | ForEach-Object {
            if ($_ -match '^([A-Z0-9_]+)=') { $Matches[1] }
        }
    )
    $missingValues = @()
    if ($existingNames -notcontains "MINIO_ROOT_USER") {
        $missingValues += "MINIO_ROOT_USER=smartgov$((New-LocalSecret).Substring(0, 16))"
    }
    if ($existingNames -notcontains "MINIO_ROOT_PASSWORD") {
        $missingValues += "MINIO_ROOT_PASSWORD=$(New-LocalSecret)"
    }
    $requiredLocalValues = [ordered]@{
        MINIO_ENDPOINT = "http://minio:9000"
        MATERIALS_BUCKET = "smart-gov-materials"
        KNOWLEDGE_BUCKET = "smart-gov-knowledge"
        MAX_MATERIAL_BYTES = "10485760"
        JWT_SIGNING_KEY = (New-LocalSecret)
        JWT_ACCESS_MINUTES = "15"
        JWT_REFRESH_DAYS = "7"
        PII_HMAC_KEY = (New-LocalSecret)
        PII_ENCRYPTION_KEY = (New-LocalSecret)
        ENABLE_DEMO_PROVIDERS = "true"
        DEMO_SMS_CODE = "000000"
        DEMO_ADMIN_USERNAME = "admin.demo"
        DEMO_ADMIN_PASSWORD = "DemoA!$(New-LocalSecret)"
        DEMO_STAFF_USERNAME = "staff.demo"
        DEMO_STAFF_PASSWORD = "DemoS!$(New-LocalSecret)"
        MCP_SESSION_TTL_MS = "900000"
        MCP_MAX_SESSIONS = "128"
    }
    foreach ($entry in $requiredLocalValues.GetEnumerator()) {
        $hasLegacyMaterialLimit = $entry.Key -eq "MAX_MATERIAL_BYTES" -and $existingNames -contains "MAX_UPLOAD_BYTES"
        if ($existingNames -notcontains $entry.Key -and -not $hasLegacyMaterialLimit) {
            $missingValues += "$($entry.Key)=$($entry.Value)"
        }
    }
    $settingsUpgraded = $false
    $updatedLines = @(
        $existingLines | ForEach-Object {
            if ($_ -eq "MILVUS_COLLECTION=gov_knowledge_v1") {
                $settingsUpgraded = $true
                "MILVUS_COLLECTION=gov_knowledge_v2"
            } elseif ($_ -like "MAX_UPLOAD_BYTES=*") {
                $settingsUpgraded = $true
                $_ -replace '^MAX_UPLOAD_BYTES=', 'MAX_MATERIAL_BYTES='
            } else {
                $_
            }
        }
    )
    if ($missingValues.Count -gt 0 -or $settingsUpgraded) {
        $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllLines($envPath, @($updatedLines + $missingValues), $utf8WithoutBom)
        Write-Host "Missing local business settings were added or upgraded; secret values were not displayed."
    } else {
        Write-Host "Local .env already exists and was left unchanged."
    }
    return
}
if (-not (Test-Path -LiteralPath $KeyListPath)) {
    throw "Key list was not found: $KeyListPath"
}

function Get-SecretValue {
    param([string]$Label)

    $escaped = [regex]::Escape($Label)
    foreach ($line in Get-Content -LiteralPath $KeyListPath) {
        if ($line -match "^\s*$escaped\s*(?:=|:|\s)\s*(.+?)\s*$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

$deepSeekKey = Get-SecretValue -Label "deepseeek-key"
if ([string]::IsNullOrWhiteSpace($deepSeekKey)) {
    throw "The deepseeek-key entry is missing or empty. No secret values were printed."
}

$postgresPassword = New-LocalSecret
$mcpToken = New-LocalSecret
$govApiToken = New-LocalSecret
$minioUser = "smartgov$((New-LocalSecret).Substring(0, 16))"
$minioPassword = New-LocalSecret
$databaseUrl = "postgresql+asyncpg://smart_gov:$postgresPassword@postgres:5432/smart_gov"

$content = @(
    "COMPOSE_PROJECT_NAME=smart-gov-assistant"
    "POSTGRES_DB=smart_gov"
    "POSTGRES_USER=smart_gov"
    "POSTGRES_PASSWORD=$postgresPassword"
    "DATABASE_URL=$databaseUrl"
    "REDIS_URL=redis://redis:6379/0"
    "CACHE_TTL_SECONDS=300"
    "MILVUS_URI=http://milvus:19530"
    "MILVUS_COLLECTION=gov_knowledge_v2"
    "MINIO_ROOT_USER=$minioUser"
    "MINIO_ROOT_PASSWORD=$minioPassword"
    "MINIO_ENDPOINT=http://minio:9000"
    "MATERIALS_BUCKET=smart-gov-materials"
    "KNOWLEDGE_BUCKET=smart-gov-knowledge"
    "MAX_MATERIAL_BYTES=10485760"
    "JWT_SIGNING_KEY=$(New-LocalSecret)"
    "JWT_ACCESS_MINUTES=15"
    "JWT_REFRESH_DAYS=7"
    "PII_HMAC_KEY=$(New-LocalSecret)"
    "PII_ENCRYPTION_KEY=$(New-LocalSecret)"
    "ENABLE_DEMO_PROVIDERS=true"
    "DEMO_SMS_CODE=000000"
    "DEMO_ADMIN_USERNAME=admin.demo"
    "DEMO_ADMIN_PASSWORD=DemoA!$(New-LocalSecret)"
    "DEMO_STAFF_USERNAME=staff.demo"
    "DEMO_STAFF_PASSWORD=DemoS!$(New-LocalSecret)"
    "MCP_URL=http://mcp-server:3000/mcp"
    "MCP_HEALTH_URL=http://mcp-server:3000/health"
    "MCP_INTERNAL_TOKEN=$mcpToken"
    "MCP_SESSION_TTL_MS=900000"
    "MCP_MAX_SESSIONS=128"
    "GOV_API_BASE_URL=http://mock-gov-api:8080"
    "GOV_API_TOKEN=$govApiToken"
    "LLM_MODE=deepseek"
    "LLM_MODEL=deepseek-chat"
    "DEEPSEEK_API_KEY=$deepSeekKey"
    "LOG_LEVEL=INFO"
)

$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envPath, $content, $utf8WithoutBom)
Write-Host "Local .env created. DeepSeek key loaded; values were not displayed."
