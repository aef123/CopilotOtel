<#
.SYNOPSIS
    Sets up a machine to forward Copilot CLI and Claude Code telemetry to the Azure OTel stack.

.DESCRIPTION
    Uses the oauth2client extension in the OTel collector to handle token
    acquisition and refresh automatically via client_credentials flow.
    No certificates, token files, or scheduled tasks needed.

    This script:
    1. Prompts for the client secret (if not provided)
    2. Starts a local OTel collector (Docker) that forwards to Azure with auth
    3. Sets persistent user environment variables for Copilot CLI and Claude Code

.EXAMPLE
    .\setup-machine.ps1
    .\setup-machine.ps1 -ClientSecret "your-secret-here"
#>

param(
    [string]$TenantId = "5df6d88f-0d78-491b-9617-8b43a209ba73",
    [string]$ClientId = "1fcf6578-502c-4a18-a8e0-ac55f1ed133a",
    [string]$ServerUrl = "https://otel.andrewfaust.com",
    [string]$ClientSecret,
    [string]$ScriptDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

# ──────────────────────────────────────────────
# Step 1: Get client secret
# ──────────────────────────────────────────────
if (-not $ClientSecret) {
    Write-Host "`n=== Client secret required ===" -ForegroundColor Cyan
    Write-Host "  Get the secret from Azure Portal:"
    Write-Host "  Entra ID > App registrations > OTel Ingest ($ClientId)"
    Write-Host "  > Certificates & secrets > Client secrets"
    $secureSecret = Read-Host -Prompt "  Enter client secret" -AsSecureString
    $ClientSecret = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)
    )
}

if (-not $ClientSecret) {
    throw "Client secret is required."
}

# ──────────────────────────────────────────────
# Step 2: Remove old scheduled task (if exists)
# ──────────────────────────────────────────────
$oldTask = Get-ScheduledTask -TaskName "CopilotOTelTokenRefresh" -ErrorAction SilentlyContinue
if ($oldTask) {
    Write-Host "`n=== Removing old token refresh task ===" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName "CopilotOTelTokenRefresh" -Confirm:$false
    Write-Host "  Removed scheduled task 'CopilotOTelTokenRefresh' (no longer needed)."
}

# ──────────────────────────────────────────────
# Step 3: Start local OTel collector
# ──────────────────────────────────────────────
Write-Host "`n=== Starting local OTel collector ===" -ForegroundColor Cyan

$envContent = @"
SERVER_URL=$ServerUrl
ENTRA_TENANT_ID=$TenantId
ENTRA_CLIENT_ID=$ClientId
ENTRA_CLIENT_SECRET=$ClientSecret
"@
[System.IO.File]::WriteAllText((Join-Path $ScriptDir ".env"), $envContent)

$collectorCompose = Join-Path $ScriptDir "docker-compose.yaml"
docker compose -f $collectorCompose up -d

# ──────────────────────────────────────────────
# Step 4: Set persistent environment variables
# ──────────────────────────────────────────────
Write-Host "`n=== Setting environment variables ===" -ForegroundColor Cyan

# Shared OTel variables (used by both Copilot CLI and Claude Code)
[Environment]::SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318", "User")
[Environment]::SetEnvironmentVariable("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf", "User")
[Environment]::SetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES", "host.name=$env:COMPUTERNAME", "User")

# Claude Code specific
[Environment]::SetEnvironmentVariable("CLAUDE_CODE_ENABLE_TELEMETRY", "1", "User")
[Environment]::SetEnvironmentVariable("OTEL_METRICS_EXPORTER", "otlp", "User")
[Environment]::SetEnvironmentVariable("OTEL_LOGS_EXPORTER", "otlp", "User")

# Traces (a.k.a. distributed tracing / spans). Off by default in Claude Code.
# Per Anthropic's docs at https://code.claude.com/docs/en/monitoring-usage#traces-beta,
# tracing requires BOTH the beta flag AND a traces exporter. Without these,
# OTEL_LOG_TOOL_CONTENT is also a no-op (it's gated on tracing).
[Environment]::SetEnvironmentVariable("CLAUDE_CODE_ENHANCED_TELEMETRY_BETA", "1", "User")
[Environment]::SetEnvironmentVariable("OTEL_TRACES_EXPORTER", "otlp", "User")

# Capture prompt + tool detail content. Without these, the span attribute
# `user_prompt` arrives as the literal string "<REDACTED>" and `tool_input`
# values come through as length-only. These are the same flags Set-OtelEnv.ps1
# sets per-shell; persisting at User scope so Task Scheduler-launched and
# default-launched Claude/Copilot sessions both get them.
[Environment]::SetEnvironmentVariable("OTEL_LOG_USER_PROMPTS", "1", "User")
[Environment]::SetEnvironmentVariable("OTEL_LOG_TOOL_DETAILS", "1", "User")

# Force CUMULATIVE temporality for sums/counters. Prometheus remote-write only
# accepts cumulative; the OTel JS SDK (used by Claude Code) defaults to delta,
# which is silently dropped by the prometheusremotewrite exporter. Setting this
# at the user level so new Claude/Copilot sessions emit cumulative directly.
[Environment]::SetEnvironmentVariable("OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE", "cumulative", "User")

# Also set in current session
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://127.0.0.1:4318"
$env:OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"
$env:OTEL_RESOURCE_ATTRIBUTES = "host.name=$env:COMPUTERNAME"
$env:CLAUDE_CODE_ENABLE_TELEMETRY = "1"
$env:CLAUDE_CODE_ENHANCED_TELEMETRY_BETA = "1"
$env:OTEL_METRICS_EXPORTER = "otlp"
$env:OTEL_LOGS_EXPORTER = "otlp"
$env:OTEL_TRACES_EXPORTER = "otlp"
$env:OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE = "cumulative"

Write-Host "  OTEL_EXPORTER_OTLP_ENDPOINT                       = http://127.0.0.1:4318"
Write-Host "  OTEL_EXPORTER_OTLP_PROTOCOL                       = http/protobuf"
Write-Host "  OTEL_RESOURCE_ATTRIBUTES                          = host.name=$env:COMPUTERNAME"
Write-Host "  CLAUDE_CODE_ENABLE_TELEMETRY                      = 1"
Write-Host "  CLAUDE_CODE_ENHANCED_TELEMETRY_BETA               = 1   (enables traces)"
Write-Host "  OTEL_METRICS_EXPORTER                             = otlp"
Write-Host "  OTEL_LOGS_EXPORTER                                = otlp"
Write-Host "  OTEL_TRACES_EXPORTER                              = otlp"
Write-Host "  OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE = cumulative"
Write-Host "  (Set as persistent User environment variables)"

# ──────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────
Write-Host "`n=== Setup complete ===" -ForegroundColor Green
Write-Host "  Auth:         oauth2client (automatic token refresh)"
Write-Host "  Collector:    localhost:4317 (gRPC), localhost:4318 (HTTP)"
Write-Host "  Forwarding:   $ServerUrl`:4318"
Write-Host "`n  Copilot CLI and Claude Code will emit telemetry automatically in new shells."
Write-Host "  (Restart your terminal for the env vars to take effect.)"
