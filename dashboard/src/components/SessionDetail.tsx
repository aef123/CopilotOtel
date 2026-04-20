import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { getSessionDetail } from "../api/client";
import type { SessionDetail as SessionDetailType } from "../api/types";
import { formatDuration, formatTokens, formatTime } from "../utils/format";

export function SessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const nav = useNavigate();
  const [detail, setDetail] = useState<SessionDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId) return;
    let mounted = true;
    getSessionDetail(sessionId)
      .then((d) => { if (mounted) setDetail(d); })
      .catch((e) => { if (mounted) setError(e.message); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [sessionId]);

  if (loading) return <div className="loading">Loading session...</div>;
  if (error) return <div className="error-message">{error}</div>;
  if (!detail) return <div className="empty-state">Session not found</div>;

  return (
    <>
      <Link to="/" className="back-link">&larr; Back to Sessions</Link>

      <div className="detail-card">
        <h2>Session Info</h2>
        <div className="detail-grid">
          <div className="detail-field">
            <div className="label">Session ID</div>
            <div className="value" style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
              {detail.sessionId}
            </div>
          </div>
          <div className="detail-field">
            <div className="label">Machine</div>
            <div className="value">{detail.machine || "Unknown"}</div>
          </div>
          <div className="detail-field">
            <div className="label">Agent Version</div>
            <div className="value">{detail.version || "N/A"}</div>
          </div>
          <div className="detail-field">
            <div className="label">Turns</div>
            <div className="value">{detail.turns.length}</div>
          </div>
        </div>
      </div>

      <h2>Turns</h2>
      <table className="data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Model</th>
            <th>Input Tokens</th>
            <th>Output Tokens</th>
            <th>Duration</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          {detail.turns.map((t, i) => (
            <tr
              key={t.spanId}
              onClick={() => nav(`/sessions/${sessionId}/traces/${t.traceId}`)}
            >
              <td>{i + 1}</td>
              <td>{t.model}</td>
              <td>{formatTokens(t.inputTokens)}</td>
              <td>{formatTokens(t.outputTokens)}</td>
              <td>{formatDuration(t.durationMs)}</td>
              <td>{formatTime(t.startTime)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
