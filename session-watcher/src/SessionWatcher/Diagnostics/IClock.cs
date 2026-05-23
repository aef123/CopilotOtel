namespace SessionWatcher.Diagnostics;

/// <summary>Time abstraction. Production uses <see cref="SystemClock"/>; tests fake it.</summary>
public interface IClock
{
    DateTimeOffset UtcNow { get; }
}

public sealed class SystemClock : IClock
{
    public DateTimeOffset UtcNow => DateTimeOffset.UtcNow;
}
