using SessionWatcher.Diagnostics;

namespace SessionWatcher.Tests;

internal sealed class FakeClock : IClock
{
    public DateTimeOffset UtcNow { get; set; } = DateTimeOffset.UnixEpoch.AddYears(56); // ~2026
    public void Advance(TimeSpan by) => UtcNow += by;
}
