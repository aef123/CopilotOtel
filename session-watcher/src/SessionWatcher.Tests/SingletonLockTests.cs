using SessionWatcher.Hosting;

namespace SessionWatcher.Tests;

public class SingletonLockTests : IDisposable
{
    private readonly string _dir;

    public SingletonLockTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "swlock-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_dir);
    }

    public void Dispose()
    {
        try { Directory.Delete(_dir, recursive: true); } catch { /* best-effort */ }
    }

    private string LockPath => Path.Combine(_dir, "session-watcher.lock");
    private string PidfilePath => Path.Combine(_dir, "pidfile.txt");

    [Fact]
    public void TryAcquire_NoExistingHolder_Succeeds()
    {
        using var lk = SingletonLock.TryAcquire(LockPath, PidfilePath);
        Assert.NotNull(lk);
    }

    [Fact]
    public void TryAcquire_AlreadyHeld_ReturnsNull()
    {
        using var first = SingletonLock.TryAcquire(LockPath, PidfilePath);
        Assert.NotNull(first);

        using var second = SingletonLock.TryAcquire(LockPath, PidfilePath);
        Assert.Null(second);
    }

    [Fact]
    public void TryAcquire_AfterRelease_Succeeds()
    {
        var first = SingletonLock.TryAcquire(LockPath, PidfilePath);
        Assert.NotNull(first);
        first.Dispose();

        using var second = SingletonLock.TryAcquire(LockPath, PidfilePath);
        Assert.NotNull(second);
    }

    [Fact]
    public void TryAcquire_WritesPidfile_WithCurrentProcessId()
    {
        using var lk = SingletonLock.TryAcquire(LockPath, PidfilePath);
        Assert.NotNull(lk);

        var contents = File.ReadAllText(PidfilePath).Trim();
        Assert.Equal(Environment.ProcessId.ToString(), contents);
    }
}
