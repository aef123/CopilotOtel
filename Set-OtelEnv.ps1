# Set-OtelEnv.ps1
# Configures both Copilot CLI and Claude Code to export full telemetry
# to the OTel collector. Dot-source this before starting either tool.
#
# Usage:
#   . .\Set-OtelEnv.ps1                              # defaults: 127.0.0.1:4318
#   . .\Set-OtelEnv.ps1 -Endpoint "http://myhost:4318"
#   . .\Set-OtelEnv.ps1 -MachineName "afaust-laptop2"  # override host.name

param(
    [string]$Endpoint = "http://127.0.0.1:4318",
    # Friendly machine name for host.name. Cloud PC / VM hostnames are random
    # ("CPC-foo-XXXXX") and meaningless; pass your own short name. Defaults to
    # whatever's already on the User env (set by setup-machine.ps1), then to
    # $env:COMPUTERNAME if nothing has ever been configured.
    [string]$MachineName
)

# ── Shared OTLP endpoint ─────────────────────────────────────────────
$env:OTEL_EXPORTER_OTLP_ENDPOINT = $Endpoint
$env:OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"

# ── host.name ────────────────────────────────────────────────────────
if (-not $MachineName) {
    $existing = [Environment]::GetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES", "User")
    if ($existing -match 'host\.name=([^,]+)') { $MachineName = $matches[1].Trim() }
    elseif (-not $MachineName) { $MachineName = $env:COMPUTERNAME }
}
$env:OTEL_RESOURCE_ATTRIBUTES = "host.name=$MachineName"

# ── Copilot CLI ──────────────────────────────────────────────────────
$env:COPILOT_OTEL_ENABLED       = "true"
$env:COPILOT_OTEL_EXPORTER_TYPE = "otlp-http"
$env:OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT = "true"
# Copilot defaults to service.name = "github-copilot", no override needed

# ── Claude Code ──────────────────────────────────────────────────────
$env:CLAUDE_CODE_ENABLE_TELEMETRY        = "1"
$env:CLAUDE_CODE_ENHANCED_TELEMETRY_BETA = "1"

# Exporters: all signals via OTLP
$env:OTEL_METRICS_EXPORTER = "otlp"
$env:OTEL_LOGS_EXPORTER    = "otlp"
$env:OTEL_TRACES_EXPORTER  = "otlp"
$env:OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"

# Service name: "claude-code" so the dashboard can distinguish from Copilot
$env:OTEL_SERVICE_NAME = "claude-code"

# Privacy: capture prompts, tool details, and tool content
$env:OTEL_LOG_USER_PROMPTS = "1"
$env:OTEL_LOG_TOOL_DETAILS = "1"
$env:OTEL_LOG_TOOL_CONTENT = "1"

# Metrics: include session ID, cumulative temporality for Prometheus
$env:OTEL_METRICS_INCLUDE_SESSION_ID = "true"
$env:OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE = "cumulative"

# Faster export intervals for near-real-time status detection
$env:OTEL_METRIC_EXPORT_INTERVAL = "15000"
$env:OTEL_LOGS_EXPORT_INTERVAL   = "5000"
$env:OTEL_TRACES_EXPORT_INTERVAL = "5000"

# ── Summary ──────────────────────────────────────────────────────────
Write-Host "OTel environment configured for both tools:" -ForegroundColor Green
Write-Host "  Endpoint : $Endpoint"
Write-Host "  Host     : $MachineName"
Write-Host "  Copilot  : github-copilot (service name is built-in)"
Write-Host "  Claude   : claude-code    (via OTEL_SERVICE_NAME)"
Write-Host "  Signals  : metrics, traces, logs"
Write-Host "  Content  : prompts, tool details, tool content"
Write-Host ""
Write-Host "Start either tool normally:  copilot  or  claude" -ForegroundColor Cyan
