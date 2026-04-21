import type {
  Session,
  SessionDetail,
  TraceDetail,
  TokenUsagePoint,
  ModelUsage,
  ToolUsage,
  HealthSummary,
  ApiSpan,
} from "./types";

const BASE = "/dashboard-api";

async function fetchJson<T>(path: string, token?: string | null): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const resp = await fetch(`${BASE}${path}`, { headers });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

function mapSession(raw: any): Session {
  return {
    sessionId: raw.session_id,
    machine: raw.host || "",
    status: raw.status,
    source: raw.source || "",
    model: raw.model || "",
    version: raw.cli_version || "",
    turns: raw.turns || 0,
    inputTokens: raw.total_input_tokens || 0,
    outputTokens: raw.total_output_tokens || 0,
    startTime: new Date(raw.first_seen).toISOString(),
    lastActivity: new Date(raw.last_activity).toISOString(),
    durationMs: (raw.last_activity - raw.first_seen) || 0,
  };
}

function mapTurn(raw: any): any {
  return {
    traceId: raw.trace_id || raw.traceID,
    spanId: raw.span_id || raw.spanID,
    model: raw.model || "",
    inputTokens: raw.input_tokens || 0,
    outputTokens: raw.output_tokens || 0,
    startTime: new Date(raw.start_time_unix_nano ? raw.start_time_unix_nano / 1e6 : raw.start_time).toISOString(),
    durationMs: raw.duration_ms || (raw.duration_s ? raw.duration_s * 1000 : 0),
  };
}

export async function getSessions(token?: string | null): Promise<Session[]> {
  const raw = await fetchJson<any[]>("/sessions", token);
  return raw.map(mapSession);
}

export async function getSessionDetail(
  sessionId: string,
  token?: string | null
): Promise<SessionDetail> {
  const raw = await fetchJson<any>(`/sessions/${sessionId}`, token);
  return {
    sessionId: raw.session_id || sessionId,
    machine: raw.host || "",
    version: raw.cli_version || "",
    turns: (raw.turns || []).map(mapTurn),
  };
}

export async function getTraceDetail(
  sessionId: string,
  traceId: string,
  token?: string | null
): Promise<TraceDetail> {
  const raw = await fetchJson<any>(
    `/sessions/${sessionId}/traces/${traceId}`,
    token
  );
  return raw;
}

export async function getTokenUsage(
  token?: string | null
): Promise<TokenUsagePoint[]> {
  return fetchJson<TokenUsagePoint[]>("/metrics/token-usage", token);
}

export async function getModelUsage(
  token?: string | null
): Promise<ModelUsage[]> {
  return fetchJson<ModelUsage[]>("/metrics/models", token);
}

export async function getToolUsage(
  token?: string | null
): Promise<ToolUsage[]> {
  return fetchJson<ToolUsage[]>("/metrics/tools", token);
}

export async function getHealth(
  token?: string | null
): Promise<HealthSummary> {
  const raw = await fetchJson<any>("/health", token);
  return {
    activeSessions: raw.active_sessions || 0,
    idleSessions: raw.idle_sessions || 0,
    totalSessions: raw.total_sessions || 0,
    totalTokens: (raw.total_input_tokens || 0) + (raw.total_output_tokens || 0),
    avgResponseTime: raw.avg_response_time || 0,
    topModel: raw.top_model || "",
  };
}
