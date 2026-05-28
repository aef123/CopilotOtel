using SessionWatcher.Telemetry;

namespace SessionWatcher.Tests;

/// <summary>
/// Verifies that the <c>host.name</c> override from
/// <c>OTEL_RESOURCE_ATTRIBUTES</c> is parsed correctly. We can't easily test
/// the Lazy-cached <see cref="HostNameResolver.HostName"/> directly without
/// process restart, so we exercise the same parsing surface by exposing it via
/// reflection over the private <c>Resolve</c> method.
/// </summary>
public class HostNameResolverTests
{
    private static string InvokeResolve()
    {
        var m = typeof(HostNameResolver).GetMethod(
            "Resolve",
            System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!;
        return (string)m.Invoke(null, null)!;
    }

    [Fact]
    public void Resolve_HonorsHostNameOverrideInResourceAttributes()
    {
        var prior = Environment.GetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES");
        try
        {
            Environment.SetEnvironmentVariable(
                "OTEL_RESOURCE_ATTRIBUTES",
                "service.namespace=test,host.name=friendly-box,deployment.environment=dev");
            Assert.Equal("friendly-box", InvokeResolve());
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES", prior);
        }
    }

    [Fact]
    public void Resolve_FallsBackToMachineNameWhenEnvMissing()
    {
        var prior = Environment.GetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES");
        try
        {
            Environment.SetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES", null);
            Assert.Equal(Environment.MachineName, InvokeResolve());
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES", prior);
        }
    }

    [Fact]
    public void Resolve_FallsBackWhenHostNameKeyAbsent()
    {
        var prior = Environment.GetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES");
        try
        {
            Environment.SetEnvironmentVariable(
                "OTEL_RESOURCE_ATTRIBUTES",
                "service.namespace=test,deployment.environment=dev");
            Assert.Equal(Environment.MachineName, InvokeResolve());
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES", prior);
        }
    }
}
