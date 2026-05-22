# Session Watcher Daemon — Plan

> A non-invasive, file-tail-based companion to the native OTel output of Copilot CLI
> and Claude Code. Fills the gaps in their native telemetry: heartbeats, authoritative
> session lifecycle, and a clean live/active/idle/ended state machine.

## Implementation status (2026-05-22)

Phase A is built in `session-watcher/` under the pidfile-only scope below.
End-to-end smoke test passed: the daemon correctly detected the live Claude
session AND surfaced seven stale Copilot session-state dirs as `Orphan`.
43 unit tests covering pidfile/lock parsing, the state classifier, both
source orchestrators, the singleton lock, and the OS process probe.

Not yet built (see `session-watcher/README.md` "What's NOT in this build"):
autostart installers, image-name PID-reuse defense, orphan-timeout
transitions, and promoting Claude's `status` field to a first-class state.
Each is a self-contained follow-up.

## Scope addendum (2026-05-21)

The original plan below describes a daemon that **both** tails the on-disk
JSONL transcripts AND watches pidfiles/locks. The user has since narrowed
that scope:

- **No hooks.** The daemon does not install or rely on PreToolUse/PostToolUse/
  SessionStart hooks. (The hook artifacts found during Claude transcript
  capture came from unrelated user-global plugins, not from this project.)
- **No JSONL transcript parsing.** The daemon's inputs are limited to
  `%USERPROFILE%\.copilot\session-state\<sid>\inuse.<pid>.lock` (Copilot)
  and `%USERPROFILE%\.claude\sessions\<pid>.json` (Claude). Everything else
  — turn boundaries, tool spans, token counts, prompts, tool results —
  comes via native OTel from Copilot CLI / Claude Code, which is already
  configured in `Set-OtelEnv.ps1` / `setup-machine.ps1`.
- **The daemon's output is OTel only** (logs/metrics/traces emitted via the
  same OTLP endpoint everything else uses).

This collapses the daemon's responsibilities to:

1. Detect session **opened** (pidfile appears).
2. Detect session **ended** (pidfile removed AND PID is dead → graceful;
   PID dead but pidfile still present → crash).
3. Detect **orphan** (pidfile present, PID dead — past graceful grace).
4. Emit **heartbeats** while the pidfile is alive.
5. For Claude only: forward the `status` field (busy/idle) from the
   pidfile as a state attribute.

Active-vs-idle for Copilot is **deliberately dropped** — Copilot's lock
file has no status field. The dashboard already derives active/idle from
Tempo span recency; that stays as-is.

The rest of the plan below still describes the full file-tail design and
is kept as reference (much of the state-machine and lock-authority
analysis still applies). When implementing, follow the addendum scope, not
the full plan.

### Open question to verify before implementation

