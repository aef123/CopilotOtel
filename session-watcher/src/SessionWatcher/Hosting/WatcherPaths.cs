namespace SessionWatcher.Hosting;

/// <summary>
/// Resolves the on-disk locations the daemon reads (Copilot session-state,
/// Claude sessions/) and writes (its own state directory).
/// </summary>
public static class WatcherPaths
{
    /// <summary>
    /// %USERPROFILE%\.copilot\session-state (Windows) or
    /// ~/.copilot/session-state (Unix). Each subdirectory is a Copilot session
    /// ID; an <c>inuse.&lt;pid&gt;.lock</c> inside it means the session is live.
    /// Override with <c>COPILOT_SESSION_STATE_DIR</c>.
    /// </summary>
    public static string CopilotSessionStateDir() =>
        Environment.GetEnvironmentVariable("COPILOT_SESSION_STATE_DIR")
        ?? Path.Combine(UserHome(), ".copilot", "session-state");

    /// <summary>
    /// %USERPROFILE%\.claude\sessions (Windows) or ~/.claude/sessions (Unix).
    /// Each <c>&lt;pid&gt;.json</c> file is the Claude Code per-process pidfile.
    /// Override with <c>CLAUDE_SESSIONS_DIR</c>.
    /// </summary>
    public static string ClaudeSessionsDir() =>
        Environment.GetEnvironmentVariable("CLAUDE_SESSIONS_DIR")
        ?? Path.Combine(UserHome(), ".claude", "sessions");

    /// <summary>
    /// Per-user, per-host directory the daemon owns: singleton lock, pidfile,
    /// and rolling diagnostic log.
    /// </summary>
    public static string StateDir()
    {
        var overrideDir = Environment.GetEnvironmentVariable("COPILOT_SESSION_WATCHER_STATE_DIR");
        if (!string.IsNullOrEmpty(overrideDir)) return overrideDir;

        if (OperatingSystem.IsWindows())
        {
            var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            return Path.Combine(localAppData, "CopilotOtel", "session-watcher");
        }
        if (OperatingSystem.IsMacOS())
        {
            return Path.Combine(UserHome(), "Library", "Application Support", "CopilotOtel", "session-watcher");
        }
        var xdg = Environment.GetEnvironmentVariable("XDG_STATE_HOME");
        var stateRoot = string.IsNullOrEmpty(xdg)
            ? Path.Combine(UserHome(), ".local", "state")
            : xdg;
        return Path.Combine(stateRoot, "CopilotOtel", "session-watcher");
    }

    private static string UserHome() =>
        Environment.GetEnvironmentVariable("USERPROFILE")
        ?? Environment.GetEnvironmentVariable("HOME")
        ?? Directory.GetCurrentDirectory();
}
