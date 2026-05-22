namespace SessionWatcher.Sources.Copilot;

/// <summary>
/// Copilot's session-state directory contains an empty file named
/// <c>inuse.&lt;pid&gt;.lock</c> while the session is live. The PID is encoded in
/// the filename only; the file body carries nothing useful.
/// </summary>
public static class CopilotLockParser
{
    public static bool TryParsePid(string filenameOrPath, out int pid)
    {
        pid = 0;
        if (string.IsNullOrEmpty(filenameOrPath)) return false;

        var name = Path.GetFileName(filenameOrPath);
        const string prefix = "inuse.";
        const string suffix = ".lock";

        if (name.Length <= prefix.Length + suffix.Length) return false;
        if (!name.StartsWith(prefix, StringComparison.Ordinal)) return false;
        if (!name.EndsWith(suffix, StringComparison.Ordinal)) return false;

        var middle = name.AsSpan(prefix.Length, name.Length - prefix.Length - suffix.Length);
        if (middle.IsEmpty) return false;

        // Reject negative or non-digit input early — int.TryParse permits a leading '-'.
        foreach (var c in middle)
        {
            if (!char.IsDigit(c)) return false;
        }

        if (!int.TryParse(middle, out var parsed)) return false;
        if (parsed <= 0) return false;

        pid = parsed;
        return true;
    }
}
