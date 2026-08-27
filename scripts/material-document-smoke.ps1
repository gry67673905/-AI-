[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$TimeoutSeconds = 180,
    [string]$OutputPath = "",
    [switch]$ConfirmPaidModelCall
)

$ErrorActionPreference = "Stop"
$base = $BaseUrl.TrimEnd('/')
if ($base -notmatch '^https://|^http://127\.0\.0\.1(?::\d+)?$') {
    throw "BaseUrl must be HTTPS or loopback HTTP."
}
if ($base -notmatch '^http://127\.0\.0\.1' -and -not $ConfirmPaidModelCall) {
    throw "Public smoke may call the configured visual model once; pass -ConfirmPaidModelCall."
}

function Invoke-SmokeJson {
    param(
        [Parameter(Mandatory = $true)][string]$Step,
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [object]$Body = $null,
        [hashtable]$Headers = @{}
    )
    $parameters = @{
        Method = $Method
        Uri = $Uri
        Headers = $Headers
        TimeoutSec = 30
    }
    if ($null -ne $Body) {
        $parameters.ContentType = "application/json; charset=utf-8"
        $parameters.Body = $Body | ConvertTo-Json -Depth 20 -Compress
    }
    try {
        Invoke-RestMethod @parameters
    } catch {
        throw "Material document smoke failed at '$Step'. Inspect sanitized API/Worker logs."
    }
}

function New-AuthHeaders([string]$Token) {
    @{ Authorization = "Bearer $Token" }
}

function New-WriteHeaders([string]$Token) {
    @{
        Authorization = "Bearer $Token"
        "Idempotency-Key" = (New-Guid).ToString()
    }
}

