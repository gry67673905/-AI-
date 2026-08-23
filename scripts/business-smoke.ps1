[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$base = $BaseUrl.TrimEnd('/')
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $workspaceRoot ".env"

if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Missing .env. Run scripts\init-env.ps1 first."
}

$localSettings = @{}
foreach ($line in Get-Content -LiteralPath $envPath) {
    if ($line -match '^([A-Z0-9_]+)=(.*)$') {
        $localSettings[$Matches[1]] = $Matches[2]
    }
}
foreach ($requiredName in @(
    "DEMO_SMS_CODE",
    "DEMO_ADMIN_USERNAME",
    "DEMO_ADMIN_PASSWORD",
    "DEMO_STAFF_USERNAME",
    "DEMO_STAFF_PASSWORD"
)) {
    if ([string]::IsNullOrWhiteSpace([string]$localSettings[$requiredName])) {
        throw "Missing required local setting $requiredName. Re-run scripts\init-env.ps1."
    }
}

function Invoke-DemoJson {
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
        $parameters["ContentType"] = "application/json; charset=utf-8"
        $parameters["Body"] = $Body | ConvertTo-Json -Depth 20 -Compress
    }
    try {
        return Invoke-RestMethod @parameters
    } catch {
        throw "Business smoke failed at '$Step'. Inspect API logs with scripts\logs.ps1."
    }
}

function New-AuthHeaders {
    param([Parameter(Mandatory = $true)][string]$Token)
    return @{ Authorization = "Bearer $Token" }
}

function New-WriteHeaders {
    param([Parameter(Mandatory = $true)][string]$Token)
    return @{
        Authorization = "Bearer $Token"
        "Idempotency-Key" = (New-Guid).ToString()
    }
}

function Send-DemoPdfMaterial {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][string]$RequirementCode,
        [Parameter(Mandatory = $true)][string]$FileName
    )

    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    try {
        $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
        $form.Add([System.Net.Http.StringContent]::new($RequirementCode), "requirement_code")
        $form.Add([System.Net.Http.StringContent]::new("true"), "synthetic_data_confirmed")
        $pdfBytes = [Text.Encoding]::ASCII.GetBytes("%PDF-1.4`n1 0 obj`n<<>>`nendobj`ntrailer`n<<>>`n%%EOF`n")
        $fileContent = [System.Net.Http.ByteArrayContent]::new($pdfBytes)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new("application/pdf")
        $form.Add($fileContent, "file", $FileName)
        $response = $client.PostAsync($Uri, $form).GetAwaiter().GetResult()
        $responseText = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "Material upload returned HTTP $([int]$response.StatusCode)."
        }
        return $responseText | ConvertFrom-Json
    } catch {
        throw "Business smoke failed while uploading a synthetic material. Inspect API logs with scripts\logs.ps1."
    } finally {
        $form.Dispose()
        $client.Dispose()
    }
}

function Send-DemoKnowledge {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][string]$UniqueSuffix
    )

    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    try {
        $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
        $form.Add([System.Net.Http.StringContent]::new("业务 smoke 合成知识"), "title")
        $form.Add([System.Net.Http.StringContent]::new("demo://business-smoke/$UniqueSuffix"), "source")
        $knowledgeBytes = [Text.Encoding]::UTF8.GetBytes("业务 smoke 合成知识 $UniqueSuffix。仅用于验证管理员索引与归档状态。")
        $fileContent = [System.Net.Http.ByteArrayContent]::new($knowledgeBytes)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new("text/plain")
        $form.Add($fileContent, "file", "business-smoke-$UniqueSuffix.txt")
        $response = $client.PostAsync($Uri, $form).GetAwaiter().GetResult()
        $responseText = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "Knowledge upload returned HTTP $([int]$response.StatusCode)."
        }
        return $responseText | ConvertFrom-Json
    } catch {
        throw "Business smoke failed while uploading synthetic knowledge. Inspect API logs with scripts\logs.ps1."
    } finally {
        $form.Dispose()
        $client.Dispose()
    }
}

$ready = $null
for ($attempt = 1; $attempt -le 10; $attempt++) {
    try {
        $ready = Invoke-DemoJson -Step "readiness" -Method Get -Uri "$base/health/ready"
        if ($ready.status -eq "ready") { break }
    } catch {
        # A freshly restarted API can briefly answer 503 while dependencies are
        # settling. Do not include the response body or headers in smoke output.
    }
    if ($attempt -lt 10) { Start-Sleep -Seconds 2 }
}
if ($null -eq $ready -or $ready.status -ne "ready") {
    throw "The full stack did not become ready. Inspect API logs with scripts\logs.ps1."
}

