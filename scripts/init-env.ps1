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

function Get-QwenVisionSettings {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $apiKey = ""
    $baseUrl = ""
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*Qwen3-vl-flash\s+key\s*[：:=]\s*(.+?)\s*$') {
            $apiKey = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*Qwen3-vl-flash\s+url\s*[：:=]\s*(.+?)\s*$') {
            $baseUrl = $Matches[1].Trim().Trim('"').Trim("'").TrimEnd('/')
        }
    }
    if ([string]::IsNullOrWhiteSpace($apiKey) -and [string]::IsNullOrWhiteSpace($baseUrl)) {
        return $null
    }
    if ([string]::IsNullOrWhiteSpace($apiKey) -or [string]::IsNullOrWhiteSpace($baseUrl)) {
        throw "Qwen3-vl-flash key and url must both be present. No secret values were printed."
    }
    if ($apiKey.Length -lt 20 -or $apiKey.Length -gt 4096 -or $apiKey -notmatch '^[\x21-\x7e]+$') {
        throw "Qwen3-vl-flash key has an invalid format. No secret values were printed."
    }
    $parsedUrl = $null
    if (-not [Uri]::TryCreate($baseUrl, [UriKind]::Absolute, [ref]$parsedUrl) `
        -or $parsedUrl.Scheme -ne 'https' `
        -or $parsedUrl.Host -ne 'dashscope.aliyuncs.com' `
        -or $parsedUrl.AbsolutePath.TrimEnd('/') -ne '/compatible-mode/v1' `
        -or -not [string]::IsNullOrEmpty($parsedUrl.Query) `
        -or -not [string]::IsNullOrEmpty($parsedUrl.Fragment) `
        -or -not [string]::IsNullOrEmpty($parsedUrl.UserInfo)) {
        throw "Qwen3-vl-flash url must be the fixed DashScope HTTPS base URL."
    }
    return [pscustomobject]@{
        ApiKey = $apiKey
        BaseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    }
}

$qwenVision = Get-QwenVisionSettings -Path $KeyListPath

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
    if ($null -ne $qwenVision -and $existingNames -notcontains "VISION_DASHSCOPE_API_KEY") {
        $missingValues += "VISION_DASHSCOPE_API_KEY=$($qwenVision.ApiKey)"
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
        VISION_ENABLED = "true"
        VISION_PROVIDER = $(if ($null -ne $qwenVision) { "dashscope" } else { "mock" })
        VISION_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        VISION_TURN_CLOSE_WAIT_MS = "2000"
        VISION_ANALYSIS_GLOBAL_DAILY = "20"
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
            } elseif ($null -ne $qwenVision -and $_ -like "VISION_ENABLED=*") {
                $expectedValue = "VISION_ENABLED=true"
                $settingsUpgraded = $settingsUpgraded -or $_ -ne $expectedValue
                $expectedValue
            } elseif ($null -ne $qwenVision -and $_ -like "VISION_PROVIDER=*") {
                $expectedValue = "VISION_PROVIDER=dashscope"
                $settingsUpgraded = $settingsUpgraded -or $_ -ne $expectedValue
                $expectedValue
            } elseif ($null -ne $qwenVision -and $_ -like "VISION_DASHSCOPE_API_KEY=*") {
                $expectedValue = "VISION_DASHSCOPE_API_KEY=$($qwenVision.ApiKey)"
                $settingsUpgraded = $settingsUpgraded -or $_ -ne $expectedValue
                $expectedValue
            } elseif ($null -ne $qwenVision -and $_ -like "VISION_DASHSCOPE_BASE_URL=*") {
                $expectedValue = "VISION_DASHSCOPE_BASE_URL=$($qwenVision.BaseUrl)"
                $settingsUpgraded = $settingsUpgraded -or $_ -ne $expectedValue
                $expectedValue
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
    "LLM_MODEL=deepseek-v4-flash"
    "DEEPSEEK_API_KEY=$deepSeekKey"
    "VISION_ENABLED=true"
    "VISION_PROVIDER=$(if ($null -ne $qwenVision) { 'dashscope' } else { 'mock' })"
    "VISION_DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1"
    "VISION_TURN_CLOSE_WAIT_MS=2000"
    "VISION_ANALYSIS_GLOBAL_DAILY=20"
)
if ($null -ne $qwenVision) {
    $content += "VISION_DASHSCOPE_API_KEY=$($qwenVision.ApiKey)"
}
$content += "LOG_LEVEL=INFO"

$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envPath, $content, $utf8WithoutBom)
Write-Host "Local .env created. Configured model credentials were loaded without displaying values."
