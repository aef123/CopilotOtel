# Session-watcher daemon — deployed and verified — 2026-05-22

Follow-up to `status-2026-05-21-otel-pipeline.md`. Phase A of the daemon
plan is now built, installed on the dev workstation as a Task Scheduler
entry, and verified end-to-end with live data in Loki + Prometheus.

## What was done

1. **Published** the daemon as a self-contained single-file Windows exe
   (`copilot-session-watcher.exe`, ~69 MB; .NET 9, win-x64, no runtime
   prerequisite). Output goes to `session-watcher/publish/win-x64/`.
2. **Installed** via `session-watcher/install/install-windows.ps1`:
   - Copies the exe to `%LOCALAPPDATA%\CopilotOtel\session-watcher\bin\`.
   - Registers a Task Scheduler task `CopilotSessionWatcher`, trigger
     "At log on of <current user>", action wraps the exe in `cmd /c`
     with stdout/stderr redirected to
     `%LOCALAPPDATA%\CopilotOtel\session-watcher\logs\watcher.log`.
   - Task settings: start when available, allow on batteries, no
     execution time limit.
   - Starts the task immediately and verifies the process appears.
   - Idempotent (safe to re-run for upgrades).
3. **Verified end-to-end emission** to the Azure backends:
   - **Prometheus:** `copilot_session_watcher_up{host="MRDESKTOP"} = 1`,
     `copilot_sessions{state="orphan",tool="copilot",host="MRDESKTOP"} = 7`,
     `copilot_sessions{state="live",tool="claude",host="MRDESKTOP"} = 1`.
   - **Loki:** `service_name=copilot-session-watcher` heartbeat log
     records flowing with attributes `tool_name`, `state_current`,
     `session_id`, `host_name`, `session_epoch`, etc.
   - **Tempo:** 0 traces *(expected)* — `session_watcher.lifecycle`
     spans only export on `End()`, which fires when a session ends.
     Will populate the first time the live Claude session exits.

## Bug found during deployment: IPv6 localhost

The daemon, freshly installed, was emitting nothing. Diagnosis showed
`Get-NetTCPConnection` on the daemon PID listing a TCP connection stuck
in `SynSent` state to `::1:4318` — Windows resolves `localhost` to IPv6
first, and Docker Desktop's IPv6 port mapping accepts the connection
silently but never replies (a known Docker Desktop / WSL2 quirk).

Claude Code's OTel JS SDK happens to retry-fallback to IPv4 silently.
The .NET OpenTelemetry SDK does not — it just blocks on the v6 SYN
forever and silently drops batches.

**Fix:** changed the user-level `OTEL_EXPORTER_OTLP_ENDPOINT` env var
from `http://localhost:4318` to `http://127.0.0.1:4318`, and updated
`azure-deploy/client/setup-machine.ps1` to use `127.0.0.1` for future
installs. After restart, the daemon's TCP connection to the local
collector showed `Established` and data flowed within seconds.

This bug also affects any other native non-Claude OTel emitter on
Windows that resolves localhost. Worth pinning in the readme.

## Files added / changed

| Path                                            | Purpose                                                  |
|-------------------------------------------------|----------------------------------------------------------|
| `session-watcher/install/install-windows.ps1`   | Build + install + Task Scheduler registration            |
| `session-watcher/src/SessionWatcher/SessionWatcher.csproj` | Adds `<AssemblyName>copilot-session-watcher</AssemblyName>` |
| `azure-deploy/client/setup-machine.ps1`         | Endpoint changed `localhost` → `127.0.0.1`               |

## Daemon attributes on Loki records (for dashboard contract)

| Label                  | Value example                          | Notes                                     |
|------------------------|----------------------------------------|-------------------------------------------|
| `service_name`         | `copilot-session-watcher`              | Stream selector for daemon emissions      |
| `tool_name`            | `claude` \| `copilot`                  | Promoted to label by collector            |
| `state_current`        | `live` \| `orphan` \| `ended`          | Bounded enum                              |
| `session_id`           | UUID                                   | Per-session                               |
| `session_epoch`        | `1`                                    | Always 1 for now (single-epoch model)     |
| `host_name`            | `MRDESKTOP`                            | Machine identity                          |
| `service_version`      | `0.1.0`                                | Bumped per daemon release                 |

## Dashboard wiring (next phase, not done in this batch)

`docs/plan-session-watcher.md` has a tile-to-query mapping. Two key
queries with the data we now have:

- **Live sessions on this host** (gauge):
  `sum by (host) (copilot_sessions{state="live"})`  *(plan uses `state=~"active|idle"`; we use `live` for now — see plan addendum)*
- **Orphan sessions** (gauge):
  `sum by (host) (copilot_sessions{state="orphan"})`
- **Per-session live list** (LogQL):
  `{service_name="copilot-session-watcher", state_current!="ended"} | latest_per_session`

`session-api/server.py` doesn't read Loki yet; that work is the next
batch.

## What's NOT in this build (recap)

- Autostart on macOS / Linux (LaunchAgent / systemd-user)
- Image-name PID-reuse defense in `OsProcessProbe`
- Orphan-timeout (5-min) transitions
- Active/idle from Claude's `status` field (currently surfaced as a log
  attribute but not as a discrete state)
- `session-api` extension to surface watcher data in the dashboard

Each is a self-contained follow-up.
