using System.Collections.Concurrent;
using System.Diagnostics;
using System.Diagnostics.Metrics;
using Microsoft.Extensions.Logging;
using SessionWatcher.Diagnostics;
using SessionWatcher.State;

namespace SessionWatcher.Telemetry;

/// <summary>
/// Emits epoch events as OTel logs (via ILogger), metrics (via Meter), and
/// traces (via ActivitySource). The SDK configured in <see cref="OtelSetup"/>
/// routes all three to the same OTLP endpoint.
/// </summary>
public sealed class OtelSink : IEpochEventSink
{
    private readonly ILogger _logger;
    private readonly string _host = Environment.MachineName;

    // Per-epoch lifecycle Activities, keyed by (tool, sessionId, epoch).
    private readonly ConcurrentDictionary<string, Activity> _lifecycle = new();

    // Current per-(tool, state) session counts, surfaced via an ObservableGauge.
    private readonly ConcurrentDictionary<(string Tool, EpochState State), int> _stateCounts = new();

    // Total epochs ended, broken out by shutdown type.
    private readonly Counter<long> _endedCounter;

    public OtelSink(ILogger<OtelSink> logger)
    {
        _logger = logger;

        WatcherTelemetry.Meter.CreateObservableGauge(
            "copilot.sessions",
            ObserveStateCounts,
            unit: "{session}",
            description: "Current sessions by tool and state on this host.");

        WatcherTelemetry.Meter.CreateObservableGauge(
            "copilot.session.watcher.up",
            () => new Measurement<int>(1, new KeyValuePair<string, object?>("host", _host)),
            description: "1 while the watcher process is running and healthy.");

        _endedCounter = WatcherTelemetry.Meter.CreateCounter<long>(
            "copilot.session.ended",
            unit: "{epoch}",
            description: "Lifecycle epochs that have ended, by shutdown_type.");
    }

    public void OnTransition(EpochSnapshot snapshot, EpochState from, EpochState to, ShutdownType? shutdown)
    {
        UpdateStateCounts(snapshot.Tool, from, to);

        if (IsAliveState(to) && from == EpochState.Opening)
        {
            StartLifecycleSpan(snapshot);
        }
        else if (IsAliveState(to) && from == EpochState.Closed && !TrackedHasSpan(snapshot))
        {
            // Orphan that recovered before we ever opened a span (cold-start case).
            StartLifecycleSpan(snapshot);
        }
        else if (to == EpochState.Ended)
        {
            EndLifecycleSpan(snapshot, shutdown);

            var shutdownLabel = shutdown switch
            {
                ShutdownType.Graceful => "graceful",
                ShutdownType.Crash => "crash",
                _ => "unknown",
            };

            _endedCounter.Add(1,
                new KeyValuePair<string, object?>("tool", snapshot.Tool),
                new KeyValuePair<string, object?>("host", _host),
                new KeyValuePair<string, object?>("shutdown_type", shutdownLabel));
        }

        using (_logger.BeginScope(BuildBaseScope(snapshot)))
        {
            _logger.LogInformation(
                "state_transition {From} -> {To}{Shutdown}",
                from, to, shutdown is null ? "" : $" ({shutdown})");
        }
    }

    public void OnHeartbeat(EpochSnapshot snapshot)
    {
        using (_logger.BeginScope(BuildBaseScope(snapshot)))
        {
            _logger.LogInformation(
                "heartbeat {Tool}/{SessionShort} state={State}",
                snapshot.Tool, ShortId(snapshot.SessionId), snapshot.State);
        }
    }

    public void OnOrphanTimeout(EpochSnapshot snapshot)
    {
        // Stop counting in the orphan gauge for this epoch — increments
        // the ended counter under shutdown_type=orphan_timeout. The epoch
        // stays in Orphan state for visibility but doesn't accrue further.
        _stateCounts.AddOrUpdate((snapshot.Tool, EpochState.Closed),
            _ => 0,
            (_, prev) => Math.Max(0, prev - 1));

        _endedCounter.Add(1,
            new KeyValuePair<string, object?>("tool", snapshot.Tool),
            new KeyValuePair<string, object?>("host", _host),
            new KeyValuePair<string, object?>("shutdown_type", "closed_timeout"));

        using (_logger.BeginScope(BuildBaseScope(snapshot)))
        {
            _logger.LogWarning(
                "orphan_timeout {Tool}/{SessionShort} (stale lock; epoch closed for accounting)",
                snapshot.Tool, ShortId(snapshot.SessionId));
        }
    }

