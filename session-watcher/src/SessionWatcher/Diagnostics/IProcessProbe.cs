namespace SessionWatcher.Diagnostics;

/// <summary>
/// Abstraction over OS-level process inspection. Tests inject a fake;
/// production uses <see cref="OsProcessProbe"/>.
/// </summary>
public interface IProcessProbe
{
    /// <summary>True if a process with the given PID currently exists.</summary>
    bool IsAlive(int pid);
}
