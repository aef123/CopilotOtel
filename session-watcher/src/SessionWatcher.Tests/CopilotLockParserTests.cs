using SessionWatcher.Sources.Copilot;

namespace SessionWatcher.Tests;

public class CopilotLockParserTests
{
    [Fact]
    public void TryParsePid_StandardLockName_ReturnsPid()
    {
        Assert.True(CopilotLockParser.TryParsePid("inuse.38112.lock", out var pid));
        Assert.Equal(38112, pid);
    }

    [Fact]
    public void TryParsePid_PathWithDirectory_ReturnsPid()
    {
        Assert.True(CopilotLockParser.TryParsePid(@"C:\Users\x\.copilot\session-state\abc\inuse.99.lock", out var pid));
        Assert.Equal(99, pid);
    }

    [Theory]
    [InlineData("")]
    [InlineData("not-a-lock")]
    [InlineData("inuse.lock")]
    [InlineData("inuse..lock")]
    [InlineData("inuse.notanumber.lock")]
    [InlineData("inuse.-1.lock")]
    [InlineData("inuse.0.lock")]
    [InlineData("preuse.123.lock")]
    public void TryParsePid_InvalidName_ReturnsFalse(string filename)
    {
        Assert.False(CopilotLockParser.TryParsePid(filename, out var pid));
        Assert.Equal(0, pid);
    }

    [Fact]
    public void TryParsePid_PidTooLarge_ReturnsFalse()
    {
        Assert.False(CopilotLockParser.TryParsePid("inuse.99999999999999.lock", out _));
    }
}
