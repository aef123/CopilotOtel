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

    [Fact]
    public void IsAlive_AllowedImageMatchesActual_ReturnsTrue()
    {
        // The test host is `testhost` on .NET Core / dotnet test.
        var probe = new OsProcessProbe();
        var actualName = Process.GetCurrentProcess().ProcessName;
        Assert.True(probe.IsAlive(Environment.ProcessId, new[] { actualName, "made-up" }));
    }

    [Fact]
    public void IsAlive_AllowedImageMismatch_ReturnsFalse()
    {
        var probe = new OsProcessProbe();
        Assert.False(probe.IsAlive(Environment.ProcessId, new[] { "definitely-not-this-process" }));
    }

    [Fact]
    public void IsAlive_AllowedImageWithExeSuffix_StillMatches()
    {
        var probe = new OsProcessProbe();
        var actualName = Process.GetCurrentProcess().ProcessName;
        Assert.True(probe.IsAlive(Environment.ProcessId, new[] { actualName + ".exe" }));
    }

    [Fact]
    public void IsAlive_AccessDeniedPid_ReturnsFalse()
    {
        // PID 4 is the Windows kernel "System" process. Process.GetProcessById(4)
        // returns a Process object, but HasExited/ProcessName both throw
        // Win32Exception(ERROR_ACCESS_DENIED=5) for non-admin callers. The probe
        // must swallow that and report "not our process" rather than crashing the
        // poll loop. Regression test for the Copilot source poll failure observed
        // in the wild on stale lockfiles whose PIDs had been recycled by a
        // protected process.
        if (!OperatingSystem.IsWindows()) return;
        var probe = new OsProcessProbe();
        Assert.False(probe.IsAlive(4, new[] { "copilot", "claude" }));
        Assert.False(probe.IsAlive(4));
    }
}