    private void StartLifecycleSpan(EpochSnapshot snapshot)
    {
        var activity = WatcherTelemetry.ActivitySource.StartActivity(
            "session_watcher.lifecycle",
            ActivityKind.Internal,
            parentContext: default,
            startTime: snapshot.StartedAt ?? snapshot.ObservedAt);

        if (activity is null) return;

        SetActivityAttrs(activity, snapshot);
        _lifecycle[LifecycleKey(snapshot)] = activity;
    }

    private void EndLifecycleSpan(EpochSnapshot snapshot, ShutdownType? shutdown)
    {
        if (!_lifecycle.TryRemove(LifecycleKey(snapshot), out var activity)) return;

        if (shutdown is not null)
        {
            activity.SetTag("shutdown.type", shutdown.ToString()?.ToLowerInvariant());
        }
        activity.SetEndTime(snapshot.ObservedAt.UtcDateTime);
        activity.Stop();
        activity.Dispose();
    }

    private static void SetActivityAttrs(Activity activity, EpochSnapshot s)
    {
        activity.SetTag("tool.name", s.Tool);
        activity.SetTag("session.id", s.SessionId);
        activity.SetTag("session.epoch", s.Epoch);
        activity.SetTag("host.name", s.Host);
        activity.SetTag("gen_ai.conversation.id", s.SessionId);
        activity.SetTag("watcher.emitter", WatcherTelemetry.ServiceName);
        if (s.Cwd is not null) activity.SetTag("cwd", s.Cwd);
        if (s.Version is not null) activity.SetTag("tool.version", s.Version);
        if (s.ClaudeKind is not null) activity.SetTag("claude.kind", s.ClaudeKind);
        if (s.ClaudeEntrypoint is not null) activity.SetTag("claude.entrypoint", s.ClaudeEntrypoint);
    }

    private static string LifecycleKey(EpochSnapshot s) => $"{s.Tool}|{s.SessionId}|{s.Epoch}";

    private static string ShortId(string sessionId) =>
        sessionId.Length > 8 ? sessionId[..8] : sessionId;

    private static bool IsReportedState(EpochState s) =>
        s is EpochState.Live or EpochState.Active or EpochState.Idle or EpochState.Closed;

    private static bool IsAliveState(EpochState s) =>
        s is EpochState.Live or EpochState.Active or EpochState.Idle;

    private bool TrackedHasSpan(EpochSnapshot s) => _lifecycle.ContainsKey(LifecycleKey(s));

    private void UpdateStateCounts(string tool, EpochState from, EpochState to)
    {
        if (IsReportedState(from))
        {
            _stateCounts.AddOrUpdate((tool, from),
                _ => 0,
                (_, prev) => Math.Max(0, prev - 1));
        }
        if (IsReportedState(to))
        {
            _stateCounts.AddOrUpdate((tool, to),
                _ => 1,
                (_, prev) => prev + 1);
        }
    }

    private IEnumerable<Measurement<int>> ObserveStateCounts()
    {
        foreach (var ((tool, state), count) in _stateCounts)
        {
            yield return new Measurement<int>(count,
                new KeyValuePair<string, object?>("tool", tool),
                new KeyValuePair<string, object?>("state", state.ToString().ToLowerInvariant()),
                new KeyValuePair<string, object?>("host", _host));
        }
    }

    private Dictionary<string, object> BuildBaseScope(EpochSnapshot s)
    {
        var scope = new Dictionary<string, object>
        {
            ["service.name"] = WatcherTelemetry.ServiceName,
            ["service.version"] = WatcherTelemetry.ServiceVersion,
            ["host.name"] = _host,
            ["tool.name"] = s.Tool,
            ["session.id"] = s.SessionId,
            ["session.epoch"] = s.Epoch,
            ["state.current"] = s.State.ToString().ToLowerInvariant(),
            ["observed_at"] = s.ObservedAt.ToString("O"),
        };
        if (s.ClosedAt is not null) scope["closed_at"] = s.ClosedAt.Value.ToString("O");
        if (s.ClaudeStatus is not null) scope["claude.status"] = s.ClaudeStatus;
        if (s.Cwd is not null) scope["cwd"] = s.Cwd;
        return scope;
    }
}
