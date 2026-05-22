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
    private readonly string _sessionsDir;
    private readonly IProcessProbe _probe;
    private readonly Dictionary<string, Tracker> _epochs = new(StringComparer.Ordinal);
    private readonly string _host = Environment.MachineName;

    public ClaudeSource(string sessionsDir, IProcessProbe probe)
    {
        _sessionsDir = sessionsDir;
        _probe = probe;
    }

    public void PollOnce(IEpochEventSink sink)
    {
        var observedAt = DateTimeOffset.UtcNow;
        var seenSessionIds = new HashSet<string>(StringComparer.Ordinal);

        var pidfiles = EnumeratePidfiles();
        foreach (var (path, pidfile) in pidfiles)
        {
            seenSessionIds.Add(pidfile.SessionId);
            var tracker = GetOrCreateTracker(pidfile, path);
            var alive = _probe.IsAlive(pidfile.Pid);
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

    private IEnumerable<(string Path, ClaudePidfile Pidfile)> EnumeratePidfiles()
    {
        if (!Directory.Exists(_sessionsDir)) yield break;
        foreach (var path in Directory.EnumerateFiles(_sessionsDir, "*.json"))
        {
            string text;
            try { text = File.ReadAllText(path); }
            catch (IOException) { continue; }
            catch (UnauthorizedAccessException) { continue; }

            var parsed = ClaudePidfile.Parse(text);
            if (parsed is not null) yield return (path, parsed);
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

        snapshot = snapshot with { State = result.NewState };

        if (result.Transitioned)
        {
            sink.OnTransition(snapshot, tracker.LastState, result.NewState, result.ShutdownType);
            tracker.LastState = result.NewState;
            tracker.LastSnapshot = snapshot;
        }

        if (result.NewState is EpochState.Live or EpochState.Orphan)
        {
            sink.OnHeartbeat(snapshot);
            tracker.LastSnapshot = snapshot;
        }
    }

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
                ClaudeStatus: pidfile.Status,
                ClaudeKind: pidfile.Kind,
                ClaudeEntrypoint: pidfile.Entrypoint);
        }

        // Pidfile gone — carry forward what we last knew.
        var prev = tracker.LastSnapshot;
        return prev is null
            ? new EpochSnapshot("claude", tracker.SessionId, tracker.Pid, tracker.EpochIndex, _host, placeholderState, at)
            : prev with { State = placeholderState, ObservedAt = at };
    }

    private sealed class Tracker
    {
        public string SessionId { get; }
        public int Pid { get; }
        public string PidfilePath { get; }
        public int EpochIndex { get; init; } = 1;

        public EpochState LastState { get; set; } = EpochState.Opening;
        public EpochSnapshot? LastSnapshot { get; set; }

        public Tracker(string sessionId, int pid, string pidfilePath)
        {
            SessionId = sessionId;
            Pid = pid;
            PidfilePath = pidfilePath;
        }
    }
}
