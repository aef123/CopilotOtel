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
    [string]$ScriptDir = $PSScriptRoot,
    # Friendly machine name for host.name resource attribute. Cloud PC / VM
    # hostnames are random and meaningless ("CPC-foo-XXXXX"); always pass your
    # own short name. Defaults to whatever's already set on the machine so
    # re-running the script doesn't clobber a name you set previously, falling
    # back to $env:COMPUTERNAME only if nothing has ever been set.
    [string]$MachineName
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
# Step 3b: Register the collector self-heal logon task
# ──────────────────────────────────────────────
# Docker Desktop for Windows has a restart race (docker/for-win#3176, #1018):
# after a host/Docker restart, the `restart: unless-stopped` container can come
# up before the Windows HNS port proxy, leaving it "Up" but with its published
# ports (4317/4318) NOT bound to localhost. The CLIs then export into a void.
# This logon task force-recreates the collector ONLY when 127.0.0.1:4318 isn't
# listening, healing the binding without disturbing a healthy collector. It also
# heals right now if the `up -d` above reused a stale, unbound container.
Write-Host "`n=== Registering collector self-heal task ===" -ForegroundColor Cyan
try {
    & (Join-Path $ScriptDir "install-collector-task.ps1") -ScriptDir $ScriptDir
} catch {
    Write-Host "  WARNING: could not register CopilotOtelCollectorEnsure task: $_" -ForegroundColor Yellow
    Write-Host "  Telemetry still works now; re-run .\install-collector-task.ps1 later to add restart resilience." -ForegroundColor Yellow
}

# ──────────────────────────────────────────────
# Step 4: Set persistent environment variables
# ──────────────────────────────────────────────
Write-Host "`n=== Setting environment variables ===" -ForegroundColor Cyan

# Shared OTel variables (used by both Copilot CLI and Claude Code)
[Environment]::SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318", "User")
[Environment]::SetEnvironmentVariable("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf", "User")

# host.name: prefer explicit -MachineName, else preserve existing User-scope value,
# else fall back to $env:COMPUTERNAME. Cloud PC / VM hostnames are random
# ("CPC-foo-XXXXX") and meaningless; users should pass their own short name.
$existingResAttrs = [Environment]::GetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES", "User")
$existingHost = $null
if ($existingResAttrs -match 'host\.name=([^,]+)') { $existingHost = $matches[1].Trim() }
if ($MachineName) {
    $hostName = $MachineName
} elseif ($existingHost) {
    $hostName = $existingHost
    Write-Host "  Preserving existing host.name=$hostName (pass -MachineName to change)" -ForegroundColor DarkGray
} else {
    $hostName = $env:COMPUTERNAME
    Write-Host "  No host.name set; defaulting to COMPUTERNAME=$hostName (pass -MachineName for a friendlier name)" -ForegroundColor Yellow
}
[Environment]::SetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES", "host.name=$hostName", "User")

# Claude Code: master enable + per-signal exporters
[Environment]::SetEnvironmentVariable("CLAUDE_CODE_ENABLE_TELEMETRY", "1", "User")
[Environment]::SetEnvironmentVariable("OTEL_METRICS_EXPORTER", "otlp", "User")
[Environment]::SetEnvironmentVariable("OTEL_LOGS_EXPORTER", "otlp", "User")

# Claude Code traces (a.k.a. distributed tracing / spans). Off by default.
# Per Anthropic's docs at https://code.claude.com/docs/en/monitoring-usage#traces-beta,
# tracing requires BOTH the beta flag AND a traces exporter. Without these,
# OTEL_LOG_TOOL_CONTENT is also a no-op (it's gated on tracing).
[Environment]::SetEnvironmentVariable("CLAUDE_CODE_ENHANCED_TELEMETRY_BETA", "1", "User")
[Environment]::SetEnvironmentVariable("OTEL_TRACES_EXPORTER", "otlp", "User")

# Capture user-prompt content + tool input/output. Without these, span
# attributes like `user_prompt` arrive as "<REDACTED>" and tool args are
# length-only. OTEL_LOG_USER_PROMPTS / OTEL_LOG_TOOL_DETAILS / OTEL_LOG_TOOL_CONTENT
# are Claude Code; OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT is the
# gen_ai-semconv equivalent that Copilot CLI honors. Set all four so prompts
# land on both tools.
[Environment]::SetEnvironmentVariable("OTEL_LOG_USER_PROMPTS", "1", "User")
[Environment]::SetEnvironmentVariable("OTEL_LOG_TOOL_DETAILS", "1", "User")
[Environment]::SetEnvironmentVariable("OTEL_LOG_TOOL_CONTENT", "1", "User")
[Environment]::SetEnvironmentVariable("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true", "User")

