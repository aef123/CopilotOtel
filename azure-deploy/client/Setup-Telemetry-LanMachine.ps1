<#
.SYNOPSIS
    ONE-STOP setup for a machine ON THE HOME LAN (the desktop / gaming PC).

.DESCRIPTION
    Run this and you're done. It:
      1. Updates this repo
      2. Asks for the one credential it needs, telling you exactly where to get it
      3. Points Claude Code + Copilot CLI telemetry at the homelab (ingress.afart.info)
      4. ALSO enables the Bitburner feed to the homelab collector (LAN-only)
      5. Installs the restart-resilience task
      6. Verifies it actually works and tells you if it didn't

    Use Setup-Telemetry-RemoteMachine.ps1 instead on a laptop / work machine / Cloud PC
    that is NOT on the home LAN.

.EXAMPLE
    pwsh -NoProfile -File .\Setup-Telemetry-LanMachine.ps1
#>

param(
    # The homelab OTel collector on the LAN. Bitburner telemetry goes here directly.
    [string]$HomelabUrl = "http://192.168.30.10:4318",
    # Friendly name shown in the dashboards. Defaults to this PC's name.
    [string]$MachineName,
    # Paste the secret non-interactively instead of being prompted.
    [string]$ClientSecret,
    # Skip the git pull (e.g. offline).
    [switch]$SkipUpdate
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir "..\..")

function Say    ($m) { Write-Host $m }
function Head   ($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Good   ($m) { Write-Host "  OK  $m" -ForegroundColor Green }
function Warn   ($m) { Write-Host "  !   $m" -ForegroundColor Yellow }
function Fail   ($m) { Write-Host "  X   $m" -ForegroundColor Red }

Head "Telemetry setup - LAN machine (on the home network)"
Say  "  Sends Claude Code + Copilot CLI telemetry to:  https://ingress.afart.info"
Say  "  Sends Bitburner telemetry to:                  $HomelabUrl"
Say  "  Dashboards will be at:                         https://grafana.afart.info"

# ── 1. Prerequisites ────────────────────────────────────────────────────────────
Head "Checking prerequisites"

if ($PSVersionTable.PSVersion.Major -lt 7) {
    Fail "This is Windows PowerShell $($PSVersionTable.PSVersion). Re-run with PowerShell 7:"
    Say  "      pwsh -NoProfile -File `"$PSCommandPath`""
    throw "PowerShell 7 required."
}
Good "PowerShell $($PSVersionTable.PSVersion)"

try { docker info 2>&1 | Out-Null; if ($LASTEXITCODE -ne 0) { throw } }
catch { Fail "Docker isn't running. Start Docker Desktop, wait for it to settle, re-run."; throw "Docker not available." }
Good "Docker is running"

# ── 2. Update the repo ──────────────────────────────────────────────────────────
if (-not $SkipUpdate) {
    Head "Updating this repo"
    Push-Location $RepoRoot
    try {
        $before = (git rev-parse HEAD).Trim()
        git pull --ff-only 2>&1 | ForEach-Object { Say "  $_" }
        $after = (git rev-parse HEAD).Trim()
        if ($before -ne $after) {
            $changed = git diff --name-only $before $after
            if ($changed -match 'Setup-Telemetry-LanMachine\.ps1') {
                Warn "This script itself was updated. Re-run it to use the new version:"
                Say  "      pwsh -NoProfile -File `"$PSCommandPath`""
                return
            }
            Good "Updated to $after"
        } else { Good "Already current" }
    } finally { Pop-Location }
}

