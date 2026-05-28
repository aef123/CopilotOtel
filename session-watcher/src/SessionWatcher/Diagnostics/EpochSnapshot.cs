using SessionWatcher.State;

namespace SessionWatcher.Diagnostics;

/// <summary>
/// Snapshot of a session epoch's state at one observation tick.
/// Carries the attributes that ride along OTel logs/metrics/spans for the epoch.
/// </summary>
public sealed record EpochSnapshot(
    string Tool,              // "claude" or "copilot"
    string SessionId,
    int Pid,
    int Epoch,                // 1-based index of lifecycle epoch within session
    string Host,              // Environment.MachineName at observation time
    EpochState State,
    DateTimeOffset ObservedAt,
    // Tool-specific attributes — null when not applicable
    string? Cwd = null,
    string? Version = null,
    DateTimeOffset? StartedAt = null,
    // Last moment the underlying tool itself touched its lockfile/pidfile.
    // Stable across daemon restarts and heartbeat ticks — use this (not
    // ObservedAt) when reporting "last activity" for closed sessions.
    DateTimeOffset? LastActivityAt = null,
    string? ClaudeStatus = null,
    string? ClaudeKind = null,
    string? ClaudeEntrypoint = null);