`Set-OtelEnv.ps1` enables `OTEL_LOG_USER_PROMPTS=1` and
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`. These should
push user-prompt content through the native OTel pipeline (as log records
on Loki for Claude; as span attributes on Tempo for Copilot). Confirm
this is actually landing in Loki/Tempo before scoping out the JSONL tail
permanently — if it's not, the dashboard's prompt display feature would
need to come from somewhere, and "go back and tail JSONL after all" is
the obvious fallback.

---

## Why this exists

The existing CopilotOtel stack relies on **native** OTel emission from Copilot CLI
(`COPILOT_OTEL_ENABLED=true`) and Claude Code (`CLAUDE_CODE_ENABLE_TELEMETRY=1`,
`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`) — configured by `Set-OtelEnv.ps1`. That works
well for **what each tool emits**: model invocations, tool calls, request durations,
token counts.

What it doesn't give us:

1. **Heartbeats.** Each tool only emits spans when something is actively happening.
   Between turns — or when a session is open but the user hasn't typed anything in
   ten minutes — the dashboard goes silent and has no way to distinguish "session
   crashed" from "user is thinking."
2. **Live vs active.** "Is the process running?" and "is work happening right now?"
   are two different questions. Today we approximate the second by querying recent
   spans in Tempo (`test-active-detection.py`), which is brittle and laggy.
3. **Authoritative lifecycle.** Native span emission can drop events under load or
   on crash. We want a separate ground-truth source for "session opened / closed
   cleanly / crashed."

Both Copilot CLI and Claude Code write **on-disk per-session transcripts** that
contain everything we need. We just need a small daemon that tails them and emits
the missing signals as OTel, into the same collector the tools are already pointed
at.

## Source data

### Copilot CLI — confirmed on `cpc-afaus-sqybg`

- Per-session directory: `%USERPROFILE%\.copilot\session-state\<session-id>\`
- Files of interest in each directory:
  - `events.jsonl` — append-only newline-delimited JSON, one row per event. The
    canonical source of truth. Schema observed (130+ sessions sampled):
    - `session.start` — sessionId, copilotVersion, `producer:"agency"` marker,
      startTime
    - `session.resume` — cwd, gitRoot, branch, repository, hostType, baseCommit
    - `session.model_change` — newModel, reasoningEffort
    - `session.shutdown` — shutdownType, totalApiDurationMs, currentModel,
      currentTokens, systemTokens, conversationTokens, toolDefinitionsTokens,
      codeChanges (linesAdded/Removed/filesModified)
    - `session.info`, `session.warning`
    - `user.message` — content, transformedContent, attachments, interactionId
    - `assistant.turn_start` / `assistant.turn_end` — turnId, interactionId
    - `assistant.message` — messageId, **model**, content, toolRequests,
      interactionId, turnId, outputTokens, requestId
    - `tool.execution_start` / `tool.execution_complete`
    - `permission.requested` / `permission.completed`
    - `hook.start` / `hook.end`
    - `abort`
  - `inuse.<pid>.lock` — exists *only* while the Copilot process holds the
    session open. Removed on graceful shutdown. Carries the owning PID.
  - `session.db` — per-session SQLite (todos, agent state). Optional secondary
    input; not required for v1.
  - `workspace.yaml`, `vscode.metadata.json` — workspace context. Already covered
    by `session.resume` event.
- Global: `%USERPROFILE%\.copilot\session-store.db` — a SQLite WAL DB indexing
  all sessions cross-machine. Useful for the API, not needed by the daemon.

### Claude Code — confirmed on a Windows 11 machine running `claude.exe 2.1.147`

Captured 2026-05-21 from a live session; samples committed under
`docs/samples/claude/`. The shape is materially different from Copilot
in three places and the daemon design has to absorb those differences:

- **Per-session transcript:** `%USERPROFILE%\.claude\projects\<sanitized-cwd>\<session-id>.jsonl`
  — append-only JSONL, just as expected. `<sanitized-cwd>` rule
  observed: drive letters become `c--`, path separators become `-`,
  case is preserved (so `c:\git\OtelCliCapture` and `C:\git\OtelCliCapture`
  produce two distinct directories — `c--git-OtelCliCapture` and
  `C--git-OtelCliCapture`). The daemon must canonicalize for de-dup if
  needed but should not assume case-insensitivity.
- **Liveness / "lock":** `%USERPROFILE%\.claude\sessions\<pid>.json` —
  one file per **live** Claude process, removed cleanly on graceful
  exit. The body is a single JSON object:
  ```json
  {"pid":38112,"sessionId":"79ebdd64-...","cwd":"c:\\git\\OtelCliCapture",
   "startedAt":1779427166873,"version":"2.1.147","peerProtocol":1,
   "kind":"interactive","entrypoint":"cli",
   "status":"busy","updatedAt":1779427261873}
  ```
  This is the Claude equivalent of Copilot's `inuse.<pid>.lock` — and
  it is **richer**, carrying `status` (observed: `"busy"`; presumed
  `"idle"` between turns) and the canonical `sessionId` mapping for
  the owning process. **There is NO lock file inside the per-session
  directory** — the per-process pidfile is the only live-session
  signal. The daemon discovers live sessions by enumerating
  `sessions\*.json`, not by scanning `projects\` for lock files.
- **`updatedAt` is event-driven, not a heartbeat.** Confirmed: a 6 s
  observation while the session was actively running tool calls
  produced **no change** to the pidfile. `updatedAt` is rewritten on
  status transitions (busy ↔ idle), not on a wall-clock tick. So the
  daemon cannot use the pidfile mtime as a periodic liveness pulse; it
  must combine `(pidfile exists) ∧ (PID alive)` for `is_live`, and use
  `status` field + transcript events for active/idle classification.

#### Transcript record types

Observed `type` values, with their daemon role:

| `type`                  | Daemon role                                                                                                    |
|-------------------------|----------------------------------------------------------------------------------------------------------------|
| `user`                  | Both human prompts AND tool results. Distinguished by `toolUseResult` presence on the record (non-null = tool result). |
| `assistant`             | One record **per content block** (`thinking` / `text` / `tool_use`). Multiple records share one `message.id`.   |
| `system`                | Turn-boundary markers. `subtype` ∈ {`turn_duration`, `stop_hook_summary`}.                                      |
| `attachment`            | Hook execution outputs. `attachment.hookEvent` ∈ {`SessionStart`, `PreToolUse`, `PostToolUse`, …}.              |
| `ai-title`              | Auto-generated short session title. Useful as a span attribute, not a state signal.                             |
| `last-prompt`           | Sentinel pointer to the latest user prompt's UUID. State, not event. Skip.                                      |
| `permission-mode`       | Current permission-mode sentinel. State, not event. Skip.                                                       |
| `file-history-snapshot` | Snapshot of file backups for Read/Edit safety. Skip.                                                            |

#### Claude → Copilot event mapping (state machine inputs)

| Copilot event                       | Claude equivalent                                                                                          |
|-------------------------------------|------------------------------------------------------------------------------------------------------------|
| `session.start` / `session.resume`  | **No transcript event.** Synthesize from `sessions\<pid>.json` first-seen.                                 |
| `session.shutdown`                  | **No transcript event.** Synthesize from `sessions\<pid>.json` deletion + PID-alive check.                 |
| `assistant.turn_start`              | **No discrete event.** Synthesize: first `assistant` record after a non-tool-result `user` record.         |
| `assistant.turn_end`                | `{"type":"system","subtype":"turn_duration","durationMs":N,"messageCount":N}` — emitted at end of each turn.|
| `assistant.message`                 | `assistant` records with `message.id`. **Dedupe usage by `msg_id`** — same usage block is replayed across each content-block record. |
| `tool.execution_start`              | **No discrete event.** Synthesize from `assistant.content[].type == "tool_use"`; key by `tool_use_id`.     |
| `tool.execution_complete`           | **No discrete event.** Synthesize from `user.message.content[].type == "tool_result"` with matching `tool_use_id`. |
| `hook.start` / `hook.end`           | `attachment` records carrying `hookName`, `hookEvent`, `durationMs`, `exitCode`. One per hook execution.   |
| `permission.requested` / `.completed`| **No first-class transcript event.** Permissions are reflected in `permission-mode` state and in PreToolUse hook denials surfaced via `attachment`. The open-interval permission counter from the Copilot model **does not apply to Claude**; track only `attachment.exitCode != 0` as a denial signal. |
| `abort`                             | Inferred when pidfile disappears with no preceding `system / turn_duration`.                                |

#### Token accounting note

Every `assistant` record carries the **full Anthropic `message.usage`**
(`input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
`cache_read_input_tokens`, plus `server_tool_use`, `service_tier`,
`cache_creation.{ephemeral_5m,ephemeral_1h}_input_tokens`, and a
per-iteration breakdown). The same usage object is duplicated across
every content-block record sharing the same `message.id` — the daemon
MUST dedupe by `msg_id` before aggregating, or it will multiply totals
by 3–5×.

#### Adjacent state directories — out of scope for the daemon

