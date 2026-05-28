using System.ComponentModel;
using System.Diagnostics;

namespace SessionWatcher.Diagnostics;

/// <summary>
/// Production process probe. Uses <see cref="Process.GetProcessById(int)"/>;
/// catches the ArgumentException that .NET throws when the PID doesn't exist.
/// </summary>
public sealed class OsProcessProbe : IProcessProbe
{
    public bool IsAlive(int pid, IReadOnlyList<string>? allowedImageNames = null)
    {
        if (pid <= 0) return false;
        Process? p = null;
        try
        {
            p = Process.GetProcessById(pid);
            // p.HasExited and p.ProcessName both call OpenProcess under the hood and can
            // throw Win32Exception(ERROR_ACCESS_DENIED=5) when the PID has been recycled
            // by a process the current user can't query (SYSTEM, services, protected
            // processes). That means it's NOT our Copilot/Claude process — treat as dead.
            if (p.HasExited) return false;

            if (allowedImageNames is { Count: > 0 })
            {
                // Process.ProcessName returns the executable base name without extension
                // (e.g. "claude" for "claude.exe"). Strip extensions from the allowlist
                // when comparing so callers can pass either form.
                var actual = p.ProcessName;
                foreach (var allowed in allowedImageNames)
                {
                    if (string.Equals(StripExe(allowed), actual, StringComparison.OrdinalIgnoreCase))
                        return true;
                }
                return false;
            }
            return true;
        }
        catch (ArgumentException) { return false; }
        catch (InvalidOperationException) { return false; }
        catch (Win32Exception) { return false; }
        finally
        {
            p?.Dispose();
        }
    }

    private static string StripExe(string name) =>
        name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
            ? name[..^4]
            : name;
}
