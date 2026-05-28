using SessionWatcher.Diagnostics;
using SessionWatcher.Sources.Copilot;
using SessionWatcher.State;

namespace SessionWatcher.Tests;

public class CopilotSourceTests : IDisposable
{
    private readonly string _root;
    private readonly FakeProcessProbe _probe = new();
    private readonly RecordingSink _sink = new();

    public CopilotSourceTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "swtest-cp-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); } catch { /* best-effort */ }
    }

    private void CreateSessionDirWithLock(string sessionId, int pid)
    {
        var dir = Path.Combine(_root, sessionId);
        Directory.CreateDirectory(dir);
        File.WriteAllBytes(Path.Combine(dir, $"inuse.{pid}.lock"), Array.Empty<byte>());
    }

    private void RemoveLock(string sessionId, int pid)
    {
        File.Delete(Path.Combine(_root, sessionId, $"inuse.{pid}.lock"));
    }

    private CopilotSource NewSource() => new(_root, _probe);

    [Fact]
    public void PollOnce_LiveLock_EmitsOpeningToLive()
    {
        CreateSessionDirWithLock("abc-123", 555);
        _probe.SetAlive(555);

        var source = NewSource();
        source.PollOnce(_sink);

        var t = Assert.Single(_sink.Transitions);
        Assert.Equal("copilot", t.Tool);
        Assert.Equal("abc-123", t.SessionId);
        Assert.Equal(EpochState.Live, t.To);
    }

    [Fact]
    public void PollOnce_DeadPid_BecomesOrphan()
    {
        CreateSessionDirWithLock("session-z", 7777);
        // 7777 not alive

        NewSource().PollOnce(_sink);

        var t = Assert.Single(_sink.Transitions);
        Assert.Equal(EpochState.Closed, t.To);
    }

    [Fact]
    public void PollOnce_LockVanishesAfterLive_EmitsGracefulEnd()
    {
        CreateSessionDirWithLock("graceful", 100);
        _probe.SetAlive(100);

        var source = NewSource();
        source.PollOnce(_sink);
        RemoveLock("graceful", 100);
        _probe.SetDead(100);
        source.PollOnce(_sink);

        Assert.Equal(2, _sink.Transitions.Count);
        Assert.Equal(EpochState.Ended, _sink.Transitions[1].To);
        Assert.Equal(ShutdownType.Graceful, _sink.Transitions[1].ShutdownType);
    }

    [Fact]
    public void PollOnce_SessionDirWithoutLock_Ignored()
    {
        // Copilot keeps the dir around forever; "no lock" = session not live now.
        Directory.CreateDirectory(Path.Combine(_root, "old-session"));

        NewSource().PollOnce(_sink);

        Assert.Empty(_sink.Transitions);
        Assert.Empty(_sink.Heartbeats);
    }

    [Fact]
    public void PollOnce_NoClaudeStatus_HeartbeatHasNullStatus()
    {
        CreateSessionDirWithLock("plain", 200);
        _probe.SetAlive(200);

        NewSource().PollOnce(_sink);

        var hb = Assert.Single(_sink.Heartbeats);
        Assert.Null(hb.ClaudeStatus);
    }

    [Fact]
    public void PollOnce_PopulatesLastActivityAtFromLockMtime()
    {
        CreateSessionDirWithLock("mtime-sid", 321);
        _probe.SetAlive(321);

        // Force a known mtime on the lock file (well before "now").
        var lockPath = Path.Combine(_root, "mtime-sid", "inuse.321.lock");
        var stableTime = new DateTime(2025, 1, 15, 10, 0, 0, DateTimeKind.Utc);
        File.SetLastWriteTimeUtc(lockPath, stableTime);

        NewSource().PollOnce(_sink);

        var hb = Assert.Single(_sink.Heartbeats);
        Assert.NotNull(hb.LastActivityAt);
        // Filesystem mtime precision varies; allow a small slack.
        Assert.True(Math.Abs((hb.LastActivityAt!.Value.UtcDateTime - stableTime).TotalSeconds) < 2,
            $"expected {stableTime:O}, got {hb.LastActivityAt:O}");
    }
}