These exist alongside `projects\` and `sessions\` but the daemon does
not consume them:

| Directory                                | Observed contents                            | Why daemon skips it                               |
|------------------------------------------|----------------------------------------------|---------------------------------------------------|
| `%USERPROFILE%\.claude\tasks\<sid>\`     | Numbered `*.json` task records + `.lock`     | Harness TaskCreate state, not session lifecycle.  |
| `%USERPROFILE%\.claude\todos\`           | `<sid>-agent-<sid>.json` (legacy)            | Older todos store; superseded by `tasks\`.        |
| `%USERPROFILE%\.claude\session-env\<sid>\` | Empty in every observed case (live + ended) | No data to capture; future-proof presence only.   |
| `%USERPROFILE%\.claude\history.jsonl`    | Global per-prompt log                        | Redundant with per-session JSONL.                 |
| `%USERPROFILE%\.claude\telemetry\`       | Empty                                        | Reserved; currently unused.                       |
| `projects\<cwd>\memory\`                 | Auto-memory storage                          | Out of daemon scope (content surface, not lifecycle). |

## State model

Each open session is tracked by a state machine. State is emitted as attributes
on every heartbeat record and as discrete state-transition log events.

### Lifecycle epochs

A session ID can have multiple **lifecycle epochs** in one `events.jsonl`.
Observed pattern: `session.start` → ... → `session.shutdown` →
`session.resume` → ... → `session.shutdown`. We model the lifecycle as a
*sequence of epochs* keyed by `(session_id, epoch_index)`, not as a single
state per session_id. `session.shutdown` ends one epoch; the next
`session.start` or `session.resume` after it begins a new one.

### States — current vs transient

States form a small, **mutually exclusive** `current_state` enum that the
gauge tracks at any instant:

| `current_state` | Definition |
|-----------------|------------|
| `active`        | Owning process verified live AND work is in flight (open interval) or recent (≤ 60 s). |
| `idle`          | Owning process verified live, no in-flight work, last event > 60 s ago or was `assistant.turn_end`. |
| `orphan`        | `inuse.<pid>.lock` present but lock authority failed. |

`ended` is **not a state** — it is a *transition*. It appears only as:

- a `state.transition` log event with `state.to="ended"`
- an increment of `copilot_session_ended_total{shutdown_type=...}`
- the closing of the in-memory `session_watcher.lifecycle` span

There is no `live` state. `live` is a *property* (`is_live=true`) of
`active` and `idle`. If you need "all live sessions" on the dashboard,
sum the `active` and `idle` gauges. The `state` label on
`copilot_sessions` never takes the value `live`.

Detection details for each state are below; see "Lock authority" and
"Activity classification" for the predicates that drive the enum.

| Predicate           | Detection                                                                                                                                                          |
|---------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `is_live`           | `inuse.<pid>.lock` present AND lock authority validated.                                                                                                           |
| `has_inflight_work` | At least one unmatched `assistant.turn_start` / `tool.execution_start` / `hook.start` / `permission.requested` event.                                              |
| `recent_event`      | Last event ≤ 60 s ago AND last event is not `assistant.turn_end`.                                                                                                  |
| `lock_invalid`      | Lock file present AND any of: PID gone, PID start time > lock mtime + 5 s, process image not in allowlist, hostname mismatch.                                      |

`active` = `is_live ∧ (has_inflight_work ∨ recent_event)`
`idle`   = `is_live ∧ ¬has_inflight_work ∧ ¬recent_event`
`orphan` = `lock_invalid`

### Lock authority — what counts as "live"

A bare PID check is not enough. The daemon validates the lock owner before
declaring `live`. The lock source differs by tool:

- **Copilot.** `inuse.<pid>.lock` is empty; PID comes from the
  filename. One lock file per session directory.
- **Claude.** `sessions\<pid>.json` is a JSON document; PID comes from
  both the filename and the `pid` field (they must match). One pidfile
  per **Claude process**, not per session — the daemon joins to a
  session via the embedded `sessionId` field.

Validation steps (same for both tools after the PID is resolved):

1. Read the PID from the lock filename. For Claude, also parse the JSON
   body and require `body.pid == filenamePid` and that
   `body.sessionId` is non-empty.
2. Resolve that PID locally. If it doesn't exist, → `orphan`.
3. Compare process start time to lock mtime — `process.start_time ≤
   lock.mtime + 5 s`. Catches PID reuse. The 5 s slack covers filesystem
   timestamp granularity + clock-update races.
4. Confirm the process image name matches an allowlist per platform:
   - Windows: `copilot.exe`, `claude.exe`, `agency.exe` (case-insensitive).
     Confirmed Windows install path observed for Claude:
     `%LOCALAPPDATA%\Microsoft\WinGet\Links\claude.exe`.
   - macOS/Linux: `copilot`, `claude`, `node`. Claude Code on Windows
     ships as a native `claude.exe` (not a Node process); on macOS/Linux
     it may still be a Node launcher — confirm during cross-platform
     packaging in Phase C. Until then, `node` is only accepted if
     `cwd` / command-line includes `claude`.
   No signature, path, or full command-line check in Phase A. Document
   that this is intentionally weak — the threat model is accidental PID
   reuse, not adversarial spoofing on the user's own machine.
5. Confirm hostname/machine-identity. For Copilot, the `session.resume`
   event records the originating host and we cross-check. For Claude,
   the pidfile carries no host field — so cross-host detection falls
   back to checking whether the session directory itself is on a
   synced/network share. If so and the lock came from a foreign PID
   (any PID that doesn't resolve locally), treat as `orphan` from this
   daemon's perspective. The other host's daemon, if any, is
   authoritative.

### Shutdown classification — exact transition rules

When a session leaves its `is_live` predicate, the daemon emits one
`state.transition{state.to="ended"}` log and one
`copilot_session_ended_total{shutdown_type=...}` increment. Exact rules:

| Trigger observed                                                       | `shutdown_type` |
|------------------------------------------------------------------------|-----------------|
| `session.shutdown` event seen for current epoch                        | `graceful`      |
| Valid lock disappears with no `session.shutdown` after a 10 s grace    | `crash`         |
| `orphan` state persisted for ≥ 5 min AND lock still present            | `orphan_timeout` (counter only; the epoch is closed for accounting, the orphan gauge keeps reporting until the lock disappears) |
| Daemon-side 24 h epoch span age cap reached                            | *(not a shutdown — span segments only; see Traces)* |

A 10 s grace window covers the legitimate race where `session.shutdown`
is written ~immediately before the lock is removed. After grace expires,
the epoch is `ended` with `shutdown_type="crash"` even if a late
`session.shutdown` arrives — the late event reconciles the span
attributes but does not retroactively change the counter.

`orphan` is a *current state* that may persist for hours (e.g., stale
locks on synced shares). To prevent unbounded gauge contribution, after
5 min in `orphan` the daemon emits the `orphan_timeout` ended counter
and stops counting that epoch in the orphan gauge. The orphan log
stream continues until the lock disappears, then a final
`watcher.orphan_resolved` log is emitted.

### Activity classification

`active` is computed from an in-flight-work model, not a raw "last event"
timestamp:

- Maintain per-epoch open-interval counters from events.
  - **Copilot:** `assistant.turn_start` → `assistant.turn_end`,
    `tool.execution_start` → `tool.execution_complete`,
    `hook.start` → `hook.end`,
    `permission.requested` → `permission.completed`.
  - **Claude:** synthesized intervals only:
    - "turn open" = `assistant` record observed and no later
      `system / subtype:turn_duration` for the same logical turn.
      (Use `parentUuid` chain to associate.)
    - "tool open" = `assistant` content block `{type:"tool_use", id:"toolu_..."}`
      with no matching later `user` record carrying
      `{type:"tool_result", tool_use_id:"toolu_..."}`.
    - "hook open" = an `attachment` record's `durationMs` is null and
      `exitCode` is null (the hook is mid-execution); closed when a
      later `attachment` with the same `toolUseID` reports a
      `durationMs`. In practice Claude writes the attachment after the
      hook completes, so this counter usually stays at zero.
    - **No permission counter.** Claude has no
      `permission.requested`/`completed` first-class events. Treat
      `attachment.exitCode != 0` on a PreToolUse hook as a one-shot
      denial signal, logged but not part of the open-interval count.
  - Optional cross-check (Claude only): `sessions\<pid>.json.status` flipping
    `busy → idle` is independent corroboration that all open intervals
    closed; if the two disagree (status idle but we still think a tool
    is open), prefer status and log a `watcher.activity_resync` event
    so we can audit later.
- If any open-interval count > 0, the session is **active** regardless of
  event age. (Avoids classifying long tool calls or long LLM responses as
  idle.)
- If all counters are zero AND the last event is `assistant.turn_end`
  (Copilot) or `system / subtype:turn_duration` (Claude), classify as
  **idle** immediately (we know the agent is waiting on the user).
- Otherwise, fall back to time-based: `active` if last event ≤ 60 s ago,
  else `idle`. Bound only.

`active` and `idle` apply *only* to `live` sessions. Open intervals on a
non-live session are dangling and are emitted as warnings on transition to
`orphan` / `ended`.

## What the daemon emits

All signals go through the same OTLP endpoint already configured by
`Set-OtelEnv.ps1` (`OTEL_EXPORTER_OTLP_ENDPOINT`, `_PROTOCOL`, `_HEADERS`).
`OTEL_SERVICE_NAME` is overridden in-process to **`copilot-session-watcher`**
so dashboards can distinguish it from `github-copilot` and `claude-code`.

### Logs (Loki) — Phase A only

Phase A emits exactly three log kinds. Everything else (prompts, tool
content) is Phase A.5+.

| `event.kind`         | Cadence                                            | Purpose                                                                  |
|----------------------|----------------------------------------------------|--------------------------------------------------------------------------|
| `state_transition`   | On every change to `current_state` per epoch       | Source of truth for the dashboard's live/active/idle view (via Loki)     |
| `heartbeat`          | Every 30 s per session that is `active` or `idle`  | Keep-alive so stale entries can be aged out; carries the current state   |
| `session_shutdown`   | On `session.shutdown` event or grace-timeout crash | Carries the full shutdown payload (tokens, code changes) for analytics   |

In Phase A.5, three additional kinds appear: `user_prompt` (gated),
`tool_execution` (gated), `daemon_health` (always on).

### Metrics (Prometheus)

**No per-session labels.** Session-level data lives in Loki and Tempo. Prometheus
carries only aggregate health and rate signals about the daemon itself and the
fleet of sessions at coarse granularity. Labels are bounded to known small sets
(`tool`, `state`, `host`, `event_type`).

- `copilot_sessions{tool, state, host}` — gauge, count of sessions in each
  state on this host right now (`tool` ∈ {copilot, claude}, `state` ∈
  {active, idle, orphan}). **`live` and `ended` are intentionally omitted**:
  `live` is `active + idle` (compute on the dashboard); `ended` is a
  transition, not a state.
- `copilot_session_ended_total{tool, host, shutdown_type}` — counter,
  incremented when an epoch ends. `shutdown_type` ∈ {`graceful`, `crash`,
  `orphan_timeout`}. **`age_cap` is NOT in this set** — span-segment age
  cap is a watcher-internal span operation, not an epoch ending; it has
  its own counter below.
- `copilot_session_events_total{tool, type, host}` — counter, incremented as
  events are read from any `events.jsonl`. `type` is the event type.
- `copilot_session_watcher_lag_seconds{host}` — gauge, last observed delta
  between an event's on-disk timestamp and the time the daemon processed it.
- `copilot_session_watcher_up{host}` — gauge, 1 while the daemon is healthy,
  scraped or pushed.
- `copilot_session_watcher_tail_errors_total{tool, host}` — counter for
  per-file tail failures (e.g., events.jsonl missing, parse failure).
- `copilot_session_watcher_span_segments_total{host, reason}` — counter
  for watcher-internal span-segment rotations. `reason` ∈ {`age_cap`}.
  Not an epoch ending.

Per-session details (token totals, model names, prompts, transitions, durations)
go to Loki/Tempo where cardinality is non-issue.

## Consumption contract — how the dashboard actually reads this

`session-api/server.py` today queries Tempo + Prometheus. The state-machine
data the daemon emits goes to **Loki + Tempo**, not Prometheus (per the
cardinality decision). To make this consumable we extend the existing API
rather than invent a new one:

- Add a Loki query path to `session-api/server.py` and a new endpoint
  (e.g., `/api/sessions/state`) that returns the per-session state derived
  from the most recent watcher state-transition log per `(host,
  session_id, epoch)`.
- Loki query shape: `{service_name="copilot-session-watcher"} | json |
  event_kind="state_transition"` filtered to recent N minutes; pick the
  latest entry per session.
- Existing `gen_ai.conversation.id`-keyed Tempo queries continue to drive
  turn/token/duration aggregations. Watcher data is for **lifecycle and
  state only** — never for token or turn accounting (Copilot's native spans
  remain authoritative for those).

### Canonical telemetry schema — Phase A

Every log record from the watcher carries this baseline attribute set:

| Attribute             | Type           | Notes                                                                |
|-----------------------|----------------|----------------------------------------------------------------------|
| `service.name`        | string         | Always `"copilot-session-watcher"`. Set via OTel SDK resource.       |
| `service.version`     | string         | Daemon semver.                                                       |
| `host.name`           | string         | `Environment.MachineName`.                                           |
| `event.kind`          | string         | See "Logs" table for the bounded enum.                               |
| `tool.name`           | string         | `"copilot"` or `"claude"`.                                           |
| `session.id`          | string         | Copilot/Claude session UUID.                                         |
| `session.epoch`       | int            | 1-based epoch index within the session.                              |
| `event.timestamp`     | RFC3339+offset | The on-disk timestamp of the source event. Null for synthetic logs.  |
| `observed_at`         | RFC3339+offset | When the daemon emitted the log. Always present.                     |
| `is_backfilled`       | bool           | True if `observed_at - event.timestamp > 30 s`.                      |

State-transition logs (`event.kind="state_transition"`) add:

| Attribute             | Type     | Notes                                                              |
|-----------------------|----------|--------------------------------------------------------------------|
| `state.from`          | string   | `"active"` \| `"idle"` \| `"orphan"` \| null (initial).            |
| `state.to`            | string   | `"active"` \| `"idle"` \| `"orphan"` \| `"ended"`.                  |
| `state.reason`        | string   | Free-form short reason: `"turn_start"`, `"turn_end"`, `"timeout_60s"`, `"lock_gone"`, `"shutdown_event"`, `"lock_pid_reuse"`, etc. |
| `shutdown.type`       | string   | Only on `state.to="ended"`. One of `graceful` \| `crash` \| `orphan_timeout`. |

Heartbeat logs (`event.kind="heartbeat"`) add:

| Attribute             | Type     | Notes                                                              |
|-----------------------|----------|--------------------------------------------------------------------|
| `state.current`       | string   | `"active"` \| `"idle"` \| `"orphan"`.                              |
| `inflight.turns`      | int      | Currently open `assistant.turn` count.                             |
| `inflight.tools`      | int      | Currently open `tool.execution` count.                             |
| `inflight.hooks`      | int      | Currently open `hook` count.                                       |
| `inflight.permissions`| int      | Currently open `permission` count.                                 |
| `last_event_age_s`    | float    | Seconds since the last event was read.                             |

Session-shutdown logs (`event.kind="session_shutdown"`) add:

| Attribute                     | Type   | Source                                |
|-------------------------------|--------|---------------------------------------|
| `shutdown.type`               | string | `graceful` \| `crash` \| `orphan_timeout` |
| `shutdown.total_api_duration_ms` | int | `data.totalApiDurationMs` (null for crash) |
| `shutdown.current_model`      | string | `data.currentModel`                   |
| `shutdown.current_tokens`     | int    | `data.currentTokens`                  |
| `shutdown.code_lines_added`   | int    | `data.codeChanges.linesAdded`         |
| `shutdown.code_lines_removed` | int    | `data.codeChanges.linesRemoved`       |
| `shutdown.code_files_modified`| int    | `data.codeChanges.filesModified`      |

Lifecycle span (`name="session_watcher.lifecycle"`) attributes:

| Attribute                  | Type   | Notes                                       |
|----------------------------|--------|---------------------------------------------|
| `session.id`               | string |                                             |
| `session.epoch`            | int    |                                             |
| `tool.name`                | string |                                             |
| `host.name`                | string |                                             |
| `gen_ai.conversation.id`   | string | = `session.id`; the join key for dashboards.|
| `watcher.emitter`          | string | Always `"copilot-session-watcher"`.         |
| `watcher.force_ended_reason` | string | Only present on age-cap segment rotations. |
| `cwd`                      | string | From `session.resume`.                      |
| `repository`               | string | From `session.resume`.                      |
| `branch`                   | string | From `session.resume`.                      |
| `agency.producer`          | string | From `session.start.data.producer`.         |

**Loki labels vs JSON body fields.** Only `service_name` (Promtail/OTel
collector underscores the dot), `tool`, and `event_kind` are promoted to
Loki labels (bounded cardinality). Everything else above lives in the
log body as JSON and is queried with `| json`. Dashboards must use
`service_name` (not `service.name`) when writing LogQL stream selectors.

### Dashboard / API contract

The session-api gets one new endpoint and one new Loki query path. This is
the authoritative contract the frontend reads.

**`GET /api/sessions/state`** — returns every session known to be `active`,
`idle`, or `orphan` across all reporting hosts.

LogQL underlying query (executed inside session-api):

```
{service_name="copilot-session-watcher", event_kind=~"state_transition|heartbeat"}
  | json
  | __error__=""
