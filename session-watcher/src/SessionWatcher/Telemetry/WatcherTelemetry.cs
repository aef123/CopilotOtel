using System.Diagnostics;
using System.Diagnostics.Metrics;

namespace SessionWatcher.Telemetry;

/// <summary>
/// Diagnostic source roots for the daemon. Strings are stable contract values
/// that downstream collectors / queries depend on.
/// </summary>
public static class WatcherTelemetry
{
    public const string ServiceName = "copilot-session-watcher";
    public const string MeterName = "copilot.session.watcher";
    public const string ActivitySourceName = "copilot.session.watcher";

    /// <summary>Single process-wide ActivitySource for lifecycle spans.</summary>
    public static readonly ActivitySource ActivitySource = new(ActivitySourceName, ServiceVersion);

    /// <summary>Single process-wide Meter for daemon metrics.</summary>
    public static readonly Meter Meter = new(MeterName, ServiceVersion);

    public const string ServiceVersion = "0.1.0";
}
