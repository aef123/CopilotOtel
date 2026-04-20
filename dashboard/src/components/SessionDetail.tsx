import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { getSessionDetail } from "../api/client";
import type { SessionDetail as SessionDetailType } from "../api/types";
import { formatDuration, formatTokens, formatTime } from "../utils/format";

const GRAFANA_BASE = window.location.port === "8888"
  ? "http://localhost:3000"
  : window.location.origin;

export function SessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const nav = useNavigate();
  const [detail, setDetail] = useState<SessionDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId) return;
    let mounted = true;
    const load = () => {
      getSessionDetail(sessionId)
        .then((d) => { if (mounted) setDetail(d); })
        .catch((e) => { if (mounted) setError(e.message); })
        .finally(() => { if (mounted) setLoading(false); });
    };
    load();
    const interval = setInterval(load, 15000);
    return () => { mounted = false; clearInterval(interval); };
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

      <h2>Prompts / Turns</h2>
      {detail.turns.length === 0 ? (
        <div className="empty-state">No turns recorded yet (data may have expired from Tempo)</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Model</th>
              <th>Input Tokens</th>
              <th>Output Tokens</th>
              <th>Duration</th>
              <th>Started</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {detail.turns.map((t, i) => {
              const grafanaUrl = `${GRAFANA_BASE}/explore?left={"datasource":"P214B5B846CF3925F","queries":[{"refId":"A","queryType":"traceql","query":"${t.traceId}"}],"range":{"from":"now-6h","to":"now"}}`;
              return (
                <tr
                  key={t.spanId}
                  onClick={() => nav(`/sessions/${sessionId}/traces/${t.traceId}`)}
                >
                  <td>{i + 1}</td>
                  <td>{t.model || "N/A"}</td>
                  <td>{formatTokens(t.inputTokens)}</td>
                  <td>{formatTokens(t.outputTokens)}</td>
                  <td>{formatDuration(t.durationMs)}</td>
                  <td>{formatTime(t.startTime)}</td>
                  <td>
                    <a
                      href={grafanaUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      style={{ color: "var(--accent)", fontSize: 11 }}
                      title="Open in Grafana/Tempo"
                    >
                      Grafana &rarr;
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </>
  );
}
