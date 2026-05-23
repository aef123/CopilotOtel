using SessionWatcher.Diagnostics;

namespace SessionWatcher.Tests;

internal sealed class FakeProcessProbe : IProcessProbe
{
    private readonly HashSet<int> _alive = new();
    private readonly Dictionary<int, string> _imageByPid = new();

    public void SetAlive(int pid, string? imageName = null)
    {
        _alive.Add(pid);
        if (imageName is not null) _imageByPid[pid] = imageName;
    }
    public void SetDead(int pid)
    {
        _alive.Remove(pid);
        _imageByPid.Remove(pid);
    }

    public bool IsAlive(int pid, IReadOnlyList<string>? allowedImageNames = null)
    {
        if (!_alive.Contains(pid)) return false;
        if (allowedImageNames is null or { Count: 0 }) return true;
        if (!_imageByPid.TryGetValue(pid, out var actual)) return true;
        foreach (var n in allowedImageNames)
        {
            var stripped = n.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) ? n[..^4] : n;
            if (string.Equals(stripped, actual, StringComparison.OrdinalIgnoreCase)) return true;
        }
        return false;
    }
}
