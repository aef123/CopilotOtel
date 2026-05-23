export interface Session {
  sessionId: string;
  machine: string;
  status: string;
  source: string;
  model: string;
  version: string;
  turns: number;
  inputTokens: number;
  outputTokens: number;
  startTime: string;
  lastActivity: string;
  durationMs: number;
}

export interface Turn {
  traceId: string;
  spanId: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  startTime: string;
  durationMs: number;
}

export interface SessionDetail {
  sessionId: string;
  machine: string;
  version: string;
  turns: Turn[];
}

export interface ApiSpan {
  span_id: string;
  parent_span_id: string;
  name: string;
  service: string;
  host: string;
  start_time: number;
  duration_ms: number;
  status: string;
  attributes: Record<string, string>;
}

export interface SpanNode {
  span: ApiSpan;
  children: SpanNode[];
}

export interface TraceDetail {
  trace_id: string;
  spans: ApiSpan[];
}

export interface TokenUsagePoint {
  timestamp: string;
  input: number;
  output: number;
}

export interface ModelUsage {
  model: string;
  totalInput: number;
  totalOutput: number;
  count: number;
}

export interface ToolUsage {
  tool: string;
  count: number;
  avgDurationMs: number;
}

export type WatcherState = "live" | "active" | "idle" | "orphan" | string;

export interface WatcherSession {
  sessionId: string;
  epoch: number;
  host: string;
  tool: string;       // "claude" | "copilot" | etc.
  state: WatcherState;
  lastObservedAt: string;
  lastObservedAgeSeconds: number;
  serviceVersion?: string;
}

export interface WatcherStateResponse {
  sessions: WatcherSession[];
  queriedAt: string;
  freshnessWindowSeconds: number;
  error?: string;
}