```

over the last 5 min. Group by `(host_name, session_id, session_epoch)`,
pick the row with the maximum `observed_at`, treat sessions absent from
that result as `ended` (omitted from the response).

Response shape (one entry per active session):

```json
{
  "sessions": [
    {
      "sessionId": "636821d3-3682-4b18-8bf0-982c241e1e8a",
      "epoch": 1,
      "host": "cpc-afaus-sqybg",
      "tool": "copilot",
      "state": "active",
      "lastObservedAt": "2026-05-21T01:15:23.412Z",
      "lastEventAt": "2026-05-21T01:15:21.808Z",
      "lastEventAgeSeconds": 1.6,
      "inflight": { "turns": 1, "tools": 0, "hooks": 0, "permissions": 0 },
      "shutdownType": null,
      "orphanReason": null,
      "isBackfilled": false
    }
  ],
  "queriedAt": "2026-05-21T01:15:25.000Z",
  "freshnessWindowSeconds": 300
}
```

**Tile-to-query mapping** for the existing mission-control style
dashboards:

| Tile                              | Source     | Query                                                                                              |
|-----------------------------------|------------|----------------------------------------------------------------------------------------------------|
| Live sessions on this host (gauge)| Prometheus | `sum by (host) (copilot_sessions{state=~"active\|idle"})`                                          |
| Active sessions on this host      | Prometheus | `sum by (host) (copilot_sessions{state="active"})`                                                 |
| Idle sessions                     | Prometheus | `sum by (host) (copilot_sessions{state="idle"})`                                                   |
| Orphan sessions (current)         | Prometheus | `sum by (host) (copilot_sessions{state="orphan"})`                                                 |
| Sessions ended (last hour)        | Prometheus | `sum(increase(copilot_session_ended_total[1h])) by (shutdown_type)`                                |
| Per-session live list             | session-api| `GET /api/sessions/state`                                                                          |
| Per-session detail (history)      | Tempo      | TraceQL `{ service.name="copilot-session-watcher" && span.session.id="<id>" }` ordered by start    |
| Per-session token totals          | Tempo      | TraceQL on native `service.name="github-copilot"` joined by `gen_ai.conversation.id` (unchanged)   |

The contract: a frontend dev should be able to wire each tile to its
query without rereading the rest of the plan.

### Span naming — avoid double-counting

To prevent the existing dashboards from accidentally summing watcher spans
with native `invoke_agent` / `chat` / tool spans:

- Watcher span names: `session_watcher.lifecycle` (root, per epoch) and
  `session_watcher.turn` (child, per assistant turn). Distinct from any
  native span name.
- Watcher spans carry `gen_ai.conversation.id` for join, plus
  `watcher.emitter = "copilot-session-watcher"` for explicit filtering.
- Existing queries in `test-active-detection.py`, `create-mission-control-*.py`,
  and `session-api/server.py` continue to filter on
  `service.name = "github-copilot"` (or `"claude-code"`) — watcher service
  name `"copilot-session-watcher"` won't be picked up by them. Any new
  query that wants watcher data filters on
  `service.name = "copilot-session-watcher"` explicitly.

### Open root spans are not "live" signal

OTel spans only export on `End()`. A long-lived `session_watcher.lifecycle`
span is *not* visible in Tempo until the epoch ends. The dashboard's "is
this session live right now?" answer comes from:

1. The watcher's most recent state-transition log in Loki, OR
2. The watcher's most recent heartbeat log in Loki

Never from Tempo for live state. Tempo gets the lifecycle span on epoch
end, used for historical lifetime queries.

### Heartbeats

- Once every 30 s per **live** session: emit one log record + update all gauges.
  State is recomputed on each tick.
- Emit heartbeats for `orphan` sessions too, so stale locks show up in the
  dashboard.

### Traces (Tempo)

Watcher traces split by phase:

- **Phase A.** One root span per **lifecycle epoch** —
  `name=session_watcher.lifecycle`. Opened in memory on `session.start`
  (or on daemon-startup discovery of an in-flight epoch). `End()`-ed on
  `session.shutdown` (`graceful`), on the 10 s post-lock-loss grace
  expiration (`crash`), or on `orphan_timeout` (5 min). Span carries the
  attributes listed in the canonical telemetry schema above.
- **Phase A.5.** One child span per `assistant.turn_start` →
  `assistant.turn_end` pair — `name=session_watcher.turn`. Token counts
  are NOT attached (Copilot's native spans are authoritative for tokens).
  Not in Phase A.
- No tool spans, ever — Copilot already emits those natively; don't
  duplicate.

**Age cap is span-level, not epoch-level.** Long-lived open spans risk
memory leaks and stalled exports. The daemon caps any open
`session_watcher.lifecycle` span at 24 h. On hit, it does:

1. End the current span with attribute `watcher.force_ended_reason="age_cap"`.
2. Increment `copilot_session_watcher_span_segments_total{reason="age_cap"}`.
3. Open a successor span for the same epoch, linked to the previous via
   a span link. The successor inherits all epoch attributes.

This is purely a span-export concern. The **session/epoch is not ended**
by this rotation — the state machine, metrics, and logs continue
uninterrupted. `copilot_session_ended_total` is NOT incremented.

### Privacy — content capture is off by default

The daemon never logs prompt text, attachment contents, tool arguments, or
tool results unless the existing privacy gates are explicitly set in the
environment:

- `OTEL_LOG_USER_PROMPTS=1` *or*
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` — enables
  emitting `user.message` content. Off → emit only a redacted log record
  with `prompt.length`, `prompt.attachment_count`, and `prompt.hash`
  (SHA-256, truncated) for de-duplication.
