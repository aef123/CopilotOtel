import type {
  Session,
  SessionDetail,
  TraceDetail,
  TokenUsagePoint,
  ModelUsage,
  ToolUsage,
  ApiSpan,
} from "./types";

const BASE = "/dashboard-api";

export type LookbackWindow = "6h" | "12h" | "24h" | "2d" | "7d";

export const LOOKBACK_OPTIONS: { value: LookbackWindow; label: string }[] = [
  { value: "6h", label: "6 hours" },
  { value: "12h", label: "12 hours" },
  { value: "24h", label: "24 hours" },
  { value: "2d", label: "2 days" },
  { value: "7d", label: "1 week" },
];

export function getLookback(): LookbackWindow {
  return (localStorage.getItem("lookback") as LookbackWindow) || "24h";
}

export function setLookback(v: LookbackWindow) {
  localStorage.setItem("lookback", v);
}

async function fetchJson<T>(path: string, token?: string | null, lookback?: LookbackWindow): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const sep = path.includes("?") ? "&" : "?";
  const url = lookback ? `${BASE}${path}${sep}lookback=${lookback}` : `${BASE}${path}`;
  const resp = await fetch(url, { headers });
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

export async function getSessions(token?: string | null, lookback?: LookbackWindow): Promise<Session[]> {
  const raw = await fetchJson<any[]>("/sessions", token, lookback);
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
  token?: string | null,
  lookback?: LookbackWindow
): Promise<TokenUsagePoint[]> {
  return fetchJson<TokenUsagePoint[]>("/metrics/token-usage", token, lookback);
}

export async function getModelUsage(
  token?: string | null,
  lookback?: LookbackWindow
): Promise<ModelUsage[]> {
  return fetchJson<ModelUsage[]>("/metrics/models", token, lookback);
}

export async function getToolUsage(
  token?: string | null,
  lookback?: LookbackWindow
): Promise<ToolUsage[]> {
  return fetchJson<ToolUsage[]>("/metrics/tools", token, lookback);
}

export async function getDebugSession(
  sessionId: string,
  token?: string | null
): Promise<any> {
  return fetchJson<any>(`/debug/session/${sessionId}`, token);
}


