[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Question = "办理社会保障卡需要准备哪些材料？"
)

$ErrorActionPreference = "Stop"
$base = $BaseUrl.TrimEnd('/')

$ready = Invoke-RestMethod -Method Get -Uri "$base/health/ready" -TimeoutSec 20
if ($ready.status -ne "ready") {
    throw "Backend is not ready: $($ready | ConvertTo-Json -Depth 10 -Compress)"
}

$body = @{ message = $Question } | ConvertTo-Json
$first = Invoke-RestMethod -Method Post -Uri "$base/api/v1/chat" -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 120
$secondBody = @{ session_id = $first.session_id; message = $Question } | ConvertTo-Json
$second = Invoke-RestMethod -Method Post -Uri "$base/api/v1/chat" -ContentType "application/json; charset=utf-8" -Body $secondBody -TimeoutSec 120

if ([string]::IsNullOrWhiteSpace([string]$first.answer)) {
    throw "The first chat response did not contain an answer."
}
$sourceKinds = @($first.sources | ForEach-Object { $_.kind })
if ($sourceKinds -notcontains "mcp" -or $sourceKinds -notcontains "rag") {
    throw "The first response did not include both MCP and RAG sources."
}
if (-not [bool]$second.cache_hit) {
    throw "The repeated request did not report a Redis cache hit."
}

[pscustomobject]@{
    status = "ok"
    request_id = $first.request_id
    session_id = $first.session_id
    source_types = ($sourceKinds -join ',')
    repeated_request_cache_hit = [bool]$second.cache_hit
} | ConvertTo-Json -Depth 5
