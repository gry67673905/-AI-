[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Question = "办理社会保障卡需要准备哪些材料？",
    [switch]$SecondPaidCall
)

$ErrorActionPreference = "Stop"
$base = $BaseUrl.TrimEnd('/')

$ready = Invoke-RestMethod -Method Get -Uri "$base/health/ready" -TimeoutSec 20
if ($ready.status -ne "ready") {
    throw "Backend is not ready: $($ready | ConvertTo-Json -Depth 10 -Compress)"
}

$catalog = Invoke-RestMethod -Method Get -Uri "$base/api/v1/services?q=%E7%A4%BE%E4%BC%9A%E4%BF%9D%E9%9A%9C%E5%8D%A1" -TimeoutSec 20
$service = @($catalog.items | Where-Object { $_.code -eq "DEMO-SS-CARD-001" }) | Select-Object -First 1
if ($null -eq $service -or [string]::IsNullOrWhiteSpace([string]$service.id)) {
    throw "The exact social security card demo service was not found."
}
if ($null -eq $service.external_item_id) {
    throw "The selected local service is not mapped to the external demo catalogue."
}

$body = @{ message = $Question; service_id = $service.id } | ConvertTo-Json
$first = Invoke-RestMethod -Method Post -Uri "$base/api/v1/chat" -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 120

if ([string]::IsNullOrWhiteSpace([string]$first.answer)) {
    throw "The paid chat response did not contain an answer."
}
$sourceKinds = @($first.sources | ForEach-Object { $_.kind })
foreach ($requiredSource in @("local_catalog", "mcp", "rag")) {
    if ($sourceKinds -notcontains $requiredSource) {
        throw "The paid response did not include every required grounded source type."
    }
}

# RetrievalCache.key_for uses NFKC + lower-case + collapsed whitespace and a
# public context derived from the selected service's external mapping. Checking
# the exact v2 key proves that retrieval context was written without paying for
# a second model invocation.
$normalizedQuestion = $Question.Normalize([Text.NormalizationForm]::FormKC).ToLowerInvariant()
$normalizedQuestion = ([regex]::Replace($normalizedQuestion, '\s+', ' ')).Trim()
$keyInput = "$normalizedQuestion|service:$($service.external_item_id)"
$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $digestBytes = $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($keyInput))
} finally {
    $sha256.Dispose()
}
$digest = -join ($digestBytes | ForEach-Object { $_.ToString("x2") })
$cacheKey = "smart-gov:retrieval:v2:$digest"

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $workspaceRoot
try {
    $cacheExistsText = docker compose exec -T redis redis-cli EXISTS $cacheKey
    if ($LASTEXITCODE -ne 0) { throw "Unable to verify the Redis retrieval cache." }
} finally {
    Pop-Location
}
$cacheExistsLines = @($cacheExistsText | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
$cacheWritten = $cacheExistsLines.Count -gt 0 -and $cacheExistsLines[-1] -eq "1"
if (-not $cacheWritten) {
    throw "The expected Redis v2 retrieval cache entry was not written."
}

$secondCacheHit = $null
if ($SecondPaidCall) {
    $secondBody = @{
        session_id = $first.session_id
        message = $Question
        service_id = $service.id
    } | ConvertTo-Json
    $second = Invoke-RestMethod -Method Post -Uri "$base/api/v1/chat" -ContentType "application/json; charset=utf-8" -Body $secondBody -TimeoutSec 120
    $secondCacheHit = [bool]$second.cache_hit
    if (-not $secondCacheHit) {
        throw "The explicitly requested second paid call did not report a Redis cache hit."
    }
}

[pscustomobject]@{
    status = "ok"
    paid_chat_calls = if ($SecondPaidCall) { 2 } else { 1 }
    request_id = $first.request_id
    source_types = ($sourceKinds -join ',')
    retrieval_cache_v2_written = $cacheWritten
    second_paid_call_cache_hit = $secondCacheHit
} | ConvertTo-Json -Depth 5
