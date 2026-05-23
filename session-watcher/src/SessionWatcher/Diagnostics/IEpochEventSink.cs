using SessionWatcher.State;

namespace SessionWatcher.Diagnostics;

/// <summary>
/// Where source watchers send their findings. Production wires this to the
/// OTel logs/metrics/traces pipeline; tests use a recording fake.
/// </summary>
public interface IEpochEventSink
{
    /// <summary>State changed for this epoch. <paramref name="from"/> is
    /// <see cref="EpochState.Opening"/> on the first observation.</summary>
    void OnTransition(EpochSnapshot snapshot, EpochState from, EpochState to, ShutdownType? shutdown);

    /// <summary>Periodic heartbeat for a live or orphan epoch (skipped for Ended).</summary>
    void OnHeartbeat(EpochSnapshot snapshot);

    /// <summary>Fires exactly once per epoch when it has been in Orphan for the
    /// configured timeout. The epoch stays in Orphan for visibility, but stops
    /// contributing to the orphan gauge from this point on.</summary>
    void OnOrphanTimeout(EpochSnapshot snapshot);
}
