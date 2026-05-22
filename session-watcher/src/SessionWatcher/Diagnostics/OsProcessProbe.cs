using System.Diagnostics;

namespace SessionWatcher.Diagnostics;

/// <summary>
/// Production process probe. Uses <see cref="Process.GetProcessById(int)"/>;
/// catches the ArgumentException that .NET throws when the PID doesn't exist.
/// </summary>
public sealed class OsProcessProbe : IProcessProbe
{
    public bool IsAlive(int pid)
    {
        if (pid <= 0) return false;
        try
        {
            using var p = Process.GetProcessById(pid);
            // p.HasExited can throw on a zombie / access-denied process; treat any throw as "dead".
            return !p.HasExited;
        }
        catch (ArgumentException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }
}