- `OTEL_LOG_TOOL_DETAILS=1` — enables `tool.execution_*` argument/result
  attributes on watcher spans. Off → emit only `tool.name` + duration.
- `OTEL_LOG_TOOL_CONTENT=1` — enables full tool result content. Default
  off.

This mirrors `Set-OtelEnv.ps1`'s opt-in model. Without these gates, no user
content reaches the OTel pipeline, even though it's all available on disk.

## Architecture

```
                   ┌───────────────────────────────────┐
                   │  copilot-session-watcher (C#)     │
                   │                                   │
~/.copilot/        │  ┌─────────────────────────────┐  │       ┌──────────────┐
session-state/  ─► │  │ FileSystemWatcher x2        │  │       │ OTLP gRPC /  │
                   │  │  - Copilot: session-state\  │  │  ───► │ http-proto   │
~/.claude/         │  │      (new session dirs)     │  │       │ collector    │
sessions/       ─► │  │  - Claude: ~/.claude/       │  │       └──────────────┘
                   │  │      sessions\ (new         │  │
                   │  │      <pid>.json pidfiles)   │  │
~/.claude/         │  └────────────┬────────────────┘  │
projects/       ─► │               │                   │       (collector
                   │  ┌────────────▼────────────────┐  │        already
                   │  │ SessionTailer (per session) │  │        running via
                   │  │  - tail events.jsonl        │  │        docker-compose
                   │  │      (Copilot) OR           │  │        or Azure)
                   │  │    tail <sid>.jsonl         │  │
                   │  │      (Claude)               │  │
                   │  │  - poll lock/pidfile + PID  │  │
                   │  │  - state machine            │  │
                   │  │  - emit logs + spans        │  │
                   │  └────────────┬────────────────┘  │
                   │               │                   │
                   │  ┌────────────▼────────────────┐  │
                   │  │ HeartbeatTimer (30s)        │  │
                   │  │  - per-session tick         │  │
                   │  │  - emit metrics + log       │  │
                   │  └─────────────────────────────┘  │
                   └───────────────────────────────────┘
```