$adminAuth = Invoke-DemoJson -Step "admin login" -Method Post -Uri "$base/api/v1/auth/login" -Body @{
    username = $localSettings["DEMO_ADMIN_USERNAME"]
    password = $localSettings["DEMO_ADMIN_PASSWORD"]
}
$staffAuth = Invoke-DemoJson -Step "staff login" -Method Post -Uri "$base/api/v1/auth/login" -Body @{
    username = $localSettings["DEMO_STAFF_USERNAME"]
    password = $localSettings["DEMO_STAFF_PASSWORD"]
}

$randomSuffix = "{0}.{1}" -f [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds(), (New-Guid).ToString("N").Substring(0, 8)
$citizenAuth = Invoke-DemoJson -Step "citizen registration" -Method Post -Uri "$base/api/v1/auth/register" -Body @{
    username = "smoke.citizen.$randomSuffix"
    password = "Smoke!$((New-Guid).ToString('N'))Az9"
    display_name = "合成演示用户"
    applicant_type = "INDIVIDUAL"
    verification_code = $localSettings["DEMO_SMS_CODE"]
    synthetic_data_confirmed = $true
}

$citizenHeaders = New-AuthHeaders -Token $citizenAuth.access_token
$staffHeaders = New-AuthHeaders -Token $staffAuth.access_token
$adminHeaders = New-AuthHeaders -Token $adminAuth.access_token

$catalog = Invoke-DemoJson -Step "catalog query" -Method Get -Uri "$base/api/v1/services?q=%E7%A4%BE%E4%BC%9A%E4%BF%9D%E9%9A%9C%E5%8D%A1"
$service = @($catalog.items | Where-Object { $_.code -eq "DEMO-SS-CARD-001" }) | Select-Object -First 1
if ($null -eq $service) {
    throw "The seeded social security card demo service was not found."
}

$facts = @{
    applicant = @{
        valid_identity_document = $true
        has_duplicate_demo_card = $false
        is_minor = $false
    }
}
$eligibility = Invoke-DemoJson -Step "eligibility precheck" -Method Post -Uri "$base/api/v1/services/$($service.id)/eligibility" -Body @{ answers = $facts }
if ($eligibility.outcome -ne "ELIGIBLE") {
    throw "The synthetic eligibility precheck did not pass."
}

$draft = Invoke-DemoJson -Step "draft creation" -Method Post -Uri "$base/api/v1/applications" -Headers (New-WriteHeaders -Token $citizenAuth.access_token) -Body @{
    service_id = $service.id
    initial_form_data = @{
        applicant_name = "合成演示申请人"
        contact_phone = "00000000000"
        applicant = $facts.applicant
    }
}

$firstMaterial = Send-DemoPdfMaterial -Uri "$base/api/v1/applications/$($draft.id)/materials" -Token $citizenAuth.access_token -RequirementCode "ss-1" -FileName "synthetic-identity.pdf"
$secondMaterial = Send-DemoPdfMaterial -Uri "$base/api/v1/applications/$($draft.id)/materials" -Token $citizenAuth.access_token -RequirementCode "ss-2" -FileName "synthetic-photo.pdf"
if ($secondMaterial.application_version -le $firstMaterial.application_version) {
    throw "Application version did not advance after the second material upload."
}

$submitted = Invoke-DemoJson -Step "application submission" -Method Post -Uri "$base/api/v1/applications/$($draft.id)/submit" -Headers (New-WriteHeaders -Token $citizenAuth.access_token) -Body @{
    version = $secondMaterial.application_version
}
if ($submitted.status -ne "SUBMITTED") {
    throw "The application was not submitted."
}

$tasks = Invoke-DemoJson -Step "staff task query" -Method Get -Uri "$base/api/v1/staff/tasks" -Headers $staffHeaders
$task = @($tasks.items | Where-Object { $_.application.id -eq $draft.id }) | Select-Object -First 1
if ($null -eq $task) {
    throw "The submitted application did not create a staff task."
}
[void](Invoke-DemoJson -Step "first task claim" -Method Post -Uri "$base/api/v1/staff/tasks/$($task.id)/claim" -Headers (New-WriteHeaders -Token $staffAuth.access_token))

$inReview = Invoke-DemoJson -Step "staff application read" -Method Get -Uri "$base/api/v1/applications/$($draft.id)" -Headers $staffHeaders
$approved = Invoke-DemoJson -Step "staff approval" -Method Post -Uri "$base/api/v1/staff/applications/$($draft.id)/approve" -Headers (New-WriteHeaders -Token $staffAuth.access_token) -Body @{
    version = $inReview.version
    comment = "本地合成材料审核通过"
    require_payment = $false
}
if ($approved.status -ne "PROCESSING") {
    throw "The approved application did not enter PROCESSING."
}

$followUpTasks = Invoke-DemoJson -Step "completion task query" -Method Get -Uri "$base/api/v1/staff/tasks" -Headers $staffHeaders
$followUpTask = @($followUpTasks.items | Where-Object { $_.application.id -eq $draft.id }) | Select-Object -First 1
if ($null -eq $followUpTask) {
    throw "The processing application did not create a completion task."
}
[void](Invoke-DemoJson -Step "completion task claim" -Method Post -Uri "$base/api/v1/staff/tasks/$($followUpTask.id)/claim" -Headers (New-WriteHeaders -Token $staffAuth.access_token))

$processing = Invoke-DemoJson -Step "processing application read" -Method Get -Uri "$base/api/v1/applications/$($draft.id)" -Headers $staffHeaders
$completed = Invoke-DemoJson -Step "staff completion" -Method Post -Uri "$base/api/v1/staff/applications/$($draft.id)/complete" -Headers (New-WriteHeaders -Token $staffAuth.access_token) -Body @{
    version = $processing.version
    comment = "本地演示办结"
    require_payment = $false
}

$timeline = Invoke-DemoJson -Step "citizen timeline" -Method Get -Uri "$base/api/v1/applications/$($draft.id)/timeline" -Headers $citizenHeaders
$delivery = Invoke-DemoJson -Step "delivery creation" -Method Post -Uri "$base/api/v1/applications/$($draft.id)/delivery" -Headers (New-WriteHeaders -Token $citizenAuth.access_token) -Body @{
    recipient = "合成演示收件人"
    address = "演示地址 100 号"
}
$cancelledDelivery = Invoke-DemoJson -Step "delivery cancellation" -Method Post -Uri "$base/api/v1/deliveries/$($delivery.id)/cancel" -Headers (New-WriteHeaders -Token $citizenAuth.access_token)
if ($cancelledDelivery.status -ne "CANCELLED") {
    throw "The synthetic delivery was not cancelled."
}

# “社保”有两个明确候选，协调者会直接要求澄清并跳过检索与模型。
# 这为转人工生命周期提供一个确定的零 DeepSeek 会话。
$ambiguousChat = Invoke-DemoJson -Step "deterministic clarification chat" -Method Post -Uri "$base/api/v1/chat" -Headers $citizenHeaders -Body @{
    message = "社保怎么办"
}
if (-not [bool]$ambiguousChat.clarification_required) {
    throw "The ambiguous consultation did not take the deterministic no-model branch."
}
$handoff = Invoke-DemoJson -Step "handoff creation" -Method Post -Uri "$base/api/v1/consultations/handoffs" -Headers $citizenHeaders -Body @{
    session_id = $ambiguousChat.session_id
    subject = "合成演示转人工"
    department_id = $null
}
$cancelledHandoff = Invoke-DemoJson -Step "handoff cancellation" -Method Post -Uri "$base/api/v1/consultations/handoffs/$($handoff.id)/cancel" -Headers (New-WriteHeaders -Token $citizenAuth.access_token)
if ($cancelledHandoff.status -ne "CANCELLED") {
    throw "The synthetic handoff was not cancelled."
}

# Upload and archive only a unique smoke-owned document. PostgreSQL metadata and
# audit history remain; the ACTIVE vectors are removed from retrieval.
$knowledge = Send-DemoKnowledge -Uri "$base/api/v1/admin/knowledge" -Token $adminAuth.access_token -UniqueSuffix $randomSuffix
if ($knowledge.status -ne "ACTIVE") {
    throw "The synthetic knowledge document did not become ACTIVE."
}
$archivedKnowledge = Invoke-DemoJson -Step "knowledge archival" -Method Post -Uri "$base/api/v1/admin/knowledge/$($knowledge.job_id)/archive" -Headers (New-WriteHeaders -Token $adminAuth.access_token)
if ($archivedKnowledge.status -ne "ARCHIVED") {
    throw "The synthetic knowledge job was not archived."
}

$metrics = Invoke-DemoJson -Step "admin metrics" -Method Get -Uri "$base/api/v1/admin/metrics" -Headers $adminHeaders
if ($completed.status -ne "COMPLETED" -or $timeline.total -lt 5) {
    throw "The completed application or immutable timeline did not satisfy smoke assertions."
}

# Never print credentials, bearer tokens, form values, material hashes, PII, or
# response bodies. The summary contains only business-state assertions.
[pscustomobject]@{
    status = "ok"
    demo_data = $true
    service_code = $service.code
    eligibility = $eligibility.outcome
    final_application_status = $completed.status
    delivery_cancel_status = $cancelledDelivery.status
    handoff_cancel_status = $cancelledHandoff.status
    knowledge_archive_status = $archivedKnowledge.status
    timeline_events = [int]$timeline.total
    admin_metrics_reachable = ($null -ne $metrics)
    deepseek_calls = 0
} | ConvertTo-Json -Depth 4
