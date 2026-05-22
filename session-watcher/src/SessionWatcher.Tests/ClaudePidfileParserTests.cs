using SessionWatcher.Sources.Claude;

namespace SessionWatcher.Tests;

public class ClaudePidfileParserTests
{
    // Captured from a real Claude Code 2.1.147 session on Windows.
    // startedAt 1779427166873ms = 2026-05-22T05:19:26.873Z
    // updatedAt 1779427261873ms = 2026-05-22T05:21:01.873Z
    private const string RealPidfileJson =
        """
        {"pid":38112,"sessionId":"79ebdd64-8db7-4f4d-8c64-ef58a4b05fa4","cwd":"c:\\git\\OtelCliCapture","startedAt":1779427166873,"version":"2.1.147","peerProtocol":1,"kind":"interactive","entrypoint":"cli","status":"busy","updatedAt":1779427261873}
        """;

    [Fact]
    public void Parse_RealPidfile_ExtractsAllFields()
    {
        var pidfile = ClaudePidfile.Parse(RealPidfileJson);

        Assert.NotNull(pidfile);
        Assert.Equal(38112, pidfile.Pid);
        Assert.Equal("79ebdd64-8db7-4f4d-8c64-ef58a4b05fa4", pidfile.SessionId);
        Assert.Equal("c:\\git\\OtelCliCapture", pidfile.Cwd);
        Assert.Equal("2.1.147", pidfile.Version);
        Assert.Equal("interactive", pidfile.Kind);
        Assert.Equal("cli", pidfile.Entrypoint);
        Assert.Equal("busy", pidfile.Status);
        Assert.Equal(DateTimeOffset.FromUnixTimeMilliseconds(1779427166873), pidfile.StartedAt);
        Assert.Equal(DateTimeOffset.FromUnixTimeMilliseconds(1779427261873), pidfile.UpdatedAt);
    }

    [Fact]
    public void Parse_InvalidJson_ReturnsNull()
    {
        Assert.Null(ClaudePidfile.Parse("not json"));
        Assert.Null(ClaudePidfile.Parse(""));
    }

    [Fact]
    public void Parse_MissingPid_ReturnsNull()
    {
        const string noPid = """{"sessionId":"abc","cwd":"x","startedAt":1,"version":"1","kind":"i","entrypoint":"c","status":"idle","updatedAt":1}""";
        Assert.Null(ClaudePidfile.Parse(noPid));
    }

    [Fact]
    public void Parse_MissingSessionId_ReturnsNull()
    {
        const string noSid = """{"pid":1,"cwd":"x","startedAt":1,"version":"1","kind":"i","entrypoint":"c","status":"idle","updatedAt":1}""";
        Assert.Null(ClaudePidfile.Parse(noSid));
    }

    [Fact]
    public void Parse_IdleStatus_PreservesStatus()
    {
        const string idleJson =
            """
            {"pid":1234,"sessionId":"abc-def","cwd":"/tmp","startedAt":1779427166873,"version":"2.1.147","peerProtocol":1,"kind":"interactive","entrypoint":"cli","status":"idle","updatedAt":1779427261873}
            """;

        var pidfile = ClaudePidfile.Parse(idleJson);

        Assert.NotNull(pidfile);
        Assert.Equal("idle", pidfile.Status);
    }
}
