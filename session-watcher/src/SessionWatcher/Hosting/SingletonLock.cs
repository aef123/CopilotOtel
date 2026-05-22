namespace SessionWatcher.Hosting;

/// <summary>
/// Cross-platform single-instance gate. Holds an exclusive file lock on
/// <c>session-watcher.lock</c> for the lifetime of the daemon process. The OS
/// releases the lock when the process exits, so a crashed daemon never blocks
/// the next start.
/// </summary>
public sealed class SingletonLock : IDisposable
{
    private readonly FileStream _stream;
    private readonly string _pidfilePath;

    private SingletonLock(FileStream stream, string pidfilePath)
    {
        _stream = stream;
        _pidfilePath = pidfilePath;
    }

    /// <summary>
    /// Attempts to acquire the singleton lock. Returns a disposable on success,
    /// <c>null</c> if another instance is already holding it.
    /// </summary>
    public static SingletonLock? TryAcquire(string lockFilePath, string pidfilePath)
    {
        var dir = Path.GetDirectoryName(lockFilePath);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

        FileStream stream;
        try
        {
            stream = new FileStream(
                lockFilePath,
                FileMode.OpenOrCreate,
                FileAccess.ReadWrite,
                FileShare.None,                  // exclusive: any other open with overlap fails
                bufferSize: 1,
                FileOptions.None);
        }
        catch (IOException)
        {
            return null;
        }

        // Best-effort: also write a pidfile alongside for observability. The lock
        // is the authority — pidfile is purely informational, used to surface
        // "who's holding the lock" in conflict log messages.
        try
        {
            File.WriteAllText(pidfilePath, Environment.ProcessId.ToString());
        }
        catch (IOException) { /* informational only — don't abort the daemon */ }

        return new SingletonLock(stream, pidfilePath);
    }

    public void Dispose()
    {
        _stream.Dispose();
        try { File.Delete(_pidfilePath); } catch { /* best-effort */ }
    }
}
