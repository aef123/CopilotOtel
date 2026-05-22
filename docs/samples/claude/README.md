# Claude Code session-state samples

Captured 2026-05-21 on a Windows 11 machine running Claude Code `2.1.147`
(installed via WinGet at `C:\Users\<user>\AppData\Local\Microsoft\WinGet\Links\claude.exe`).

These samples are reduced from a live session for the purpose of pinning down
the schema the session-watcher daemon must consume. Long content bodies and
hook stdout are truncated or elided; identifiers are real but the underlying
session is the one in which this plan was drafted, so nothing sensitive.

## Files in this directory

| File                          | Source on disk                                                                  | Purpose                                                                |
|-------------------------------|---------------------------------------------------------------------------------|------------------------------------------------------------------------|
| `pidfile.json`                | `%USERPROFILE%\.claude\sessions\<pid>.json`                                     | The authoritative per-process liveness file. Watcher's lock authority. |
| `transcript-excerpts.jsonl`   | `%USERPROFILE%\.claude\projects\<sanitized-cwd>\<session-id>.jsonl`             | One representative record per `type` / `subtype` the daemon must parse. |
| `directory-layout.txt`        | `dir %USERPROFILE%\.claude` plus per-session subdirs                            | Concrete tree for the daemon's discovery + GC code.                    |

## Key facts the daemon depends on (verified)

- **Per-session transcript path:** `%USERPROFILE%\.claude\projects\<sanitized-cwd>\<session-id>.jsonl`.
  The `<sanitized-cwd>` rule observed: drive letters become `c--`,
  separators become `-`. Examples: `c:\git\OtelCliCapture` →
  `c--git-OtelCliCapture`; `C:\WINDOWS\system32` → `C--WINDOWS-system32`.
  Case is preserved (we have both `C--git-...` and `c--git-...`
  directories side-by-side from sessions launched with different cwd
  casing).
- **Liveness file:** `%USERPROFILE%\.claude\sessions\<pid>.json` —
  one per **live** Claude process, removed on graceful exit. **There is
  no `inuse.<pid>.lock`-style file inside the session directory** —
  unlike Copilot.
- **Pidfile body** (single line, no trailing newline):
  ```json
  {"pid":38112,"sessionId":"79ebdd64-...","cwd":"c:\\git\\OtelCliCapture",
   "startedAt":1779427166873,"version":"2.1.147","peerProtocol":1,
   "kind":"interactive","entrypoint":"cli",
   "status":"busy","updatedAt":1779427261873}
  ```
- **`status` field** observed value: `"busy"` during in-flight work.
  Flips between `busy` and (assumed but not directly observed in this
  capture) `"idle"` between turns. `updatedAt` ticks **only on status
  changes** — it is NOT a per-second heartbeat. Confirmed: `updatedAt`
  did not change during a 6 s observation window while the session was
  actively doing tool calls.
- **No `session.start` / `session.shutdown` events** exist in the
  JSONL. Lifecycle MUST be derived from pidfile presence + PID-alive
  validation, not from transcript content.

## Distinct transcript record `type` values observed

Counts from the live session at capture time (229 KB JSONL):

| `type`                  | Count | Purpose                                                                                                  |
|-------------------------|------:|----------------------------------------------------------------------------------------------------------|
| `user`                  |    29 | Human prompts AND tool results. Distinguished by `toolUseResult` presence and parent chain.              |
| `assistant`             |    36 | One record **per content block** (`thinking` / `text` / `tool_use`). Multiple records share one `msg_id`. |
| `system`                |     2 | Lifecycle-of-turn markers. See `subtype` table below.                                                    |
| `attachment`            |     8 | Hook outputs attached to the conversation.                                                               |
| `ai-title`              |     4 | Auto-generated short session title.                                                                      |
| `last-prompt`           |     5 | Sentinel record pointing to the latest user prompt UUID (overwritten each turn).                         |
| `permission-mode`       |     5 | Current permission mode at the time the record was written.                                              |
| `file-history-snapshot` |     3 | Snapshot of file backups (for the Read/Edit safety system).                                              |

## `system.subtype` values observed

| `subtype`            | Trigger                       | Useful fields                                                                                                                |
|----------------------|-------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| `turn_duration`      | Emitted at the END of each turn | `durationMs`, `messageCount`, `timestamp`, `uuid`, `sessionId`                                                               |
| `stop_hook_summary`  | Emitted before `turn_duration`  | `hookCount`, `hookInfos[]` (each with `command`, optional `durationMs`), `hookErrors[]`, `preventedContinuation`, `stopReason` |

## Notes for the daemon implementer

- `assistant` records that share a `msg_id` carry the SAME `message.usage`
  payload (one Anthropic API call → multiple JSONL rows). Dedupe token
  totals by `msg_id` or you will multiply the count 3–5×.
- Tool execution has no discrete start/end records. Open interval =
  from `assistant` record with content block `{"type":"tool_use",
  "id":"toolu_..."}` to the matching `user` record carrying
  `content_blocks` containing `{"type":"tool_result","tool_use_id":
  "toolu_..."}`.
- Hook execution is reported as `attachment` rows individually (one per
  hook) AND summarized at turn end via `system / stop_hook_summary`.
  Daemon should NOT double-count; prefer `attachment` for per-hook
  spans, use `stop_hook_summary` only for aggregate flags
  (`preventedContinuation`, `hookErrors`).
- Sessions that are started but never used (e.g., resumed via
  `claude --resume <id>` then immediately exited) appear as small
  JSONL files containing only `permission-mode`, `last-prompt`, and
  maybe `file-history-snapshot` records — no `assistant`/`system`.
  Daemon should treat these as ended-immediately, not crashed.
- Resumed sessions APPEND to the existing `<sid>.jsonl`. The same
  session ID may therefore correspond to multiple lifecycle epochs in
  one file — same model as Copilot.
