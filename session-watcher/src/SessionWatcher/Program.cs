using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using SessionWatcher;
using SessionWatcher.Diagnostics;
using SessionWatcher.Hosting;
using SessionWatcher.Telemetry;

var stateDir = WatcherPaths.StateDir();
Directory.CreateDirectory(stateDir);
var logDir = Path.Combine(stateDir, "logs");
Directory.CreateDirectory(logDir);
var lockPath = Path.Combine(stateDir, "session-watcher.lock");
var pidfilePath = Path.Combine(stateDir, "pidfile.txt");
var logFilePath = Path.Combine(logDir, "watcher.log");

// File logger gets attached BEFORE the singleton check so the conflict
// message lands on disk even when we exit immediately.
var fileLogger = new FileLoggerProvider(logFilePath);
var bootLogger = fileLogger.CreateLogger("SessionWatcher.Boot");

using var singleton = SingletonLock.TryAcquire(lockPath, pidfilePath);
if (singleton is null)
{
    bootLogger.LogWarning(
        "copilot-session-watcher: another instance is already running. See {Pidfile}. Exiting.",
        pidfilePath);
    return 0;
}

var builder = Host.CreateApplicationBuilder(args);
builder.Logging.AddProvider(fileLogger);
builder.Services.AddSessionWatcherTelemetry();
builder.Services.AddSingleton<IProcessProbe, OsProcessProbe>();
builder.Services.AddSingleton<IEpochEventSink, OtelSink>();
builder.Services.AddHostedService<WatcherLoop>();

await builder.Build().RunAsync();
return 0;