function Assert-SafeDocx([byte[]]$Bytes, [string]$ExpectedSha256) {
    if ($Bytes.Length -le 0 -or $Bytes.Length -gt 10MB) {
        throw "Downloaded DOCX size is outside the allowed range."
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $actual = [Convert]::ToHexString($sha.ComputeHash($Bytes)).ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
    if ($actual -cne $ExpectedSha256.ToLowerInvariant()) {
        throw "Downloaded DOCX SHA-256 does not match the response header."
    }

    Add-Type -AssemblyName System.IO.Compression
    $memory = [IO.MemoryStream]::new($Bytes, $false)
    $archive = [IO.Compression.ZipArchive]::new(
        $memory, [IO.Compression.ZipArchiveMode]::Read, $false
    )
    try {
        if ($archive.Entries.Count -gt 2000) { throw "DOCX contains too many entries." }
        $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        [long]$expanded = 0
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName
            if ([string]::IsNullOrWhiteSpace($name) -or $name.StartsWith('/') -or
                $name.Contains('\') -or $name.Split('/') -contains '..' -or
                -not $names.Add($name)) {
                throw "DOCX contains an unsafe package path."
            }
            $expanded += $entry.Length
            if ($expanded -gt 50MB) { throw "DOCX expanded size is too large." }
            $lower = $name.ToLowerInvariant()
            if ($lower.Contains('vbaproject') -or $lower.EndsWith('.bin') -or
                $lower.StartsWith('word/embeddings/') -or $lower.StartsWith('word/altchunk')) {
                throw "DOCX contains active or embedded content."
            }
            if ($lower.EndsWith('.rels') -or $lower -eq 'word/document.xml') {
                if ($entry.Length -gt 10MB) { throw "DOCX XML part is too large." }
                $reader = [IO.StreamReader]::new($entry.Open(), [Text.Encoding]::UTF8, $true)
                try { $xml = $reader.ReadToEnd() } finally { $reader.Dispose() }
                if ($lower.EndsWith('.rels') -and $xml -match '(?i)TargetMode\s*=\s*["'']External["'']') {
                    throw "DOCX contains an external relationship."
                }
                if ($lower -eq 'word/document.xml' -and $xml -match '(?i)<(?:[A-Z_][A-Z0-9_.-]*:)?altChunk\b') {
                    throw "DOCX contains altChunk content."
                }
            }
        }
        if (-not $names.Contains('[Content_Types].xml') -or -not $names.Contains('word/document.xml')) {
            throw "DOCX is missing required OOXML parts."
        }
    } finally {
        $archive.Dispose()
        $memory.Dispose()
    }
}

$ready = Invoke-SmokeJson -Step "readiness" -Method Get -Uri "$base/health/ready"
if ($ready.status -ne 'ready') { throw "API is not ready." }

$suffix = "{0}{1}" -f [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds(), (New-Guid).ToString('N').Substring(0, 6)
$username = "doc.smoke.$suffix"
$password = "DocSmoke!$((New-Guid).ToString('N'))Az9"
$codeResponse = Invoke-SmokeJson -Step "request demo code" -Method Post -Uri "$base/api/v1/auth/request-code" -Body @{
    destination = $username
    purpose = 'REGISTER'
}
if ([string]::IsNullOrWhiteSpace([string]$codeResponse.demo_code)) {
    throw "Demo registration code was not returned."
}
$auth = Invoke-SmokeJson -Step "register synthetic citizen" -Method Post -Uri "$base/api/v1/auth/register" -Body @{
    username = $username
    password = $password
    display_name = '材料模板合成测试用户'
    applicant_type = 'INDIVIDUAL'
    verification_code = [string]$codeResponse.demo_code
    synthetic_data_confirmed = $true
}
$token = [string]$auth.access_token
$catalog = Invoke-SmokeJson -Step "find seeded service" -Method Get -Uri "$base/api/v1/services?q=%E8%BA%AB%E4%BB%BD%E8%AF%81"
$service = @($catalog.items | Where-Object { $_.code -eq 'DEMO-ID-REISSUE-001' }) | Select-Object -First 1
if ($null -eq $service) { throw "Seeded identity reissue service was not found." }

$draft = Invoke-SmokeJson -Step "create synthetic draft" -Method Post -Uri "$base/api/v1/applications" -Headers (New-WriteHeaders $token) -Body @{
    service_id = $service.id
    initial_form_data = @{
        applicant_name = '演示申请人甲'
        contact_phone = '13800000000'
        verification = @{
            demo_identity_passed = $true
            loss_date = '2026年8月20日'
            loss_place = '成都市演示服务大厅'
            loss_description = '学生项目演示过程中发现证件遗失。'
        }
    }
}
$options = Invoke-SmokeJson -Step "load application templates" -Method Get -Uri "$base/api/v1/applications/$($draft.id)/material-template-options" -Headers (New-AuthHeaders $token)
$template = @($options.items | Where-Object {
    $_.requirement_code -eq 'id-2' -and $_.template_available -eq $true
}) | Select-Object -First 1
if ($null -eq $template) { throw "The reviewed loss-statement template is unavailable." }

$job = Invoke-SmokeJson -Step "queue material document" -Method Post -Uri "$base/api/v1/applications/$($draft.id)/material-documents" -Headers (New-WriteHeaders $token) -Body @{
    requirement_code = 'id-2'
    template_id = $template.template_id
    request_text = '预填合成联系人、遗失日期和遗失说明'
    synthetic_data_confirmed = $true
}
$generationId = [string]$job.generation_id
$deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
$status = $job
do {
    if ($status.status -in @('READY', 'FAILED', 'EXPIRED')) { break }
    Start-Sleep -Seconds 2
    $status = Invoke-SmokeJson -Step "poll generation" -Method Get -Uri "$base/api/v1/material-documents/$generationId" -Headers (New-AuthHeaders $token)
} while ([DateTimeOffset]::UtcNow -lt $deadline)
if ($status.status -ne 'READY') {
    $safeCode = if ($status.error_code) { [string]$status.error_code } else { 'TIMEOUT' }
    throw "Material document did not become READY (code: $safeCode)."
}

Add-Type -AssemblyName System.Net.Http
$client = [Net.Http.HttpClient]::new()
try {
    $client.DefaultRequestHeaders.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $token)
    $client.DefaultRequestHeaders.Accept.Add([Net.Http.Headers.MediaTypeWithQualityHeaderValue]::new('application/vnd.openxmlformats-officedocument.wordprocessingml.document'))
    $response = $client.GetAsync("$base/api/v1/material-documents/$generationId/download").GetAwaiter().GetResult()
    if (-not $response.IsSuccessStatusCode) { throw "DOCX download returned a non-success status." }
    if ($response.Content.Headers.ContentType.MediaType -cne 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') {
        throw "DOCX download returned the wrong media type."
    }
    $hashValues = $null
    if (-not $response.Headers.TryGetValues('X-Content-SHA256', [ref]$hashValues)) {
        throw "DOCX download did not include X-Content-SHA256."
    }
    $expectedSha = @($hashValues)[0]
    if ($expectedSha -notmatch '^[0-9a-fA-F]{64}$') { throw "DOCX hash header is invalid." }
    [byte[]]$bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    Assert-SafeDocx -Bytes $bytes -ExpectedSha256 $expectedSha
    if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
        $resolvedParent = Split-Path -Parent $OutputPath
        if ($resolvedParent -and -not (Test-Path -LiteralPath $resolvedParent)) {
            [void](New-Item -ItemType Directory -Path $resolvedParent)
        }
        [IO.File]::WriteAllBytes($OutputPath, $bytes)
    }
} finally {
    $client.Dispose()
}

[pscustomobject]@{
    status = 'passed'
    service = 'DEMO-ID-REISSUE-001'
    template = 'id-loss-statement-v1'
    model_calls_expected = 1
    docx_verified = $true
    output_saved = -not [string]::IsNullOrWhiteSpace($OutputPath)
}
