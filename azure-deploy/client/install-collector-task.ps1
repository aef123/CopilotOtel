<#
.SYNOPSIS
    Registers a per-user logon task that keeps the local OTel collector's host
    port binding healthy across Docker Desktop / host restarts.

.DESCRIPTION
    Idempotent: safe to re-run. Creates (or replaces) the Task Scheduler entry
    "CopilotOtelCollectorEnsure", which runs ensure-collector.ps1 at logon. That
    script force-recreates the collector container ONLY when 127.0.0.1:4318 is
    not listening, healing the Docker Desktop for Windows port-proxy race
    (docker/for-win#3176, #1018) without disturbing a healthy collector.

    No admin/elevation required (uses the current user's task store), matching
    session-watcher\install\install-windows.ps1.

.EXAMPLE
    .\install-collector-task.ps1
    .\install-collector-task.ps1 -NoRunNow   # register but don't run immediately
#>
[CmdletBinding()]
param(
    [switch]$NoRunNow,
    [string]$ScriptDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

$TaskName    = "CopilotOtelCollectorEnsure"
$EnsureScript = Join-Path $ScriptDir "ensure-collector.ps1"

if (-not (Test-Path $EnsureScript)) {
    throw "ensure-collector.ps1 not found next to this installer at $EnsureScript"
}

# PowerShell 7 is a documented prerequisite (docs/machine-setup.md). Resolve it
# explicitly so the task doesn't accidentally bind to Windows PowerShell 5.
#
# NOTE: deliberately avoids the null-conditional operator `(...)?.Source`. That is PS7-only
# syntax, and a parse error is raised for the WHOLE FILE before any line executes — so when this
# installer was invoked from Windows PowerShell 5.1 it died with
# "Unexpected token '?.Source'" instead of the clear message below. The guard against PS5 could
# not run because PS5 couldn't parse the guard. This form parses on both engines, so the installer
# works whichever shell launches it, as long as pwsh.exe is installed for the task itself.
$pwshCmd = Get-Command pwsh.exe -ErrorAction SilentlyContinue
$pwsh = if ($pwshCmd) { $pwshCmd.Source } else { $null }
if (-not $pwsh) {
    throw "pwsh.exe (PowerShell 7+) not found on PATH. Install it, then re-run."
}

Write-Host "=== CopilotOtelCollectorEnsure installer ===" -ForegroundColor Cyan
Write-Host "  Script : $EnsureScript"
Write-Host "  pwsh   : $pwsh"
Write-Host ""

# Replace any existing registration so upgrades are clean.
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute $pwsh `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$EnsureScript`""

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# ExecutionTimeLimit bounds a stuck run (the script waits up to ~5 min for
# Docker); it self-terminates well within an hour on success.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::FromHours(1))

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Heals the local OTel collector host port binding after Docker/host restarts (docker/for-win#3176)." `
    | Out-Null

Write-Host "  Registered task '$TaskName' (trigger=AtLogOn)" -ForegroundColor Green
$logFile = Join-Path $env:LOCALAPPDATA "CopilotOtel\collector\logs\ensure-collector.log"
Write-Host "  Log    : $logFile"

if (-not $NoRunNow) {
    Write-Host "`n=== Running ensure-collector once now ===" -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
    if (Test-Path $logFile) { Get-Content $logFile -Tail 8 }
} else {
    Write-Host "  -NoRunNow specified; task will first run at next logon."
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "  To run now  : Start-ScheduledTask -TaskName $TaskName"
Write-Host "  To remove   : Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
Write-Host ""