# Copilot CLI: master enable + exporter type. Without COPILOT_OTEL_ENABLED
# the Copilot binary emits nothing regardless of OTEL_* env vars.
[Environment]::SetEnvironmentVariable("COPILOT_OTEL_ENABLED", "true", "User")
[Environment]::SetEnvironmentVariable("COPILOT_OTEL_EXPORTER_TYPE", "otlp-http", "User")

# Per-session label on metrics. The dashboard's compute_sessions groups
# Prometheus series by gen_ai.conversation.id to detect "responding" state.
[Environment]::SetEnvironmentVariable("OTEL_METRICS_INCLUDE_SESSION_ID", "true", "User")

# Force CUMULATIVE temporality for sums/counters. Prometheus remote-write only
# accepts cumulative; the OTel JS SDK (used by Claude Code) defaults to delta,
# which is silently dropped by the prometheusremotewrite exporter. Setting this
# at the user level so new Claude/Copilot sessions emit cumulative directly.
[Environment]::SetEnvironmentVariable("OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE", "cumulative", "User")

# Also set in current session
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://127.0.0.1:4318"
$env:OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"
$env:OTEL_RESOURCE_ATTRIBUTES = "host.name=$hostName"
$env:CLAUDE_CODE_ENABLE_TELEMETRY = "1"
$env:CLAUDE_CODE_ENHANCED_TELEMETRY_BETA = "1"
$env:OTEL_METRICS_EXPORTER = "otlp"
$env:OTEL_LOGS_EXPORTER = "otlp"
$env:OTEL_TRACES_EXPORTER = "otlp"
$env:OTEL_LOG_USER_PROMPTS = "1"
$env:OTEL_LOG_TOOL_DETAILS = "1"
$env:OTEL_LOG_TOOL_CONTENT = "1"
$env:OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT = "true"
$env:COPILOT_OTEL_ENABLED = "true"
$env:COPILOT_OTEL_EXPORTER_TYPE = "otlp-http"
$env:OTEL_METRICS_INCLUDE_SESSION_ID = "true"
$env:OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE = "cumulative"

Write-Host "  OTEL_EXPORTER_OTLP_ENDPOINT                          = http://127.0.0.1:4318"
Write-Host "  OTEL_EXPORTER_OTLP_PROTOCOL                          = http/protobuf"
Write-Host "  OTEL_RESOURCE_ATTRIBUTES                             = host.name=$hostName"
Write-Host "  CLAUDE_CODE_ENABLE_TELEMETRY                         = 1"
Write-Host "  CLAUDE_CODE_ENHANCED_TELEMETRY_BETA                  = 1   (enables Claude traces)"
Write-Host "  OTEL_METRICS_EXPORTER / OTEL_LOGS_EXPORTER / OTEL_TRACES_EXPORTER = otlp"
Write-Host "  OTEL_LOG_USER_PROMPTS / OTEL_LOG_TOOL_DETAILS / OTEL_LOG_TOOL_CONTENT = 1"
Write-Host "  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT   = true  (Copilot prompts)"
Write-Host "  COPILOT_OTEL_ENABLED                                 = true"
Write-Host "  COPILOT_OTEL_EXPORTER_TYPE                           = otlp-http"
Write-Host "  OTEL_METRICS_INCLUDE_SESSION_ID                      = true"
Write-Host "  OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE    = cumulative"
Write-Host "  (Set as persistent User environment variables)"

# ──────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────
Write-Host "`n=== Setup complete ===" -ForegroundColor Green
Write-Host "  Auth:         oauth2client (automatic token refresh)"
Write-Host "  Collector:    localhost:4317 (gRPC), localhost:4318 (HTTP)"
Write-Host "  Self-heal:    CopilotOtelCollectorEnsure logon task (rebinds ports after restarts)"
Write-Host "  Forwarding:   $ServerUrl`:4318"
Write-Host "`n  Copilot CLI and Claude Code will emit telemetry automatically in new shells."
Write-Host "  (Restart your terminal for the env vars to take effect.)"
