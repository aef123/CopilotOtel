import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { getTraceDetail } from "../api/client";
import type { TraceDetail as TraceDetailType, Span } from "../api/types";
import { formatDuration } from "../utils/format";

function spanClass(name: string): string {
  if (name === "invoke_agent") return "invoke";
  if (name.startsWith("chat")) return "chat";
  if (name === "execute_tool" || name.includes("tool")) return "tool";
  return "other";
}

function SpanRow({
  span,
  depth,
  traceStart,
  traceDuration,
}: {
  span: Span;
  depth: number;
  traceStart: number;
  traceDuration: number;
}) {
  const offsetPct = traceDuration > 0
    ? ((span.startTime - traceStart) / traceDuration) * 100
    : 0;
  const widthPct = traceDuration > 0
    ? (span.duration / traceDuration) * 100
    : 100;

  const toolName = span.attributes?.["gen_ai.tool.name"] || "";
  const model = span.attributes?.["gen_ai.response.model"] || "";

  return (
    <>
      <div className="span-row">
        <div className="span-indent" style={{ width: depth * 20 }} />
        <div className="span-name">{span.operationName}</div>
        <div className="span-bar-container">
          <div
            className={`span-bar ${spanClass(span.operationName)}`}
            style={{
              left: `${Math.max(0, Math.min(offsetPct, 100))}%`,
              width: `${Math.max(0.5, Math.min(widthPct, 100 - offsetPct))}%`,
            }}
          />
        </div>
        <div className="span-duration">{formatDuration(span.duration / 1000)}</div>
      </div>
      {span.attributes && (toolName || model) && (
        <div className="span-row" style={{ paddingLeft: depth * 20 + 20 }}>
          <div className="span-attrs">
            {model && <span>model: {model} </span>}
            {toolName && <span>tool: {toolName}</span>}
          </div>
        </div>
      )}
      {span.children?.map((child) => (
        <SpanRow
          key={child.spanID}
          span={child}
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
  if (!trace) return <div className="empty-state">Trace not found</div>;

  const traceStart = trace.rootSpan.startTime;
  const traceDuration = Math.max(
    ...trace.spans.map((s) => s.startTime + s.duration)
  ) - traceStart;

  return (
    <>
      <Link to={`/sessions/${sessionId}`} className="back-link">&larr; Back to Session</Link>
      <div className="detail-card">
        <h2>Trace</h2>
        <div className="detail-grid">
          <div className="detail-field">
            <div className="label">Trace ID</div>
            <div className="value" style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
              {trace.traceId}
            </div>
          </div>
          <div className="detail-field">
            <div className="label">Spans</div>
            <div className="value">{trace.spans.length}</div>
          </div>
          <div className="detail-field">
            <div className="label">Total Duration</div>
            <div className="value">{formatDuration(traceDuration / 1000)}</div>
          </div>
        </div>
      </div>

      <h2>Span Tree</h2>
      <div className="span-tree">
        <SpanRow
          span={trace.rootSpan}
          depth={0}
          traceStart={traceStart}
          traceDuration={traceDuration}
        />
      </div>
    </>
  );
}
