using SessionWatcher.Diagnostics;
using SessionWatcher.State;

namespace SessionWatcher.Telemetry;

/// <summary>
/// Plain-text sink useful when running the daemon interactively. Writes each
/// transition + heartbeat to stdout. NOT used in production — the OTel sink is.
/// </summary>
public sealed class ConsoleSink : IEpochEventSink
{
    public void OnTransition(EpochSnapshot snapshot, EpochState from, EpochState to, ShutdownType? shutdown)
    {
        var tail = shutdown is null ? "" : $" shutdown={shutdown}";
        Console.WriteLine(
            $"[{snapshot.ObservedAt:HH:mm:ss}] state {snapshot.Tool}/{Short(snapshot.SessionId)} " +
            $"{from} -> {to}{tail}");
    }

    public void OnHeartbeat(EpochSnapshot snapshot)
    {
        var extra = snapshot.ClaudeStatus is not null ? $" status={snapshot.ClaudeStatus}" : "";
        Console.WriteLine(
            $"[{snapshot.ObservedAt:HH:mm:ss}] hb    {snapshot.Tool}/{Short(snapshot.SessionId)} " +
            $"state={snapshot.State}{extra} pid={snapshot.Pid}");
    }

    public void OnOrphanTimeout(EpochSnapshot snapshot)
    {
        Console.WriteLine(
            $"[{snapshot.ObservedAt:HH:mm:ss}] ORPHAN_TIMEOUT {snapshot.Tool}/{Short(snapshot.SessionId)}");
    }

    private static string Short(string sessionId) =>
        sessionId.Length > 8 ? sessionId[..8] : sessionId;
}
