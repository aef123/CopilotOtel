using System.Text;
using Microsoft.Extensions.Logging;

namespace SessionWatcher.Telemetry;

/// <summary>
/// Tiny rolling-file logger so the daemon has on-disk diagnostics when the
/// local OTel collector is down. Lock-free single-writer file append; one
/// global instance per process. Not high-performance — fine for a few records
/// per second.
/// </summary>
public sealed class FileLoggerProvider : ILoggerProvider
{
    private readonly string _path;
    private readonly long _maxBytes;
    private readonly int _maxBackups;
    private readonly object _gate = new();

    public FileLoggerProvider(string path, long maxBytes = 10 * 1024 * 1024, int maxBackups = 5)
    {
        _path = path;
        _maxBytes = maxBytes;
        _maxBackups = maxBackups;
        var dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
    }

    public ILogger CreateLogger(string categoryName) => new FileLogger(this, categoryName);

    public void Dispose() { }

    internal void Write(string category, LogLevel level, string message, Exception? ex)
    {
        var line = new StringBuilder(256)
            .Append(DateTimeOffset.UtcNow.ToString("O")).Append(' ')
            .Append(LevelTag(level)).Append(' ')
            .Append(category).Append(": ")
            .Append(message);
        if (ex is not null) line.Append(' ').Append(ex);
        line.Append('\n');

        lock (_gate)
        {
            try
            {
                File.AppendAllText(_path, line.ToString());
                MaybeRotate();
            }
            catch (IOException) { /* swallow — file logger must never throw */ }
        }
    }

    private void MaybeRotate()
    {
        FileInfo fi;
        try { fi = new FileInfo(_path); }
        catch { return; }
        if (!fi.Exists || fi.Length < _maxBytes) return;

        // Shift .N -> .N+1, drop the oldest, move current -> .1
        try
        {
            for (var i = _maxBackups; i >= 1; i--)
            {
                var src = _path + "." + i;
                var dst = _path + "." + (i + 1);
                if (i == _maxBackups && File.Exists(src)) File.Delete(src);
                if (File.Exists(src)) File.Move(src, dst, overwrite: true);
            }
            File.Move(_path, _path + ".1", overwrite: true);
        }
        catch (IOException) { /* best-effort */ }
    }

    private static string LevelTag(LogLevel l) => l switch
    {
        LogLevel.Trace => "TRC",
        LogLevel.Debug => "DBG",
        LogLevel.Information => "INF",
        LogLevel.Warning => "WRN",
        LogLevel.Error => "ERR",
        LogLevel.Critical => "CRT",
        _ => "INF",
    };

    private sealed class FileLogger : ILogger
    {
        private readonly FileLoggerProvider _owner;
        private readonly string _category;

        public FileLogger(FileLoggerProvider owner, string category)
        {
            _owner = owner;
            _category = category;
        }

        public IDisposable BeginScope<TState>(TState state) where TState : notnull => NullScope.Instance;
        public bool IsEnabled(LogLevel logLevel) => logLevel >= LogLevel.Information;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state,
                                Exception? exception, Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(logLevel)) return;
            _owner.Write(_category, logLevel, formatter(state, exception), exception);
        }

        private sealed class NullScope : IDisposable
        {
            public static readonly NullScope Instance = new();
            public void Dispose() { }
        }
    }
}
