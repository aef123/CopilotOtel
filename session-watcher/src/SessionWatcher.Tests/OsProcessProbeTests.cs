using System.Diagnostics;
using SessionWatcher.Diagnostics;

namespace SessionWatcher.Tests;

public class OsProcessProbeTests
{
    [Fact]
    public void IsAlive_CurrentProcess_ReturnsTrue()
    {
        var probe = new OsProcessProbe();
        Assert.True(probe.IsAlive(Environment.ProcessId));
    }

    [Fact]
    public void IsAlive_ImpossiblePid_ReturnsFalse()
    {
        // Pids are bounded; a value beyond any plausible PID space is reliably dead.
        var probe = new OsProcessProbe();
        Assert.False(probe.IsAlive(int.MaxValue));
    }

    [Fact]
    public void IsAlive_NegativeOrZero_ReturnsFalse()
    {
        var probe = new OsProcessProbe();
        Assert.False(probe.IsAlive(0));
        Assert.False(probe.IsAlive(-1));
    }
}
