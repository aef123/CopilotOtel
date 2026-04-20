import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { getTraceDetail } from "../api/client";
import type { TraceDetail as TraceDetailType, ApiSpan, SpanNode } from "../api/types";
import { formatDuration } from "../utils/format";

const GRAFANA_BASE = window.location.port === "8888"
  ? "http://localhost:3000"
  : window.location.origin;

function spanClass(name: string): string {
  if (name === "invoke_agent") return "invoke";
  if (name.startsWith("chat")) return "chat";
  if (name === "execute_tool" || name.includes("tool")) return "tool";
  return "other";
}

function buildTree(spans: ApiSpan[]): SpanNode[] {
  const map = new Map<string, SpanNode>();
  const roots: SpanNode[] = [];

  for (const s of spans) {
    map.set(s.span_id, { span: s, children: [] });
  }

  for (const s of spans) {
    const node = map.get(s.span_id)!;
    if (s.parent_span_id && map.has(s.parent_span_id)) {
      map.get(s.parent_span_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const sortChildren = (node: SpanNode) => {
    node.children.sort((a, b) => a.span.start_time - b.span.start_time);
    node.children.forEach(sortChildren);
  };
  roots.forEach(sortChildren);

  return roots;
}

function SpanRow({
  node,
  depth,
  traceStart,
  traceDuration,
}: {
  node: SpanNode;
  depth: number;
  traceStart: number;
  traceDuration: number;
}) {
  const s = node.span;
  const offsetPct = traceDuration > 0
    ? ((s.start_time - traceStart) / traceDuration) * 100
    : 0;
  const widthPct = traceDuration > 0
    ? (s.duration_ms / traceDuration) * 100
    : 100;

  const toolName = s.attributes?.["gen_ai.tool.name"] || "";
  const model = s.attributes?.["gen_ai.response.model"] || "";
  const inputTokens = s.attributes?.["gen_ai.usage.input_tokens"] || "";
  const outputTokens = s.attributes?.["gen_ai.usage.output_tokens"] || "";

  return (
    <>
      <div className="span-row">
        <div className="span-indent" style={{ width: depth * 20 }} />
        <div className="span-name">
          {s.name}
          {toolName && <span className="span-tool-label"> ({toolName})</span>}
        </div>
        <div className="span-bar-container">
          <div
            className={`span-bar ${spanClass(s.name)}`}
            style={{
              left: `${Math.max(0, Math.min(offsetPct, 100))}%`,
              width: `${Math.max(0.5, Math.min(widthPct, 100 - offsetPct))}%`,
            }}
          />
        </div>
        <div className="span-duration">{formatDuration(s.duration_ms)}</div>
      </div>
      {(model || inputTokens || outputTokens) && (
        <div className="span-row" style={{ paddingLeft: depth * 20 + 20 }}>
          <div className="span-attrs">
            {model && <span>model: {model} </span>}
            {inputTokens && <span>in: {inputTokens} </span>}
            {outputTokens && <span>out: {outputTokens} </span>}
          </div>
        </div>
      )}
      {node.children.map((child) => (
        <SpanRow
          key={child.span.span_id}
          node={child}
          depth={depth + 1}
          traceStart={traceStart}
          traceDuration={traceDuration}
        />
      ))}
    </>
  );
}

export function TraceDetail() {
  const { sessionId, traceId } = useParams<{ sessionId: string; traceId: string }>();
  const [trace, setTrace] = useState<TraceDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId || !traceId) return;
    let mounted = true;
    getTraceDetail(sessionId, traceId)
      .then((d) => { if (mounted) setTrace(d); })
      .catch((e) => { if (mounted) setError(e.message); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [sessionId, traceId]);

  if (loading) return <div className="loading">Loading trace...</div>;
  if (error) return <div className="error-message">{error}</div>;
  if (!trace || trace.spans.length === 0) {
    return <div className="empty-state">Trace not found</div>;
  }

  const roots = buildTree(trace.spans);
  const allSpans = trace.spans;
  const traceStart = Math.min(...allSpans.map((s) => s.start_time));
  const traceEnd = Math.max(...allSpans.map((s) => s.start_time + s.duration_ms));
  const traceDuration = traceEnd - traceStart;

  const grafanaUrl = `${GRAFANA_BASE}/explore?left={"datasource":"P214B5B846CF3925F","queries":[{"refId":"A","queryType":"traceql","query":"${traceId}"}],"range":{"from":"now-6h","to":"now"}}`;

  return (
    <>
      <Link to={`/sessions/${sessionId}`} className="back-link">&larr; Back to Session</Link>
      <div className="detail-card">
        <h2>Trace</h2>
        <div className="detail-grid">
          <div className="detail-field">
            <div className="label">Trace ID</div>
            <div className="value" style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
              {trace.trace_id}
            </div>
          </div>
          <div className="detail-field">
            <div className="label">Spans</div>
            <div className="value">{allSpans.length}</div>
          </div>
          <div className="detail-field">
            <div className="label">Total Duration</div>
            <div className="value">{formatDuration(traceDuration)}</div>
          </div>
          <div className="detail-field">
            <div className="label">Grafana</div>
            <div className="value">
              <a
                href={grafanaUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "var(--accent)", fontSize: 12 }}
              >
                View in Grafana/Tempo &rarr;
              </a>
            </div>
          </div>
        </div>
      </div>

      <h2>Span Tree</h2>
      <div className="span-tree">
        {roots.map((root) => (
          <SpanRow
            key={root.span.span_id}
            node={root}
            depth={0}
            traceStart={traceStart}
            traceDuration={traceDuration}
          />
        ))}
      </div>
    </>
  );
}
