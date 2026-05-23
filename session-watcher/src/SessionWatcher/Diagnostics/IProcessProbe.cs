namespace SessionWatcher.Diagnostics;

/// <summary>
/// Abstraction over OS-level process inspection. Tests inject a fake;
/// production uses <see cref="OsProcessProbe"/>.
/// </summary>
public interface IProcessProbe
{
    /// <summary>True if a process with the given PID currently exists AND, when
    /// <paramref name="allowedImageNames"/> is non-empty, its base process name
    /// matches one of them (case-insensitive). Image-name validation closes the
    /// PID-reuse blind spot: a recycled PID owned by a different program is
    /// reported as not-alive from the daemon's perspective.</summary>
    bool IsAlive(int pid, IReadOnlyList<string>? allowedImageNames = null);
}
