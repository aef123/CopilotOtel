using SessionWatcher.Diagnostics;
using SessionWatcher.State;

namespace SessionWatcher.Sources.Claude;

/// <summary>
/// Watches <c>%USERPROFILE%\.claude\sessions\</c> for per-process pidfiles
/// (<c>&lt;pid&gt;.json</c>). One pidfile = one live Claude Code process; its
/// presence is the daemon's authoritative "live" signal.
/// </summary>
public sealed class ClaudeSource
{
    private static readonly IReadOnlyList<string> ClaudeImages = new[] { "claude", "claude.exe" };

    private readonly string _sessionsDir;
    private readonly IProcessProbe _probe;
    private readonly IClock _clock;
    private readonly TimeSpan _orphanTimeout;
    private readonly Dictionary<string, Tracker> _epochs = new(StringComparer.Ordinal);
    private readonly string _host = Environment.MachineName;

    public ClaudeSource(
        string sessionsDir,
        IProcessProbe probe,
        IClock? clock = null,
        TimeSpan? orphanTimeout = null)
    {
        _sessionsDir = sessionsDir;
        _probe = probe;
        _clock = clock ?? new SystemClock();
        _orphanTimeout = orphanTimeout ?? TimeSpan.FromMinutes(5);
    }

    public void PollOnce(IEpochEventSink sink)
    {
        var observedAt = _clock.UtcNow;
        var seenSessionIds = new HashSet<string>(StringComparer.Ordinal);

        var pidfiles = EnumeratePidfiles();
        foreach (var (path, pidfile, mtime) in pidfiles)
        {
            seenSessionIds.Add(pidfile.SessionId);
            var tracker = GetOrCreateTracker(pidfile, path);
            tracker.LastActivityAt = mtime;
            var alive = _probe.IsAlive(pidfile.Pid, ClaudeImages);
            ApplyObservation(tracker, pidfile, alive, observedAt, sink);
        }

        // Epochs we tracked previously but didn't see this tick: pidfile vanished.
        var vanished = _epochs.Values.Where(t => !seenSessionIds.Contains(t.SessionId)).ToList();
        foreach (var tracker in vanished)
        {
            if (tracker.LastState == EpochState.Ended) continue;
            ApplyObservation(tracker, pidfile: null, alive: false, observedAt, sink);
        }
    }

    private IEnumerable<(string Path, ClaudePidfile Pidfile, DateTimeOffset Mtime)> EnumeratePidfiles()
    {
        if (!Directory.Exists(_sessionsDir)) yield break;
        foreach (var path in Directory.EnumerateFiles(_sessionsDir, "*.json"))
        {
            string text;
            DateTimeOffset mtime;
            try
            {
                text = File.ReadAllText(path);
                mtime = new DateTimeOffset(File.GetLastWriteTimeUtc(path), TimeSpan.Zero);
            }
            catch (IOException) { continue; }
            catch (UnauthorizedAccessException) { continue; }

            var parsed = ClaudePidfile.Parse(text);
            if (parsed is not null) yield return (path, parsed, mtime);
        }
    }

    private Tracker GetOrCreateTracker(ClaudePidfile pidfile, string path)
    {
        if (!_epochs.TryGetValue(pidfile.SessionId, out var tracker))
        {
            tracker = new Tracker(pidfile.SessionId, pidfile.Pid, path);
            _epochs[pidfile.SessionId] = tracker;
        }
        return tracker;
    }

    private void ApplyObservation(
        Tracker tracker,
        ClaudePidfile? pidfile,
        bool alive,
        DateTimeOffset observedAt,
        IEpochEventSink sink)
    {
        var snapshot = BuildSnapshot(tracker, pidfile, observedAt, tracker.LastState);
        var result = EpochClassifier.Classify(
            tracker.LastState,
            new Observation(PidfilePresent: pidfile is not null, PidAlive: alive));

        // Refine Live → Active/Idle using the Claude pidfile's status hint.
        var refinedState = RefineFromStatus(result.NewState, pidfile?.Status);

        snapshot = snapshot with { State = refinedState };

        // Compare with previous *refined* state so a busy→idle transition still counts.
        var transitioned = refinedState != tracker.LastState;
        if (transitioned)
        {
            sink.OnTransition(snapshot, tracker.LastState, refinedState, result.ShutdownType);

            if (refinedState == EpochState.Closed && tracker.OrphanFirstSeenAt is null)
            {
                tracker.OrphanFirstSeenAt = observedAt;
                tracker.OrphanTimedOut = false;
            }
            else if (refinedState != EpochState.Closed)
            {
                tracker.OrphanFirstSeenAt = null;
                tracker.OrphanTimedOut = false;
            }

            tracker.LastState = refinedState;
            tracker.LastSnapshot = snapshot;
        }

        // Fire orphan-timeout once if the epoch has been Orphan long enough.
        if (refinedState == EpochState.Closed
            && !tracker.OrphanTimedOut
            && tracker.OrphanFirstSeenAt is { } firstSeen
            && observedAt - firstSeen >= _orphanTimeout)
        {
            sink.OnOrphanTimeout(snapshot);
            tracker.OrphanTimedOut = true;
        }

        if (refinedState is EpochState.Live or EpochState.Active or EpochState.Idle or EpochState.Closed)
        {
            sink.OnHeartbeat(snapshot);
            tracker.LastSnapshot = snapshot;
        }
    }

    private static EpochState RefineFromStatus(EpochState classified, string? status) =>
        classified == EpochState.Live
            ? (status?.ToLowerInvariant() switch
            {
                "busy" => EpochState.Active,
                "idle" => EpochState.Idle,
                _ => EpochState.Live,
            })
            : classified;

    private EpochSnapshot BuildSnapshot(Tracker tracker, ClaudePidfile? pidfile, DateTimeOffset at, EpochState placeholderState)
    {
        if (pidfile is not null)
        {
            return new EpochSnapshot(
                Tool: "claude",
                SessionId: pidfile.SessionId,
                Pid: pidfile.Pid,
                Epoch: tracker.EpochIndex,
                Host: _host,
                State: placeholderState,
                ObservedAt: at,
                Cwd: pidfile.Cwd,
                Version: pidfile.Version,
                StartedAt: pidfile.StartedAt,
                LastActivityAt: tracker.LastActivityAt,
                ClaudeStatus: pidfile.Status,
                ClaudeKind: pidfile.Kind,
                ClaudeEntrypoint: pidfile.Entrypoint);
        }

        // Pidfile gone — carry forward what we last knew.
        var prev = tracker.LastSnapshot;
        return prev is null
            ? new EpochSnapshot("claude", tracker.SessionId, tracker.Pid, tracker.EpochIndex, _host, placeholderState, at, LastActivityAt: tracker.LastActivityAt)
            : prev with { State = placeholderState, ObservedAt = at, LastActivityAt = tracker.LastActivityAt ?? prev.LastActivityAt };
    }

    private sealed class Tracker
    {
        public string SessionId { get; }
        public int Pid { get; }
        public string PidfilePath { get; }
        public int EpochIndex { get; init; } = 1;

        public EpochState LastState { get; set; } = EpochState.Opening;
        public EpochSnapshot? LastSnapshot { get; set; }
        public DateTimeOffset? OrphanFirstSeenAt { get; set; }
        public bool OrphanTimedOut { get; set; }
        public DateTimeOffset? LastActivityAt { get; set; }

        public Tracker(string sessionId, int pid, string pidfilePath)
        {
            SessionId = sessionId;
            Pid = pid;
            PidfilePath = pidfilePath;
        }
    }
}
