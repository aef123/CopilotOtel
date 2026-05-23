using SessionWatcher.Diagnostics;
using SessionWatcher.State;

namespace SessionWatcher.Sources.Copilot;

/// <summary>
/// Watches <c>%USERPROFILE%\.copilot\session-state\&lt;sid&gt;\</c> for the
/// presence of <c>inuse.&lt;pid&gt;.lock</c>. Lock present + PID alive = live
/// session. Unlike Claude's pidfile, the lock body carries nothing — PID lives
/// in the filename, session ID is the parent directory name.
/// </summary>
public sealed class CopilotSource
{
    private static readonly IReadOnlyList<string> CopilotImages =
        new[] { "copilot", "copilot.exe", "agency", "agency.exe" };

    private readonly string _sessionStateRoot;
    private readonly IProcessProbe _probe;
    private readonly IClock _clock;
    private readonly TimeSpan _orphanTimeout;
    private readonly Dictionary<string, Tracker> _epochs = new(StringComparer.Ordinal);
    private readonly string _host = Environment.MachineName;

    public CopilotSource(
        string sessionStateRoot,
        IProcessProbe probe,
        IClock? clock = null,
        TimeSpan? orphanTimeout = null)
    {
        _sessionStateRoot = sessionStateRoot;
        _probe = probe;
        _clock = clock ?? new SystemClock();
        _orphanTimeout = orphanTimeout ?? TimeSpan.FromMinutes(5);
    }

    public void PollOnce(IEpochEventSink sink)
    {
        var observedAt = _clock.UtcNow;
        var seenSessions = new HashSet<string>(StringComparer.Ordinal);

        foreach (var (sessionId, pid) in EnumerateLiveLocks())
        {
            seenSessions.Add(sessionId);
            var tracker = GetOrCreateTracker(sessionId, pid);
            var alive = _probe.IsAlive(pid, CopilotImages);
            ApplyObservation(tracker, lockPresent: true, alive, observedAt, sink);
        }

        var vanished = _epochs.Values.Where(t => !seenSessions.Contains(t.SessionId)).ToList();
        foreach (var tracker in vanished)
        {
            if (tracker.LastState == EpochState.Ended) continue;
            ApplyObservation(tracker, lockPresent: false, alive: false, observedAt, sink);
        }
    }

    private IEnumerable<(string SessionId, int Pid)> EnumerateLiveLocks()
    {
        if (!Directory.Exists(_sessionStateRoot)) yield break;
        foreach (var dir in Directory.EnumerateDirectories(_sessionStateRoot))
        {
            var sessionId = Path.GetFileName(dir);
            if (string.IsNullOrEmpty(sessionId)) continue;

            string[] locks;
            try { locks = Directory.GetFiles(dir, "inuse.*.lock"); }
            catch (IOException) { continue; }
            catch (UnauthorizedAccessException) { continue; }

            foreach (var lockPath in locks)
            {
                if (CopilotLockParser.TryParsePid(lockPath, out var pid))
                {
                    yield return (sessionId, pid);
                    break; // one lock per session is the normal case
                }
            }
        }
    }

    private Tracker GetOrCreateTracker(string sessionId, int pid)
    {
        if (!_epochs.TryGetValue(sessionId, out var tracker))
        {
            tracker = new Tracker(sessionId, pid);
            _epochs[sessionId] = tracker;
        }
        return tracker;
    }

    private void ApplyObservation(
        Tracker tracker,
        bool lockPresent,
        bool alive,
        DateTimeOffset observedAt,
        IEpochEventSink sink)
    {
        var snapshot = new EpochSnapshot(
            Tool: "copilot",
            SessionId: tracker.SessionId,
            Pid: tracker.Pid,
            Epoch: tracker.EpochIndex,
            Host: _host,
            State: tracker.LastState,
            ObservedAt: observedAt);

        var result = EpochClassifier.Classify(
            tracker.LastState,
            new Observation(PidfilePresent: lockPresent, PidAlive: alive));

        snapshot = snapshot with { State = result.NewState };

        if (result.Transitioned)
        {
            sink.OnTransition(snapshot, tracker.LastState, result.NewState, result.ShutdownType);

            if (result.NewState == EpochState.Orphan && tracker.OrphanFirstSeenAt is null)
            {
                tracker.OrphanFirstSeenAt = observedAt;
                tracker.OrphanTimedOut = false;
            }
            else if (result.NewState != EpochState.Orphan)
            {
                tracker.OrphanFirstSeenAt = null;
                tracker.OrphanTimedOut = false;
            }

            tracker.LastState = result.NewState;
        }

        if (result.NewState == EpochState.Orphan
            && !tracker.OrphanTimedOut
            && tracker.OrphanFirstSeenAt is { } firstSeen
            && observedAt - firstSeen >= _orphanTimeout)
        {
            sink.OnOrphanTimeout(snapshot);
            tracker.OrphanTimedOut = true;
        }

        if (result.NewState is EpochState.Live or EpochState.Orphan)
        {
            sink.OnHeartbeat(snapshot);
        }
    }

    private sealed class Tracker
    {
        public string SessionId { get; }
        public int Pid { get; }
        public int EpochIndex { get; init; } = 1;
        public EpochState LastState { get; set; } = EpochState.Opening;
        public DateTimeOffset? OrphanFirstSeenAt { get; set; }
        public bool OrphanTimedOut { get; set; }

        public Tracker(string sessionId, int pid) { SessionId = sessionId; Pid = pid; }
    }
}
