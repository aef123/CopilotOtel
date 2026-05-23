using SessionWatcher.Diagnostics;
using SessionWatcher.State;

namespace SessionWatcher.Tests;

internal sealed class RecordingSink : IEpochEventSink
{
    public List<RecordedTransition> Transitions { get; } = new();
    public List<RecordedHeartbeat> Heartbeats { get; } = new();
    public List<RecordedOrphanTimeout> OrphanTimeouts { get; } = new();

    public void OnTransition(EpochSnapshot snapshot, EpochState from, EpochState to, ShutdownType? shutdown) =>
        Transitions.Add(new RecordedTransition(
            Tool: snapshot.Tool,
            SessionId: snapshot.SessionId,
            From: from,
            To: to,
            ShutdownType: shutdown));

    public void OnHeartbeat(EpochSnapshot snapshot) =>
        Heartbeats.Add(new RecordedHeartbeat(
            Tool: snapshot.Tool,
            SessionId: snapshot.SessionId,
            State: snapshot.State,
            ClaudeStatus: snapshot.ClaudeStatus));

    public void OnOrphanTimeout(EpochSnapshot snapshot) =>
        OrphanTimeouts.Add(new RecordedOrphanTimeout(
            Tool: snapshot.Tool,
            SessionId: snapshot.SessionId));
}

internal sealed record RecordedTransition(
    string Tool, string SessionId, EpochState From, EpochState To, ShutdownType? ShutdownType);

internal sealed record RecordedHeartbeat(
    string Tool, string SessionId, EpochState State, string? ClaudeStatus);

internal sealed record RecordedOrphanTimeout(string Tool, string SessionId);
