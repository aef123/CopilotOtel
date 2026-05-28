namespace SessionWatcher.Telemetry;

/// <summary>
/// Resolves the friendly host name the daemon should advertise as
/// <c>host.name</c>. Honors <c>OTEL_RESOURCE_ATTRIBUTES</c>'s <c>host.name</c>
/// key when present so users can override the OS-assigned machine name with a
/// memorable label (e.g. <c>afaust-datadev2</c> instead of
/// <c>CPC-afaus-SQYBG</c>). Falls back to <see cref="Environment.MachineName"/>.
/// </summary>
public static class HostNameResolver
{
    private static readonly Lazy<string> _resolved = new(Resolve);

    public static string HostName => _resolved.Value;

    private static string Resolve()
    {
        var raw = Environment.GetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES");
        if (!string.IsNullOrWhiteSpace(raw))
        {
            // Format: comma-separated key=value pairs (OTel spec).
            foreach (var pair in raw.Split(',', StringSplitOptions.RemoveEmptyEntries))
            {
                var eq = pair.IndexOf('=');
                if (eq <= 0) continue;
                var key = pair.AsSpan(0, eq).Trim();
                if (!key.SequenceEqual("host.name")) continue;
                var value = pair.AsSpan(eq + 1).Trim().ToString();
                if (!string.IsNullOrEmpty(value)) return value;
            }
        }
        return Environment.MachineName;
    }
}
