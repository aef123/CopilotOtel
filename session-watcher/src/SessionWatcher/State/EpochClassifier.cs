namespace SessionWatcher.State;

public enum EpochState
{
    /// <summary>Initial state — daemon has discovered a pidfile/lock but hasn't yet validated it.</summary>
    Opening,
    /// <summary>Pidfile/lock present and owning PID alive (image validation passed).</summary>
    Live,
    /// <summary>Pidfile/lock present but owning PID dead or image mismatch.</summary>
    Orphan,
    /// <summary>Epoch closed. Terminal.</summary>
    Ended,
}

public enum ShutdownType
{
    /// <summary>Pidfile/lock removed by its owner; PID exited cleanly.</summary>
    Graceful,
    /// <summary>Pidfile/lock present when PID died; classifier waited and pidfile eventually vanished.</summary>
    Crash,
}

/// <summary>
/// Observation passed to the classifier each tick. The caller (a source watcher)
/// is responsible for image validation, PID-reuse detection, etc. — the
/// classifier consumes only the boolean outcomes.
/// </summary>
/// <param name="PidfilePresent">True if the pidfile/lock file exists on disk at observation time.</param>
/// <param name="PidAlive">True if the owning process exists AND image+lock-authority checks passed.</param>
public readonly record struct Observation(bool PidfilePresent, bool PidAlive);

public readonly record struct ClassificationResult(
    EpochState NewState,
    bool Transitioned,
    ShutdownType? ShutdownType);

public static class EpochClassifier
{
    public static ClassificationResult Classify(EpochState previous, Observation observation)
    {
        var next = NextState(previous, observation);
        if (next == previous)
            return new ClassificationResult(next, Transitioned: false, ShutdownType: null);

        ShutdownType? shutdown = next == EpochState.Ended
            ? (previous == EpochState.Orphan ? State.ShutdownType.Crash : State.ShutdownType.Graceful)
            : null;

        return new ClassificationResult(next, Transitioned: true, ShutdownType: shutdown);
    }

    private static EpochState NextState(EpochState previous, Observation observation) => previous switch
    {
        EpochState.Ended => EpochState.Ended,
        _ when !observation.PidfilePresent => EpochState.Ended,
        _ when observation.PidAlive => EpochState.Live,
        _ => EpochState.Orphan,
    };
}
