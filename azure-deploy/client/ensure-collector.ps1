<#
.SYNOPSIS
    Ensures the local OTel collector is actually reachable on 127.0.0.1:4318,
    healing the Docker Desktop for Windows "published ports not bound after
    restart" race (docker/for-win#3176, #1018).

.DESCRIPTION
    On a host/Docker restart, a container kept alive by `restart: unless-stopped`
    can come up before the Windows Host Network Service (HNS) port proxy is
    ready, leaving the container "Up" but with its published ports NOT bound to
    localhost. `docker ps` / `docker port` still show the mapping; nothing
    listens on the host. The reliable cure is to recreate the container so the
    port bindings are re-established.

    This script is conservative: it does nothing while the collector is already
    reachable. It only force-recreates when 127.0.0.1:4318 is not listening.

    Intended to run at logon via a Task Scheduler entry (see
    install-collector-task.ps1), but safe to run by hand any time.

.PARAMETER Port
    Host port the collector's OTLP/HTTP receiver should be listening on.

.PARAMETER DockerReadyTimeoutSec
    How long to wait for the Docker engine to become responsive at logon.

.PARAMETER PortGraceSec
    After Docker is ready, how long to let the auto-restarted container bind its
    port on its own before deciding to force-recreate.

.EXAMPLE
    .\ensure-collector.ps1
    .\ensure-collector.ps1 -Verbose
#>
[CmdletBinding()]
param(
    [int]$Port = 4318,
    [int]$DockerReadyTimeoutSec = 300,
    [int]$PortGraceSec = 25,
    [string]$ScriptDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

# --- Logging -----------------------------------------------------------------
$LogDir = Join-Path $env:LOCALAPPDATA "CopilotOtel\collector\logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$LogFile = Join-Path $LogDir "ensure-collector.log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $line = "{0}  {1,-5}  {2}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffK"), $Level, $Message
    Add-Content -Path $LogFile -Value $line
    Write-Verbose $line
}

# Trim the log so it can't grow without bound across many logons.
if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 512KB)) {
    (Get-Content $LogFile -Tail 500) | Set-Content $LogFile
}

# --- Helpers -----------------------------------------------------------------

# Fast, non-blocking TCP probe. Test-NetConnection is slow and chatty; a raw
# TcpClient with an explicit timeout is quicker and quieter for polling.
function Test-PortOpen {
    param([int]$ProbePort, [int]$TimeoutMs = 800)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect("127.0.0.1", $ProbePort, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs) -and $client.Connected) {
            $client.EndConnect($iar)
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-DockerReady {
    try {
        docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

# --- Main --------------------------------------------------------------------
Write-Log "ensure-collector starting (port=$Port, scriptDir=$ScriptDir)"

$compose = Join-Path $ScriptDir "docker-compose.yaml"
if (-not (Test-Path $compose)) {
    Write-Log "docker-compose.yaml not found at $compose; cannot continue." "ERROR"
    exit 1
}

# 1. Wait for the Docker engine to be responsive (it may still be starting at
#    logon). If it never comes up, there's nothing we can do this session.
$deadline = (Get-Date).AddSeconds($DockerReadyTimeoutSec)
while (-not (Test-DockerReady)) {
    if ((Get-Date) -ge $deadline) {
        Write-Log "Docker engine not ready after ${DockerReadyTimeoutSec}s; giving up for now." "ERROR"
        exit 2
    }
    Start-Sleep -Seconds 3
}
Write-Log "Docker engine is ready."

# 2. Give the auto-restarted container a short grace period to bind the port on
#    its own. If it does, the restart policy worked fine this boot and we leave
#    everything untouched.
$graceDeadline = (Get-Date).AddSeconds($PortGraceSec)
while (-not (Test-PortOpen -ProbePort $Port)) {
    if ((Get-Date) -ge $graceDeadline) { break }
    Start-Sleep -Seconds 2
}

if (Test-PortOpen -ProbePort $Port) {
    Write-Log "Collector already reachable on 127.0.0.1:$Port; nothing to do."
    exit 0
}

# 3. Port is not bound. This is the Docker Desktop port-proxy race. Recreate the
#    container from compose so the host port binding is re-established.
Write-Log "127.0.0.1:$Port not listening; force-recreating collector from $compose." "WARN"
docker compose -f $compose up -d --force-recreate 2>&1 | ForEach-Object { Write-Log "docker: $_" }

if ($LASTEXITCODE -ne 0) {
    Write-Log "docker compose up --force-recreate exited with $LASTEXITCODE." "ERROR"
    exit 3
}

# 4. Verify the heal actually took.
$verifyDeadline = (Get-Date).AddSeconds(20)
while (-not (Test-PortOpen -ProbePort $Port)) {
    if ((Get-Date) -ge $verifyDeadline) {
        Write-Log "Recreated container but 127.0.0.1:$Port still not listening after 20s." "ERROR"
        exit 4
    }
    Start-Sleep -Seconds 2
}

Write-Log "Collector healed: 127.0.0.1:$Port is now listening."
exit 0
