using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using SessionWatcher;
using SessionWatcher.Diagnostics;
using SessionWatcher.Hosting;
using SessionWatcher.Telemetry;

var stateDir = WatcherPaths.StateDir();
Directory.CreateDirectory(stateDir);
var lockPath = Path.Combine(stateDir, "session-watcher.lock");
var pidfilePath = Path.Combine(stateDir, "pidfile.txt");

using var singleton = SingletonLock.TryAcquire(lockPath, pidfilePath);
if (singleton is null)
{
    await Console.Error.WriteLineAsync(
        $"copilot-session-watcher: another instance is already running. See {pidfilePath}. Exiting.");
    return 0;
}

var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddSessionWatcherTelemetry();
builder.Services.AddSingleton<IProcessProbe, OsProcessProbe>();
builder.Services.AddSingleton<IEpochEventSink, OtelSink>();
builder.Services.AddHostedService<WatcherLoop>();

await builder.Build().RunAsync();
return 0;
