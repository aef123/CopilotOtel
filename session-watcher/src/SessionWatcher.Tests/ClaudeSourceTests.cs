using SessionWatcher.Diagnostics;
using SessionWatcher.Sources.Claude;
using SessionWatcher.State;

namespace SessionWatcher.Tests;

public class ClaudeSourceTests : IDisposable
{
    private readonly string _dir;
    private readonly FakeProcessProbe _probe = new();
    private readonly RecordingSink _sink = new();

    public ClaudeSourceTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "swtest-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_dir);
    }

    public void Dispose()
    {
        try { Directory.Delete(_dir, recursive: true); } catch { /* best-effort */ }
    }

    private void WritePidfile(int pid, string sessionId, string status = "busy")
    {
        var path = Path.Combine(_dir, $"{pid}.json");
        var startedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - 60_000;
        var json = $$"""
            {"pid":{{pid}},"sessionId":"{{sessionId}}","cwd":"c:\\test","startedAt":{{startedMs}},"version":"2.1.147","peerProtocol":1,"kind":"interactive","entrypoint":"cli","status":"{{status}}","updatedAt":{{startedMs}}}
            """;
        File.WriteAllText(path, json);
    }

    private ClaudeSource NewSource() => new(_dir, _probe);

    [Fact]
    public void PollOnce_NewLivePidfile_EmitsOpeningToLiveTransition()
    {
        WritePidfile(pid: 38112, sessionId: "session-A");
        _probe.SetAlive(38112);

        var source = NewSource();
        source.PollOnce(_sink);

        var t = Assert.Single(_sink.Transitions);
        Assert.Equal("claude", t.Tool);
        Assert.Equal("session-A", t.SessionId);
        Assert.Equal(EpochState.Opening, t.From);
        Assert.Equal(EpochState.Live, t.To);
        Assert.Null(t.ShutdownType);
    }

    [Fact]
    public void PollOnce_DeadPid_EmitsOpeningToOrphanTransition()
    {
        WritePidfile(pid: 99999, sessionId: "session-B");
        // PID 99999 deliberately not registered as alive

        var source = NewSource();
        source.PollOnce(_sink);

        var t = Assert.Single(_sink.Transitions);
        Assert.Equal(EpochState.Orphan, t.To);
    }

    [Fact]
    public void PollOnce_PidfileGoneAfterLive_EmitsGracefulEnd()
    {
        WritePidfile(pid: 100, sessionId: "session-C");
        _probe.SetAlive(100);

        var source = NewSource();
        source.PollOnce(_sink);  // tick 1: Live
        Assert.Single(_sink.Transitions);

        // simulate graceful exit
        File.Delete(Path.Combine(_dir, "100.json"));
        _probe.SetDead(100);

        source.PollOnce(_sink);  // tick 2: Ended-graceful

        Assert.Equal(2, _sink.Transitions.Count);
        Assert.Equal(EpochState.Ended, _sink.Transitions[1].To);
        Assert.Equal(ShutdownType.Graceful, _sink.Transitions[1].ShutdownType);
    }

    [Fact]
    public void PollOnce_PidDiesThenPidfileGone_EmitsCrash()
    {
        WritePidfile(pid: 200, sessionId: "session-D");
        _probe.SetAlive(200);

        var source = NewSource();
        source.PollOnce(_sink);                  // Live
        _probe.SetDead(200);
        source.PollOnce(_sink);                  // Live → Orphan
        File.Delete(Path.Combine(_dir, "200.json"));
        source.PollOnce(_sink);                  // Orphan → Ended(crash)

        Assert.Equal(3, _sink.Transitions.Count);
        Assert.Equal(EpochState.Live, _sink.Transitions[0].To);
        Assert.Equal(EpochState.Orphan, _sink.Transitions[1].To);
        Assert.Equal(EpochState.Ended, _sink.Transitions[2].To);
        Assert.Equal(ShutdownType.Crash, _sink.Transitions[2].ShutdownType);
    }

    [Fact]
    public void PollOnce_StableLive_NoExtraTransitions_EmitsHeartbeat()
    {
        WritePidfile(pid: 300, sessionId: "session-E");
        _probe.SetAlive(300);

        var source = NewSource();
        source.PollOnce(_sink);
        source.PollOnce(_sink);
        source.PollOnce(_sink);

        // Exactly one Opening→Live transition
        Assert.Single(_sink.Transitions);
        // Every tick where state is Live or Orphan should produce a heartbeat
        Assert.Equal(3, _sink.Heartbeats.Count);
        Assert.All(_sink.Heartbeats, h => Assert.Equal("session-E", h.SessionId));
    }

    [Fact]
    public void PollOnce_StatusBusy_CarriedThroughOnHeartbeat()
    {
        WritePidfile(pid: 400, sessionId: "session-F", status: "busy");
        _probe.SetAlive(400);

        var source = NewSource();
        source.PollOnce(_sink);

        var hb = Assert.Single(_sink.Heartbeats);
        Assert.Equal("busy", hb.ClaudeStatus);
    }

    [Fact]
    public void PollOnce_TwoLivePidfiles_TracksBothIndependently()
    {
        WritePidfile(pid: 500, sessionId: "session-G");
        WritePidfile(pid: 501, sessionId: "session-H");
        _probe.SetAlive(500);
        _probe.SetAlive(501);

        var source = NewSource();
        source.PollOnce(_sink);

        Assert.Equal(2, _sink.Transitions.Count);
        Assert.Equal(new[] { "session-G", "session-H" }, _sink.Transitions.Select(t => t.SessionId).OrderBy(s => s));
    }
}
