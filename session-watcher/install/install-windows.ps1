<#
.SYNOPSIS
    Builds, installs, and registers the copilot-session-watcher daemon as a
    per-user Task Scheduler entry that auto-starts at logon.

.DESCRIPTION
    Idempotent: safe to re-run for upgrades. Drops the self-contained single-file
    exe into %LOCALAPPDATA%\CopilotOtel\session-watcher\bin\ and creates / replaces
    the Task Scheduler task "CopilotSessionWatcher".

    No admin/elevation required (uses the current user's task store).

.EXAMPLE
    .\install-windows.ps1
    .\install-windows.ps1 -NoStart    # install but don't launch immediately
#>

[CmdletBinding()]
param(
    [switch]$NoStart,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$TaskName  = "CopilotSessionWatcher"
$RepoRoot  = Resolve-Path "$PSScriptRoot\.."  # session-watcher/
$Project   = Join-Path $RepoRoot "src\SessionWatcher\SessionWatcher.csproj"
$PublishOut = Join-Path $RepoRoot "publish\win-x64"
$InstallDir = Join-Path $env:LOCALAPPDATA "CopilotOtel\session-watcher"
$BinDir     = Join-Path $InstallDir "bin"
$LogDir     = Join-Path $InstallDir "logs"
$ExeName    = "copilot-session-watcher.exe"
$TargetExe  = Join-Path $BinDir $ExeName

Write-Host "=== copilot-session-watcher installer ===" -ForegroundColor Cyan
Write-Host "  Repo root  : $RepoRoot"
Write-Host "  Install at : $InstallDir"
Write-Host "  Target exe : $TargetExe"
Write-Host ""

# --- 1. Build (unless skipped) ---
if (-not $SkipBuild) {
    Write-Host "=== Publishing self-contained single-file exe (win-x64) ===" -ForegroundColor Cyan
    dotnet publish $Project -c Release -r win-x64 --self-contained `
        -p:PublishSingleFile=true -p:PublishTrimmed=false `
        -o $PublishOut | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed" }
}

$publishedExe = Join-Path $PublishOut $ExeName
if (-not (Test-Path $publishedExe)) {
    throw "Published exe not found at $publishedExe (rerun without -SkipBuild?)"
}

# --- 2. Install ---
New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# Stop the task if it's already running so we can replace the file.
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Stopping existing scheduled task '$TaskName'..." -ForegroundColor Yellow
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch { }
    # Give any running copies a moment to release the exe file lock.
    Start-Sleep -Seconds 2
}

# Also kill any stray running copies (singleton lock should mean at most one).
Get-Process -Name "copilot-session-watcher" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Stopping running daemon PID $($_.Id)..." -ForegroundColor Yellow
    try { Stop-Process -Id $_.Id -Force -ErrorAction Stop } catch { }
}
Start-Sleep -Milliseconds 500

Copy-Item -Path $publishedExe -Destination $TargetExe -Force

# Copy the .pdb too (small) so stack traces are readable.
$publishedPdb = [System.IO.Path]::ChangeExtension($publishedExe, ".pdb")
if (Test-Path $publishedPdb) {
    Copy-Item -Path $publishedPdb -Destination (Join-Path $BinDir ([System.IO.Path]::GetFileName($publishedPdb))) -Force
}

Write-Host "  Installed exe : $TargetExe ($([math]::Round((Get-Item $TargetExe).Length / 1MB, 1)) MB)"

# --- 3. Register Task Scheduler entry ---
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Wrap the daemon launch in cmd.exe so we can redirect stdout/stderr to a log
# file. The OTel pipeline ships everything to Loki when the local collector is
# up, but the file is a backstop for diagnosing daemon startup issues.
$logFile = Join-Path $LogDir "watcher.log"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"`"$TargetExe`" > `"$logFile`" 2>&1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartOnIdle `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "copilot-session-watcher: per-user session lifecycle telemetry for Copilot CLI and Claude Code." `
    | Out-Null

Write-Host "  Registered task '$TaskName' (trigger=AtLogOn, log=$logFile)"

# --- 4. Start now (unless suppressed) ---
if (-not $NoStart) {
    Write-Host "=== Starting daemon ===" -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
    $proc = Get-Process -Name "copilot-session-watcher" -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "  Running. PID=$($proc.Id), started=$($proc.StartTime)" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: daemon process not visible after 3s. Check $logFile." -ForegroundColor Yellow
    }
} else {
    Write-Host "  -NoStart specified; not launching now. Task will start at next logon."
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "  Diagnostics : $logFile"
Write-Host "  To stop     : Stop-ScheduledTask -TaskName $TaskName"
Write-Host "  To remove   : Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
Write-Host ""