### Why C#

- The user knows C# well.
- Modern .NET has first-class OpenTelemetry SDK
  (`OpenTelemetry`, `OpenTelemetry.Exporter.OpenTelemetryProtocol`,
  `OpenTelemetry.Extensions.Hosting`).
- Native cross-platform file watching, single-file publish, and Windows Service
  hosting via `Microsoft.Extensions.Hosting.WindowsServices`.
- Rest of CopilotOtel is Python/Bash/PowerShell — keeping the daemon in C#
  doesn't conflict and avoids another Python dependency on the client side.

### Project layout (proposed)

```
session-watcher/
├── SessionWatcher.sln
├── src/
│   ├── SessionWatcher/                # main daemon
│   │   ├── SessionWatcher.csproj
│   │   ├── Program.cs                 # generic host setup
│   │   ├── Telemetry/
│   │   │   ├── OtelSetup.cs           # standard OTEL_* env-var wiring
│   │   │   └── SessionMeters.cs
│   │   ├── Sources/
│   │   │   ├── ISessionSource.cs
│   │   │   ├── CopilotSource.cs       # ~/.copilot/session-state watcher
│   │   │   └── ClaudeSource.cs        # ~/.claude/sessions + ~/.claude/projects (Phase B)
│   │   ├── Tailing/
│   │   │   ├── SessionTailer.cs       # owns one session
│   │   │   ├── EventsJsonlTail.cs     # newline-delim JSON tail w/ position
│   │   │   └── LockProbe.cs           # check inuse.<pid>.lock + IsAlive
│   │   ├── State/
│   │   │   ├── SessionState.cs        # enum + transition table
│   │   │   └── ActivityClassifier.cs  # event timeline -> active/idle
│   │   └── appsettings.json
│   └── SessionWatcher.Tests/          # xUnit
└── docs/
    └── samples/                       # captured events.jsonl snippets
```

### Tailing — append-only JSONL with cursor + partial-line buffer

The tail loop's correctness is the foundation of everything else. Rules:

- Open `events.jsonl` with **shared read** (Windows: `FileShare.ReadWrite |
  FileShare.Delete`; Unix: default `O_RDONLY`). Copilot writes with shared
  read so this is fine, but it must be explicit on Windows.
- Maintain `(filePosition, pendingBuffer)` per session. After each read,
  scan the buffer for complete newline-terminated JSON values.
- **Advance the file cursor only after a complete JSON value is parsed and
  emitted.** Bytes after the last newline stay in `pendingBuffer` for the
  next read. This means a crashing writer that leaves a partial last line
  never poisons or skips events.
- If `pendingBuffer` grows beyond a sanity cap (e.g., 1 MB) without a
  terminating newline, flush + drop with an explicit
  `watcher.tail_quarantine` log event so the issue is visible. Reset
  cursor to current EOF — better to skip than loop forever.
- Treat each parsed value as immutable past the cursor advance. Idempotent
  emission must hold from "I saw this byte" onward, not from "I emitted
  it" onward (the OTel exporter has its own queue / retries).

### File rotation / replacement detection

The plan no longer assumes events.jsonl never rotates. On each tail tick:

- Track `(deviceId, inode)` on Unix; on Windows track
  `(volumeSerial, fileIndex)` from `GetFileInformationByHandle`. If those
  change, the file was atomically replaced — treat as a new stream epoch:
  reset cursor to 0, log a `watcher.stream_replaced` event, parse from
  scratch.
- If file size *shrinks* between reads (truncate), same treatment.
- Re-confirm the first event in the file matches the session ID encoded in
  the directory name. If it doesn't, log + skip rather than emit
  mismatched events.

### FileSystemWatcher is a hint, not a source of truth

FSW reliability varies wildly: it drops events under load, coalesces rapid
writes, behaves differently on network/synced folders, and on some Windows
versions misses individual filename events when an entire directory is
moved.

Implementation:

- FSW is a *wake-up* signal. When it fires, schedule an immediate tail tick.
- A periodic poll runs unconditionally every 2 s (configurable). Each tick
  re-stats every known session's events.jsonl + lock file, and does a
  full re-scan of the session-state directory for new dirs that FSW
  may have missed.
- The poll cadence and FSW work in tandem; either alone is insufficient.

### State persistence

Daemon persists per-epoch state to
`%LOCALAPPDATA%\CopilotOtel\session-watcher\cursor.json` (or the
platform equivalent: `~/Library/Application Support/CopilotOtel/...`
on macOS; `$XDG_STATE_HOME/CopilotOtel/...` or
`~/.local/state/CopilotOtel/...` on Linux). The persisted record per
session epoch must be sufficient to resume the state machine without
replay:

