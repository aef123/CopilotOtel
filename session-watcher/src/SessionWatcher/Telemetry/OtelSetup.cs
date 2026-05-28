using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using OpenTelemetry.Logs;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

namespace SessionWatcher.Telemetry;

/// <summary>
/// Wires the OTel SDK to forward logs/metrics/traces to whatever
/// <c>OTEL_EXPORTER_OTLP_*</c> env vars point at — typically the local
/// collector that <c>setup-machine.ps1</c> deploys.
/// </summary>
public static class OtelSetup
{
    /// <summary>
    /// Sets <c>OTEL_SERVICE_NAME</c> in-process if it isn't already set, so the
    /// resource attribute is right even when the env var only carries the
    /// Claude/Copilot value.
    /// </summary>
    public static void EnsureServiceName()
    {
        if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("OTEL_SERVICE_NAME")))
        {
            Environment.SetEnvironmentVariable("OTEL_SERVICE_NAME", WatcherTelemetry.ServiceName);
        }
        else
        {
            // The shell may have set OTEL_SERVICE_NAME=claude-code for the Claude/Copilot
            // tooling. The daemon overrides in-process so its emissions are
            // distinguishable from the tools'.
            Environment.SetEnvironmentVariable("OTEL_SERVICE_NAME", WatcherTelemetry.ServiceName);
        }
    }

    public static IServiceCollection AddSessionWatcherTelemetry(this IServiceCollection services)
    {
        EnsureServiceName();

        var resource = ResourceBuilder.CreateDefault()
            .AddService(WatcherTelemetry.ServiceName, serviceVersion: WatcherTelemetry.ServiceVersion)
            .AddAttributes(new KeyValuePair<string, object>[]
            {
                new("host.name", HostNameResolver.HostName),
            });

        services.AddOpenTelemetry()
            .ConfigureResource(rb => rb
                .AddService(WatcherTelemetry.ServiceName, serviceVersion: WatcherTelemetry.ServiceVersion)
                .AddAttributes(new KeyValuePair<string, object>[]
                {
                    new("host.name", HostNameResolver.HostName),
                }))
            .WithTracing(tb => tb
                .AddSource(WatcherTelemetry.ActivitySourceName)
                .AddOtlpExporter())
            .WithMetrics(mb => mb
                .AddMeter(WatcherTelemetry.MeterName)
                .AddOtlpExporter());

        services.AddLogging(lb => lb
            .AddOpenTelemetry(o =>
            {
                o.SetResourceBuilder(resource);
                o.IncludeScopes = true;
                o.IncludeFormattedMessage = true;
                o.ParseStateValues = true;
                o.AddOtlpExporter();
            }));

        return services;
    }
}
