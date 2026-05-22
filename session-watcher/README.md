# copilot-session-watcher

A small .NET daemon that emits authoritative session-lifecycle telemetry for
**GitHub Copilot CLI** and **Claude Code**. Fills the gap that the tools'
native OTel doesn't cover: did a session open, is it still alive, did it crash.

This is the **Phase A pidfile-only build** described in
`../docs/plan-session-watcher.md` (see the scope addendum at the top of that
file). It watches pidfiles/lock files only; **it does NOT tail JSONL
transcripts and does NOT install or rely on hooks**. Everything else
(prompts, turns, tool calls, tokens) continues to come from the tools'
native OTel.

## What it watches

| Tool         | File                                                          | Signal                                                                         |
|--------------|---------------------------------------------------------------|--------------------------------------------------------------------------------|
| Claude Code  | `%USERPROFILE%\.claude\sessions\<pid>.json`                   | Rich JSON pidfile: `pid`, `sessionId`, `cwd`, `version`, `status`, `updatedAt`. Removed cleanly on graceful exit. |
| Copilot CLI  | `%USERPROFILE%\.copilot\session-state\<sid>\inuse.<pid>.lock` | Empty lock file. PID encoded in filename. Removed cleanly on graceful exit.    |

## What it emits

All via the standard `OTEL_EXPORTER_OTLP_*` env vars — typically into the local
collector that `azure-deploy/client/setup-machine.ps1` already configures.
`service.name` is forced to `copilot-session-watcher` so emissions are
distinguishable from `claude-code` / `github-copilot`.

| Signal  | Name                                  | Purpose                                                                   |
|---------|---------------------------------------|---------------------------------------------------------------------------|
| Log     | `state_transition`                    | One per state change per epoch: opening → live, live → orphan, → ended.   |
| Log     | `heartbeat`                           | Per live/orphan epoch, once per poll tick (30 s).                         |
| Metric  | `copilot.sessions{tool,state,host}`   | Gauge: count of sessions in each state on this host.                      |
| Metric  | `copilot.session.ended{tool,host,shutdown_type}` | Counter: epochs ended, by `graceful` / `crash`.                |
| Metric  | `copilot.session.watcher.up{host}`    | Gauge: 1 while the watcher is healthy.                                    |
| Span    | `session_watcher.lifecycle`           | One per lifecycle epoch. Closed on `Ended` with `shutdown.type` attribute. |

## Build + run

```powershell
cd session-watcher
dotnet build
dotnet run --project src/SessionWatcher
```

The daemon respects these env-var overrides (mostly for tests/dev):

| Variable                              | Default                                       |
|---------------------------------------|-----------------------------------------------|
| `CLAUDE_SESSIONS_DIR`                 | `%USERPROFILE%\.claude\sessions`              |
| `COPILOT_SESSION_STATE_DIR`           | `%USERPROFILE%\.copilot\session-state`        |
| `COPILOT_SESSION_WATCHER_STATE_DIR`   | `%LOCALAPPDATA%\CopilotOtel\session-watcher\` |

OTLP destination + auth come from the standard `OTEL_EXPORTER_OTLP_*` env vars.

## Tests

```powershell
dotnet test
```

43 tests covering pidfile parsing, lock parsing, the state classifier, both
source orchestrators, the singleton lock, and the OS process probe.

## What's NOT in this build

- **Autostart.** No Task Scheduler / LaunchAgent / systemd-user installer yet.
  Plan calls for these in Phase C.
- **active/idle classification for Claude.** The Claude pidfile's `status`
  field is carried through to log records as `claude.status` but isn't
  promoted to a discrete state yet.
- **Image-name PID-reuse defense.** The classifier consumes a boolean
  `PidAlive`; today's `OsProcessProbe` only checks existence + `HasExited`.
  Adding image-name validation is a small extension when needed.
- **Orphan-timeout transitions** (5-minute orphan → `orphan_timeout` counter).
- **Source dispatch beyond Copilot + Claude.** No third source.