```jsonc
{
  "sessionId": "636821d3-3682-4b18-8bf0-982c241e1e8a",
  "epoch": 3,
  "tool": "copilot",
  "epochStartedAt": "2026-05-20T16:50:11.001Z",
  "epochAttrs": {
    "cwd": "...", "repository": "...", "branch": "...",
    "agency.producer": "..."
  },
  "filePosition": 123456,
  "pendingBufferBytes": 0,
  "fileIdentity": { "kind": "ntfs", "volumeSerial": "...", "fileIndex": "..." },
  "lastEventTime": "2026-05-20T17:30:47.857Z",
  "lastEventType": "assistant.turn_end",
  "lastState": "idle",
  "inflight": {
    "turns":      { "openIds": [] },
    "tools":      { "openIds": ["tc_abc"] },
    "hooks":      { "openIds": [] },
    "permissions":{ "openIds": [] }
  },
  "lifecycleSpan": {
    "traceId": "...", "spanId": "...",
    "openedAt": "2026-05-20T16:50:11.030Z",
    "segmentIndex": 1
  },
  "shutdownStatus": "none",
  "lockGoneSince": null,
  "orphanSince": null,
  "observedAt": "2026-05-21T01:15:00Z"
}
```

`observedAt` distinguishes "when the daemon last saw an event" from
"when the event happened" — important for backfill correctness. The
`openIds` arrays let us correctly close in-flight intervals across
restarts (a turn that opened in the previous daemon run remains open
after restart). The `lifecycleSpan` block lets us continue the same
trace context across restart instead of orphaning the historical span.

Cursor is rewritten atomically (`tempfile + rename`). A corrupted cursor
falls back to cold-start for affected sessions.

### Backfill on startup

Three startup modes, picked based on what the cursor file says vs. what's on
disk:

