using SessionWatcher.Diagnostics;

namespace SessionWatcher.Tests;

internal sealed class FakeProcessProbe : IProcessProbe
{
    private readonly HashSet<int> _alive = new();

    public void SetAlive(int pid) => _alive.Add(pid);
    public void SetDead(int pid) => _alive.Remove(pid);

    public bool IsAlive(int pid) => _alive.Contains(pid);
}
