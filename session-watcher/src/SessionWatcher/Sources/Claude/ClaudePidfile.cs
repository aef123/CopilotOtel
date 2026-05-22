using System.Text.Json;
using System.Text.Json.Serialization;

namespace SessionWatcher.Sources.Claude;

/// <summary>
/// Per-process file at %USERPROFILE%\.claude\sessions\&lt;pid&gt;.json that Claude Code
/// writes for the lifetime of a session. File presence is the daemon's "live"
/// signal; the embedded fields enrich the lifecycle epoch.
/// </summary>
public sealed record ClaudePidfile(
    int Pid,
    string SessionId,
    string Cwd,
    DateTimeOffset StartedAt,
    string Version,
    string Kind,
    string Entrypoint,
    string Status,
    DateTimeOffset UpdatedAt)
{
    public static ClaudePidfile? Parse(string json)
    {
        if (string.IsNullOrWhiteSpace(json)) return null;

        ClaudePidfileDto? dto;
        try
        {
            dto = JsonSerializer.Deserialize<ClaudePidfileDto>(json);
        }
        catch (JsonException)
        {
            return null;
        }

        if (dto is null) return null;
        if (dto.Pid is null or 0) return null;
        if (string.IsNullOrEmpty(dto.SessionId)) return null;

        return new ClaudePidfile(
            Pid: dto.Pid.Value,
            SessionId: dto.SessionId,
            Cwd: dto.Cwd ?? "",
            StartedAt: dto.StartedAt is { } start
                ? DateTimeOffset.FromUnixTimeMilliseconds(start)
                : DateTimeOffset.MinValue,
            Version: dto.Version ?? "",
            Kind: dto.Kind ?? "",
            Entrypoint: dto.Entrypoint ?? "",
            Status: dto.Status ?? "",
            UpdatedAt: dto.UpdatedAt is { } updated
                ? DateTimeOffset.FromUnixTimeMilliseconds(updated)
                : DateTimeOffset.MinValue);
    }

    private sealed class ClaudePidfileDto
    {
        [JsonPropertyName("pid")] public int? Pid { get; set; }
        [JsonPropertyName("sessionId")] public string? SessionId { get; set; }
        [JsonPropertyName("cwd")] public string? Cwd { get; set; }
        [JsonPropertyName("startedAt")] public long? StartedAt { get; set; }
        [JsonPropertyName("version")] public string? Version { get; set; }
        [JsonPropertyName("kind")] public string? Kind { get; set; }
        [JsonPropertyName("entrypoint")] public string? Entrypoint { get; set; }
        [JsonPropertyName("status")] public string? Status { get; set; }
        [JsonPropertyName("updatedAt")] public long? UpdatedAt { get; set; }
    }
}
