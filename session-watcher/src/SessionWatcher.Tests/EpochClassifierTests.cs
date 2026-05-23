using SessionWatcher.State;

namespace SessionWatcher.Tests;

public class EpochClassifierTests
{
    [Fact]
    public void Opening_PidfilePresentAndPidAlive_BecomesLive()
    {
        var result = EpochClassifier.Classify(
            previous: EpochState.Opening,
            observation: new Observation(PidfilePresent: true, PidAlive: true));

        Assert.Equal(EpochState.Live, result.NewState);
        Assert.True(result.Transitioned);
        Assert.Null(result.ShutdownType);
    }

    [Fact]
    public void Opening_PidfilePresentButPidDead_BecomesOrphan()
    {
        var result = EpochClassifier.Classify(
            previous: EpochState.Opening,
            observation: new Observation(PidfilePresent: true, PidAlive: false));

        Assert.Equal(EpochState.Closed, result.NewState);
        Assert.True(result.Transitioned);
        Assert.Null(result.ShutdownType);
    }

    [Fact]
    public void Live_StaysLive_WhenPidfilePresentAndPidAlive()
    {
        var result = EpochClassifier.Classify(
            previous: EpochState.Live,
            observation: new Observation(PidfilePresent: true, PidAlive: true));

        Assert.Equal(EpochState.Live, result.NewState);
        Assert.False(result.Transitioned);
    }

    [Fact]
    public void Live_BecomesOrphan_WhenPidDies_PidfileStillPresent()
    {
        var result = EpochClassifier.Classify(
            previous: EpochState.Live,
            observation: new Observation(PidfilePresent: true, PidAlive: false));

        Assert.Equal(EpochState.Closed, result.NewState);
        Assert.True(result.Transitioned);
        Assert.Null(result.ShutdownType);
    }

    [Fact]
    public void Live_EndsGracefully_WhenPidfileVanishes()
    {
        var result = EpochClassifier.Classify(
            previous: EpochState.Live,
            observation: new Observation(PidfilePresent: false, PidAlive: false));

        Assert.Equal(EpochState.Ended, result.NewState);
        Assert.True(result.Transitioned);
        Assert.Equal(ShutdownType.Graceful, result.ShutdownType);
    }

    [Fact]
    public void Orphan_EndsAsCrash_WhenPidfileVanishes()
    {
        var result = EpochClassifier.Classify(
            previous: EpochState.Closed,
            observation: new Observation(PidfilePresent: false, PidAlive: false));

        Assert.Equal(EpochState.Ended, result.NewState);
        Assert.True(result.Transitioned);
        Assert.Equal(ShutdownType.Crash, result.ShutdownType);
    }

    [Fact]
    public void Orphan_RecoversToLive_WhenPidResurrected()
    {
        // Pid reuse on Windows is real. The classifier reports a recovery; lock-authority
        // checks live one layer up and would already have decided "image mismatch =
        // still orphan" before the classifier ever sees PidAlive=true here.
        var result = EpochClassifier.Classify(
            previous: EpochState.Closed,
            observation: new Observation(PidfilePresent: true, PidAlive: true));

        Assert.Equal(EpochState.Live, result.NewState);
        Assert.True(result.Transitioned);
    }

    [Fact]
    public void Ended_IsTerminal_StaysEnded()
    {
        // Once a transition emits Ended, the caller should drop the tracker.
        // If somehow another tick fires, we don't oscillate back.
        var result = EpochClassifier.Classify(
            previous: EpochState.Ended,
            observation: new Observation(PidfilePresent: true, PidAlive: true));

        Assert.Equal(EpochState.Ended, result.NewState);
        Assert.False(result.Transitioned);
    }
}
