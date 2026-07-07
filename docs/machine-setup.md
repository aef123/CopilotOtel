# Machine setup & updates

Point any machine at this doc to get it into the **correct state** for emitting
Claude Code **and** GitHub Copilot CLI telemetry at the same time.

- **First-time setup** — a machine that has never been configured. Start at
  [First-time setup](#first-time-setup).
- **Update** — a machine that was set up before and just needs to be brought
  current. Skip to [Updating an existing machine](#updating-an-existing-machine).

Both paths converge on the same two scripts and the same
[verification](#verify-its-correct).

A machine is "correct" when all three are true:

1. **Persistent env vars** are set for both tools — and `OTEL_SERVICE_NAME` is
   **not** set anywhere.
2. **Local OTel collector** (Docker) is running and forwarding to Azure, with the
   **`CopilotOtelCollectorEnsure`** logon task registered to re-bind its ports
   after restarts.
3. **session-watcher daemon** is running the latest build.

Both tools run concurrently because nothing forces a shared service identity:
Claude Code defaults its `service.name` to `claude-code`, Copilot CLI to
`github-copilot`. The one variable that would break that is `OTEL_SERVICE_NAME` —
so it must stay unset at every scope. The single daemon watches both tools and
tags each session with its own `tool=` label, so simultaneous sessions never
collide.

---

## Prerequisites

The same list applies to both paths (an updated machine already has these):

- Windows + PowerShell 7+
- Docker Desktop running
- **.NET 9 SDK** (needed to build the watcher) — check with `dotnet --list-sdks`
- This repo cloned locally
- The OTel ingest **client secret** — Azure Portal → Entra ID → App registrations →
  *OTel Ingest* → Certificates & secrets → Client secrets. One secret works for
  every machine; auth is shared (client-credentials), not per-machine.

The server stack and Entra apps are already deployed (`otel.andrewfaust.com`), and
the tenant/client/server defaults are baked into `setup-machine.ps1` — so a new
machine only needs the secret above. (If you're standing up the *server* stack
from scratch, see [`../azure-deploy/README.md`](../azure-deploy/README.md) first.)

---

## First-time setup

Run from a PowerShell 7 terminal.

### 1. Clone the repo (if you haven't)

```powershell
git clone <this-repo-url> C:\git\OtelCliCapture
cd C:\git\OtelCliCapture
```

### 2. Configure env vars + local collector

Sets every persistent user env var for both tools, writes the collector `.env`,
starts the local collector that forwards to Azure, and registers the
`CopilotOtelCollectorEnsure` logon task that re-binds the collector's ports after
a Docker/host restart (see [Troubleshooting](#troubleshooting)). It prompts for
the client secret (or pass `-ClientSecret "..."`).

```powershell
.\azure-deploy\client\setup-machine.ps1
```

**On a Cloud PC / VM** whose hostname is random (`CPC-...`), pass a friendly name
so the dashboard is readable (it's preserved on later re-runs):

```powershell
.\azure-deploy\client\setup-machine.ps1 -MachineName "afaust-laptop2"
```

### 3. Install the watcher daemon

Builds the single-file exe into `%LOCALAPPDATA%\CopilotOtel\session-watcher\bin\`
and registers the `CopilotSessionWatcher` logon task.

```powershell
.\session-watcher\install\install-windows.ps1
```

### 4. Restart your terminal

Persistent env vars only apply to **new** shells. Then jump to
[Verify](#verify-its-correct).

---

## Updating an existing machine

Run from the repo root in a PowerShell 7 terminal.

### 1. Get the latest code

```powershell
git pull
```

### 2. Refresh env vars + local collector

Re-runs the same script. It re-sets every persistent env var (including the
Copilot ones), restarts the collector, re-registers the
`CopilotOtelCollectorEnsure` self-heal task, and deliberately does **not** set
`OTEL_SERVICE_NAME`.

```powershell
.\azure-deploy\client\setup-machine.ps1
# Cloud PC / VM: pass -MachineName to keep a friendly host name
```

### 3. Rebuild + reinstall the watcher daemon

Idempotent: stops the running daemon, rebuilds, replaces the exe, and re-registers
the task.

```powershell
.\session-watcher\install\install-windows.ps1
```

### 4. Restart your terminal

New env vars only apply to new shells. Then [verify](#verify-its-correct).

---

## Verify it's correct

Paste this into PowerShell 7. All three checks should pass on either path.

```powershell
# 1. OTEL_SERVICE_NAME must be empty at every scope
'User','Machine','Process' | ForEach-Object {
    $v = if ($_ -eq 'Process') { $env:OTEL_SERVICE_NAME }
         else { [Environment]::GetEnvironmentVariable('OTEL_SERVICE_NAME', $_) }
    "OTEL_SERVICE_NAME ($_) = '$v'"
}

# 2. Local collector is up
docker ps --format "{{.Names}}`t{{.Status}}" | Select-String "otel-collector"

# 3. Watcher is running the new build (heartbeats carry last_activity_at=)
Get-Process copilot-session-watcher -ErrorAction SilentlyContinue |
    Select-Object Id, StartTime
Get-Content "$env:LOCALAPPDATA\CopilotOtel\session-watcher\logs\watcher.log" -Tail 6

# 4. Collector is actually reachable on the host, and the self-heal task exists
Test-NetConnection 127.0.0.1 -Port 4318 -InformationLevel Quiet   # must be True
Get-ScheduledTask -TaskName CopilotOtelCollectorEnsure | Select-Object TaskName, State
```

Expected:

- All three `OTEL_SERVICE_NAME` lines show `''` (empty).
- The collector container shows `Up ...`.
- The watcher process is listed, and heartbeat lines look like
  `heartbeat claude/<id> state=Active last_activity_at=2026-...` — the
  `last_activity_at=` suffix proves the **new** build is live. (The old build
  omitted it.)
- `Test-NetConnection ... -Port 4318` returns `True`, and the
  `CopilotOtelCollectorEnsure` task is `Ready`.

**End-to-end check:** run `claude` in one terminal and `copilot` in another, then
open the dashboard. You should see the same `host.name` with two distinct sources —
`claude-code` and `github-copilot` — reporting at once.

---

## Per-shell alternative (no persistent changes)

To configure a single shell ad hoc (e.g. point at a different endpoint) without
touching persistent env vars, dot-source the helper. It configures **both** tools
and does not set `OTEL_SERVICE_NAME`, so it's safe whether you launch `claude` or
`copilot` in that shell:

```powershell
. .\Set-OtelEnv.ps1                                  # defaults to 127.0.0.1:4318
. .\Set-OtelEnv.ps1 -Endpoint "http://myhost:4318"
. .\Set-OtelEnv.ps1 -MachineName "afaust-laptop2"
```

---

## Troubleshooting

- **Both tools show up as the same source on the dashboard** → `OTEL_SERVICE_NAME`
  got set somewhere. Clear it:
  `[Environment]::SetEnvironmentVariable('OTEL_SERVICE_NAME', $null, 'User')`
  (repeat for `'Machine'`), then restart the terminal.
- **Watcher heartbeats have no `last_activity_at=`** → you're running an old build.
  Re-run `install-windows.ps1`.
- **`dotnet publish failed`** → .NET 9 SDK missing. Install it, confirm with
  `dotnet --list-sdks`, re-run.
- **No telemetry reaching Azure** → confirm the collector container is `Up` and the
  `.env` next to `azure-deploy\client\docker-compose.yaml` has a current client
  secret. Auth details are in [`../azure-deploy/README.md`](../azure-deploy/README.md).
- **Collector is `Up` but nothing reaches the dashboard after a restart** → the
  Docker Desktop for Windows port-proxy race (docker/for-win#3176, #1018): the
  container came up before the Windows HNS proxy, so `4318` is declared but not
  bound. Tell: `docker inspect client-otel-collector-1 --format '{{json .NetworkSettings.Ports}}'`
  shows empty arrays and `Test-NetConnection 127.0.0.1 -Port 4318` is `False`.
  Heal it immediately with `.\azure-deploy\client\ensure-collector.ps1`, or
  `docker compose -f azure-deploy\client\docker-compose.yaml up -d --force-recreate`.
  The `CopilotOtelCollectorEnsure` logon task does this automatically at each
  logon; re-register it with `.\azure-deploy\client\install-collector-task.ps1`.
- **Cloud PC shows a random `CPC-...` host** → re-run `setup-machine.ps1` with
  `-MachineName`.
</content>
