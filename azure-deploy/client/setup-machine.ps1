<#
.SYNOPSIS
    Sets up a machine to forward Copilot CLI telemetry to the Azure OTel stack.

.DESCRIPTION
    Assumes the client certificate is already installed in the current user's
    cert store and already uploaded to the Entra app registration.

    This script:
    1. Finds the certificate by subject name
    2. Acquires an initial access token
    3. Creates a scheduled task to refresh the token every 30 minutes
    4. Starts a local OTel collector (Docker) that forwards to Azure with auth
    5. Sets persistent user environment variables for Copilot CLI

.EXAMPLE
    .\setup-machine.ps1
    .\setup-machine.ps1 -CertSubject "CN=my-custom-cert"
#>

param(
    [string]$TenantId = "5df6d88f-0d78-491b-9617-8b43a209ba73",
    [string]$ClientId = "1fcf6578-502c-4a18-a8e0-ac55f1ed133a",
    [string]$ServerUrl = "https://otel.andrewfaust.com",
    [string]$CertSubject = "CN=client.copilottracker.andrewfaust.com",
    [string]$TokenDir = "$env:USERPROFILE\.otel-token",
    [string]$ScriptDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

# ──────────────────────────────────────────────
# Step 1: Find the certificate
# ──────────────────────────────────────────────
Write-Host "`n=== Finding certificate ===" -ForegroundColor Cyan
$cert = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq $CertSubject } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1

if (-not $cert) {
    throw "No certificate found with subject '$CertSubject' in Cert:\CurrentUser\My. Install the cert first."
}

$CertThumbprint = $cert.Thumbprint
Write-Host "  Found: $($cert.Subject)"
Write-Host "  Thumbprint: $CertThumbprint"
Write-Host "  Expires: $($cert.NotAfter.ToString('yyyy-MM-dd'))"

# ──────────────────────────────────────────────
# Step 2: Acquire initial token
# ──────────────────────────────────────────────
Write-Host "`n=== Acquiring initial token ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $TokenDir -Force | Out-Null

$refreshScript = Join-Path $ScriptDir "refresh-token.ps1"
& $refreshScript -TenantId $TenantId -ClientId $ClientId -CertThumbprint $CertThumbprint -TokenFilePath "$TokenDir\token"

# ──────────────────────────────────────────────
# Step 3: Scheduled task for token refresh
# ──────────────────────────────────────────────
Write-Host "`n=== Installing scheduled task ===" -ForegroundColor Cyan
$taskName = "CopilotOTelTokenRefresh"

$action = New-ScheduledTaskAction `
    -Execute "pwsh.exe" `
    -Argument "-NoProfile -NonInteractive -File `"$refreshScript`" -TenantId `"$TenantId`" -ClientId `"$ClientId`" -CertThumbprint `"$CertThumbprint`" -TokenFilePath `"$TokenDir\token`""

$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "  Scheduled task '$taskName' registered (runs every 30 minutes)."

# ──────────────────────────────────────────────
# Step 4: Start local OTel collector
# ──────────────────────────────────────────────
Write-Host "`n=== Starting local OTel collector ===" -ForegroundColor Cyan

$envContent = @"
SERVER_URL=$ServerUrl
TOKEN_DIR=$($TokenDir -replace '\\','/')
"@
$envContent | Set-Content (Join-Path $ScriptDir ".env")

$collectorCompose = Join-Path $ScriptDir "docker-compose.yaml"
docker compose -f $collectorCompose up -d

# ──────────────────────────────────────────────
# Step 5: Set persistent environment variables
# ──────────────────────────────────────────────
Write-Host "`n=== Setting environment variables ===" -ForegroundColor Cyan

# Shared OTel variables (used by both Copilot CLI and Claude Code)
[Environment]::SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318", "User")
[Environment]::SetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES", "host.name=$env:COMPUTERNAME", "User")

# Claude Code specific
[Environment]::SetEnvironmentVariable("CLAUDE_CODE_ENABLE_TELEMETRY", "1", "User")
[Environment]::SetEnvironmentVariable("OTEL_METRICS_EXPORTER", "otlp", "User")
[Environment]::SetEnvironmentVariable("OTEL_LOGS_EXPORTER", "otlp", "User")

# Also set in current session
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4318"
$env:OTEL_RESOURCE_ATTRIBUTES = "host.name=$env:COMPUTERNAME"
$env:CLAUDE_CODE_ENABLE_TELEMETRY = "1"
$env:OTEL_METRICS_EXPORTER = "otlp"
$env:OTEL_LOGS_EXPORTER = "otlp"

Write-Host "  OTEL_EXPORTER_OTLP_ENDPOINT  = http://localhost:4318"
Write-Host "  OTEL_RESOURCE_ATTRIBUTES     = host.name=$env:COMPUTERNAME"
Write-Host "  CLAUDE_CODE_ENABLE_TELEMETRY = 1"
Write-Host "  OTEL_METRICS_EXPORTER        = otlp"
Write-Host "  OTEL_LOGS_EXPORTER           = otlp"
Write-Host "  (Set as persistent User environment variables)"

# ──────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────
Write-Host "`n=== Setup complete ===" -ForegroundColor Green
Write-Host "  Certificate:  $($cert.Subject) ($CertThumbprint)"
Write-Host "  Token file:   $TokenDir\token"
Write-Host "  Token refresh: Every 30 minutes via scheduled task"
Write-Host "  Collector:    localhost:4317 (gRPC), localhost:4318 (HTTP)"
Write-Host "  Forwarding:   $ServerUrl`:4318"
Write-Host "`n  Copilot CLI will now emit telemetry automatically in new shells."
Write-Host "  (Restart your terminal for the env vars to take effect.)"
