using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using SessionWatcher.Diagnostics;
using SessionWatcher.Hosting;
using SessionWatcher.Sources.Claude;
using SessionWatcher.Sources.Copilot;

namespace SessionWatcher;

/// <summary>
/// The daemon's main poll loop. Runs every <see cref="PollInterval"/> while the
/// host is alive. Each tick: ask each source to look at its directory, classify
/// what's there, and emit transitions/heartbeats through the configured sink.
/// </summary>
public sealed class WatcherLoop : BackgroundService
{
    private static readonly TimeSpan PollInterval = TimeSpan.FromSeconds(30);

    private readonly IEpochEventSink _sink;
    private readonly ClaudeSource _claude;
    private readonly CopilotSource _copilot;
    private readonly ILogger<WatcherLoop> _logger;

    public WatcherLoop(IProcessProbe probe, IEpochEventSink sink, ILogger<WatcherLoop> logger)
    {
        _sink = sink;
        _logger = logger;
        _claude = new ClaudeSource(WatcherPaths.ClaudeSessionsDir(), probe);
        _copilot = new CopilotSource(WatcherPaths.CopilotSessionStateDir(), probe);
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        _logger.LogInformation(
            "copilot-session-watcher started. Claude={Claude}, Copilot={Copilot}",
            WatcherPaths.ClaudeSessionsDir(),
            WatcherPaths.CopilotSessionStateDir());

        while (!ct.IsCancellationRequested)
        {
            try { _claude.PollOnce(_sink); }
            catch (Exception ex) { _logger.LogError(ex, "Claude source poll failed"); }

            try { _copilot.PollOnce(_sink); }
            catch (Exception ex) { _logger.LogError(ex, "Copilot source poll failed"); }

            try { await Task.Delay(PollInterval, ct); }
            catch (TaskCanceledException) { break; }
        }

        _logger.LogInformation("copilot-session-watcher stopping.");
    }
}