1. **Cold start** (no cursor file): scan the session-state dir; for each
   session with `inuse.*.lock` still present, treat as in-flight and start
   tailing from byte 0; emit a single `watcher.cold_start` log noting
   "events emitted are historical, observedAt = now". Sessions whose lock
   is gone and whose last event is older than 24 h are skipped entirely
   (already-ended ancient history; don't pollute Tempo).
2. **Warm start** (cursor file present, daemon was off briefly): resume
   from saved `filePosition` per session. Validate fileIdentity matches;
   if not, treat that session as cold-start.
3. **Gap recovery** (cursor file present but daemon was off long enough
   that sessions ended during the gap): for any session whose final
   `session.shutdown` happened during the gap, emit a synthetic
   `session_watcher.lifecycle` span retroactively using on-disk timestamps,
   `End()`-ed immediately. State-transition logs for those sessions carry
   `observedAt` distinct from event timestamps so dashboards can show "this
   was backfilled, not live".

### Single-instance lock

Cross-platform single-instance enforcement, scoped per **(user, host)** —
never global, never cross-user. Implementation uses a held-open advisory
file lock so it works the same on every platform and survives
RDP/fast-user-switching without surprise:

- **All platforms.** Acquire an `LockFile`/`flock`-style exclusive lock
  on `<state-dir>/session-watcher.lock`, holding the file open for the
  daemon's lifetime. The OS releases the lock automatically when the
  process exits or is killed, so a crashed daemon never blocks the next
  start.
  - Windows state dir: `%LOCALAPPDATA%\CopilotOtel\session-watcher\`
    (per-user by NTFS ACL, so cross-user collisions can't happen).
  - macOS state dir: `~/Library/Application Support/CopilotOtel/session-watcher/`
  - Linux state dir: `${XDG_STATE_HOME:-$HOME/.local/state}/CopilotOtel/session-watcher/`
- A named mutex was considered for Windows but rejected: `Local\` mutexes
  are scoped to the logon session, which allows duplicates under RDP and
  fast user switching; `Global\` mutexes require explicit SID-based ACLs
  and still don't help on non-Windows. A file lock in the per-user state
  dir is simpler and uniform.
- On lock-acquire failure, read the companion `pidfile.txt` (written
  alongside the lock by the holding daemon) and log a single
  `watcher.singleton_conflict` message naming the other PID, then exit 0.
- The pidfile is observability only — the lock is the authority.

### OTLP configuration — explicit, not magic

`Set-OtelEnv.ps1` configures the current shell. Task Scheduler /
LaunchAgent / systemd-user jobs do **not** inherit that environment. The
daemon's resolution order for OTLP endpoint + protocol + headers:

1. Process environment (set by the autostart hook or by the user
   manually).
2. Config file at the state-dir root:
   `%LOCALAPPDATA%\CopilotOtel\session-watcher\config.json` — same keys
   as the OTEL env vars (uppercase). Written by the installer.
3. If neither is configured: log a single warning, **continue to run**,
   write all telemetry to a local rolling file at
   `<state-dir>\logs\watcher.log` + emit nothing over OTLP. The daemon's
   own health is observable on disk; the dashboard simply won't see this
   host until the installer is re-run.

The installer (`setup-client.ps1` / `setup-client.sh`) is the canonical
place that persists OTLP settings for the autostart hook. Document this
explicitly so the user doesn't lose data after a reboot.

### Failure modes

- **Daemon crash:** position cursor + idempotent emission means a restart
  catches up cleanly. We may double-emit at most the events between the
  last persisted cursor and the actual stream position, which OTel signals
  tolerate.
- **Events.jsonl rotation/truncation:** covered above under "File rotation
  / replacement detection" — fileIdentity + size-shrink triggers a fresh
  stream epoch.
- **Collector down:** OTel SDK does its own bounded queue + retry. We
  don't try to outsmart it. The cursor still advances so we don't backlog
  forever; the gap shows up in `copilot_session_watcher_lag_seconds`.
- **Clock skew:** all timestamps in events.jsonl are ISO-8601 with
  timezone, so we use those verbatim for span start/end rather than
  `DateTimeOffset.UtcNow`. `observedAt` uses the daemon clock and is the
  only place skew can leak in.
- **Stale cursor for a session that no longer exists:** GC on startup —
  drop cursor entries whose directory is gone, log one
  `watcher.cursor_gc` event per drop.
- **Daemon's own log noise:** rolling file at
  `<state-dir>\logs\watcher.log`, 10 MB × 5 files, drop oldest. **These
  are the daemon's internal diagnostic logs only** (exception traces,
  config dumps, lock acquisition messages). They are NOT sent over OTel
  — that would loop or pollute Loki with watcher-internal noise.

  Distinct from these are the watcher's **OTel logs** (Phase A:
  `state_transition`, `heartbeat`, `session_shutdown`; Phase A.5
  adds a `daemon_health` heartbeat-style log emitted every 60 s
  carrying `copilot_session_watcher_up`, queue depths, last export
  error, etc.). Phase A relies on the metric
  `copilot_session_watcher_up` and the rolling file for daemon-health
  observability; no `daemon_health` log over OTel yet.

## Phasing

### Phase A — heartbeat + state, minimum viable (v1)

Scope cut deliberately: this phase only proves the lifecycle/state pipeline
works. No prompt content, no turn spans. Defer content surface to A.5
once the dashboard contract is validated.

1. Scaffold the .NET project + OTel wiring (logs, metrics, traces).
2. `CopilotSource` discovers existing + new session dirs under
   `%USERPROFILE%\.copilot\session-state\` via FSW + 2 s polling.
3. `EventsJsonlTail` reads events with position cursor + partial-line
   buffer + fileIdentity tracking.
4. State machine (`active` / `idle` / `orphan` current state + `ended`
   transitions) with epoch tracking and the 30 s heartbeat timer.
5. Emit:
   - Loki: `state_transition` and `heartbeat` log records (and
     `session_shutdown` records). NO `user_prompt`, NO `tool_execution`,
     NO `daemon_health` logs in Phase A.
   - Prometheus: the aggregate gauges + counters defined above.
   - Tempo: `session_watcher.lifecycle` spans ONLY. No
     `session_watcher.turn` spans yet.
6. Extend `session-api/server.py` with a Loki query path + a
   `/api/sessions/state` endpoint sourced from watcher state-transition
   logs.
7. Smoke test: open a Copilot session; observe live → active → idle →
   ended transitions in Loki/Prometheus and a lifecycle span in Tempo on
   shutdown. Crash a session (kill -9) and observe transition to
   `orphan`.

### Phase A.5 — content surface

1. Add `session_watcher.turn` child spans (assistant.turn_start →
   assistant.turn_end).
2. Add `user.message` log records, gated on
   `OTEL_LOG_USER_PROMPTS` (default redacted).
3. Add tool execution attributes on turn spans gated on
   `OTEL_LOG_TOOL_DETAILS` / `OTEL_LOG_TOOL_CONTENT`.
4. Validate dashboard correctness — no double-counting against
   `github-copilot` native spans.

### Phase B — Claude Code

Schema verified; samples committed under `docs/samples/claude/`. The
remaining work is implementation:

1. Implement `ClaudeSource` to:
   - Discover live sessions by enumerating
     `%USERPROFILE%\.claude\sessions\*.json` (FSW + 2 s poll, same
     pattern as Copilot).
   - For each pidfile, parse `{pid, sessionId, cwd}` and locate the
     matching transcript at
     `%USERPROFILE%\.claude\projects\<sanitize(cwd)>\<sessionId>.jsonl`.
     The cwd-sanitization rule is documented in
     `docs/samples/claude/README.md` (drive `:` → `--`, separators → `-`,
     case preserved).
   - Synthesize the Claude → Copilot event mapping from the table in
     the "Claude Code — confirmed" section above, before events hit
     the shared `SessionTailer` state machine.
2. Add Claude-specific lock-authority handling:
   - PID source = both the filename AND the `pid` field in the JSON
     body (require equality).
   - `sessions\<pid>.json` deletion + PID dead = graceful shutdown.
   - `sessions\<pid>.json` present + PID dead = crash.
3. Dedupe assistant `message.usage` by `msg_id` before any token
   aggregation (Phase A.5 token surface).
4. Skip the permission open-interval counter for Claude — not
   first-class in the transcript; treat denials as one-shot signals
   sourced from `attachment.exitCode != 0`.

### Phase C — Autostart + cross-platform packaging

The daemon runs as a **plain user process**, not a system service. Rationale:

- The transcripts we watch are user-scoped (`%USERPROFILE%\.copilot\`,
  `~/.claude\`). A system service would have to impersonate or run-as the
  user, which buys nothing.
- A plain process gives us trivial macOS and Linux portability.
- The "one instance" property is enforced in-process via a single-instance
  lock (named mutex on Windows, advisory `flock` on Unix at
  `$XDG_RUNTIME_DIR/copilot-session-watcher.lock`). On startup the daemon
  acquires the lock; if it can't, it logs and exits 0.

Per-platform autostart:

- **Windows.** Task Scheduler entry, trigger = "at logon of any user, this
  user", action = the daemon exe. Install via `setup-client.ps1`. (Startup
  folder shortcut works too but Task Scheduler gives us a clean
  delayed-start + restart-on-fail policy.)
- **macOS.** A `LaunchAgent` plist at
  `~/Library/LaunchAgents/com.copilotOtel.session-watcher.plist`,
  `RunAtLoad=true`, `KeepAlive=true`. Install via
  `setup-client.sh` (new — sibling to `setup-client.ps1`).
- **Linux.** `systemd --user` unit at
  `~/.config/systemd/user/copilot-session-watcher.service`, enabled via
  `systemctl --user enable --now`.

The .NET binary is published as a self-contained single-file executable for
each RID we target: `win-x64`, `osx-arm64`, `osx-x64`, `linux-x64`,
`linux-arm64`. Distribution mechanism is whatever
`azure-deploy/setup-client.*` ends up doing — likely fetching the right asset
from a GitHub Release.

## Decisions (locked) and remaining open items

Locked:

- **Cardinality.** No per-session labels on Prometheus metrics. Session-level
  data goes to Loki and Tempo only.
- **Hosting.** Plain user process with single-instance lock. Autostart per
  platform (Task Scheduler / LaunchAgent / systemd-user). Not a system
  service.
- **Trace correlation.** Daemon emits its own session-root + per-turn spans
  in a separate trace from Copilot's native `invoke_agent` spans, linked by
  `gen_ai.conversation.id`.
- **Active timeout.** 60 s default for live→idle. May tune after dogfood.
- **Where it runs.** Per-client-machine. Never centrally.

Still open:

*(none — Claude transcript verification was completed 2026-05-21;
samples committed under `docs/samples/claude/` and the daemon design is
unblocked for both tools.)*

## Context carried over from copilot-detour

The MITM proxy in `aef123/copilot-detour` (Phase 1 complete) is **preserved as
is** for the LLM-protocol-level capture use case (raw Anthropic Messages
bodies, exact token deltas as emitted by the model API, debugging Copilot
internals). It is **not** the path for general session telemetry — this daemon
is. The two are complementary: the proxy hooks the wire, the daemon hooks the
disk.

Key findings from copilot-detour Phase 1 that informed this plan:

- The MITM approach required CA install + allow-list + per-process wrapping +
  ongoing maintenance against schema changes in the Anthropic Messages format.
  The events.jsonl approach has none of those costs.
- Copilot's agentic loop re-sends the full conversation on every internal API
  call, which made one-prompt-per-record reporting hard from the wire side.
  events.jsonl has clean `user.message` events at exactly user-prompt
  boundaries — no aggregation needed.
- The proxy can't see anything until the user wraps the command with
  `session-bridge run`. The daemon captures every session automatically,
  including ones the user forgot to wrap.
- Standard `OTEL_EXPORTER_OTLP_*` env vars are the right cross-tool config
  surface — both Copilot and Claude already honor them, and the daemon picks
  them up for free without any custom config.
