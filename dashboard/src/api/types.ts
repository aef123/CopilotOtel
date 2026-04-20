export interface Session {
  sessionId: string;
  machine: string;
  status: string;
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

export interface Span {
  traceID: string;
  spanID: string;
  parentSpanID: string;
  operationName: string;
  serviceName: string;
  startTime: number;
  duration: number;
  attributes: Record<string, string>;
  children?: Span[];
}

export interface TraceDetail {
  traceId: string;
  rootSpan: Span;
  spans: Span[];
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

export interface HealthSummary {
  activeSessions: number;
  idleSessions: number;
  totalSessions: number;
  totalTokens: number;
  avgResponseTime: number;
  topModel: string;
}