# ── 3. The one credential ───────────────────────────────────────────────────────
if (-not $ClientSecret) {
    Head "Credential needed - OTel Ingest client secret"
    Say  "  Get it here:"
    Say  "    1. portal.azure.com  ->  Microsoft Entra ID  ->  App registrations"
    Say  "    2. Open:  OTel Ingest      (client id 1fcf6578-502c-4a18-a8e0-ac55f1ed133a)"
    Say  "    3. Left menu:  Certificates & secrets  ->  tab 'Client secrets'"
    Say  "    4. Copy the VALUE column (a ~40 character string)."
    Say  "       NOT the 'Secret ID' column - that's a GUID with dashes and will be rejected."
    Say  "    5. If none is listed or it's expired: 'New client secret', then copy the Value"
    Say  "       immediately - Azure only shows it once."
    Say  ""
    $sec = Read-Host -Prompt "  Paste the secret VALUE" -AsSecureString
    $ClientSecret = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
if (-not $ClientSecret) { throw "No secret provided." }

if ($ClientSecret -match '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') {
    Fail "That looks like a GUID, so it's the Secret ID, not the Value."
    Say  "      The Value is ~40 characters with no dashes. Copy the 'Value' column."
    throw "Wrong field pasted."
}
Good "Secret captured ($($ClientSecret.Length) characters)"

if (-not $MachineName) { $MachineName = $env:COMPUTERNAME }
Good "This machine will appear as: $MachineName"

# ── 4. Configure + start ────────────────────────────────────────────────────────
Head "Configuring the local collector"
& (Join-Path $ScriptDir "setup-machine.ps1") `
    -ClientSecret $ClientSecret `
    -HomelabUrl   $HomelabUrl `
    -MachineName  $MachineName

# ── 5. Restart resilience ───────────────────────────────────────────────────────
Head "Installing restart-resilience task"
Say  "  (Docker Desktop can bring the collector up with its ports unbound after a reboot;"
Say  "   this task detects that and fixes it, so telemetry doesn't silently stop.)"
try {
    & (Join-Path $ScriptDir "install-collector-task.ps1") -ScriptDir $ScriptDir
    Good "Self-heal task registered"
} catch {
    Warn "Could not register the task: $_"
    Warn "Telemetry works now, but won't self-heal after a reboot."
}

# ── 6. Verify ───────────────────────────────────────────────────────────────────
Head "Verifying"
$problems = @()

$state = (docker inspect OtelCollector --format '{{.State.Status}}' 2>$null)
if ($state -eq 'running') { Good "Collector container is running" }
else { Fail "Collector is '$state'"; $problems += "container not running" }

Start-Sleep -Seconds 5
$listening = Test-NetConnection -ComputerName 127.0.0.1 -Port 4318 -InformationLevel Quiet -WarningAction SilentlyContinue
if ($listening) { Good "Collector is listening on 127.0.0.1:4318" }
else { Fail "Nothing listening on 127.0.0.1:4318 (Docker port-binding race)"; $problems += "port 4318 unbound" }

$ports = (docker port OtelCollector 2>$null) -join ' '
if ($ports -match '4319') { Good "Bitburner receiver active on :4319 (homelab feed enabled)" }
else { Warn "No :4319 - Bitburner feed is NOT enabled"; $problems += "bitburner overlay missing" }

try {
    $r = Invoke-WebRequest -Uri "https://ingress.afart.info/v1/metrics" -Method POST `
            -Body '{"resourceMetrics":[]}' -ContentType 'application/json' `
            -SkipHttpErrorCheck -TimeoutSec 25
    if ($r.StatusCode -eq 401) { Good "Homelab ingest reachable and requiring auth (401 as expected)" }
    else { Warn "Ingest returned HTTP $($r.StatusCode) unauthenticated (expected 401)"; $problems += "ingest returned $($r.StatusCode)" }
} catch { Fail "Could not reach https://ingress.afart.info - $($_.Exception.Message)"; $problems += "ingest unreachable" }

Start-Sleep -Seconds 10
$authErrors = docker logs OtelCollector --since 2m 2>&1 | Select-String -Pattern '401|403|invalid_client|unauthorized'
if ($authErrors) {
    Fail "The collector is being rejected upstream - the secret is probably wrong or expired:"
    $authErrors | Select-Object -First 3 | ForEach-Object { Say "      $_" }
    $problems += "upstream auth rejected"
} else { Good "No upstream auth errors" }

# ── Done ────────────────────────────────────────────────────────────────────────
if ($problems.Count -eq 0) {
    Head "Done - everything checks out"
    Say  "  Dashboards:   https://grafana.afart.info"
    Say  "  Sessions:     https://grafana.afart.info/dashboard/"
    Say  ""
    Say  "  Open a NEW terminal and run 'claude' or 'copilot'. Data appears within ~1 minute."
} else {
    Head "Finished WITH PROBLEMS"
    $problems | ForEach-Object { Fail $_ }
    Say  ""
    Say  "  Paste this output to Claude and it can pick it up from here."
}
