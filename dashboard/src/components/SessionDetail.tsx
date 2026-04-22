import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { getSessionDetail, getDebugSession } from "../api/client";
import { useAuth } from "../auth/useAuth";
import type { SessionDetail as SessionDetailType } from "../api/types";
import { formatDuration, formatTokens, formatTime } from "../utils/format";

const GRAFANA_BASE = window.location.port === "8888"
  ? "http://localhost:3000"
  : window.location.origin;

export function SessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const nav = useNavigate();
  const { getAccessToken } = useAuth();
  const [detail, setDetail] = useState<SessionDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [debugData, setDebugData] = useState<any>(null);
  const [debugLoading, setDebugLoading] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    let mounted = true;
    const load = async () => {
      const token = await getAccessToken();
      getSessionDetail(sessionId, token)
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
        <h2>
          Session Info
          <button
            onClick={async () => {
              setDebugLoading(true);
              try {
                const token = await getAccessToken();
                const d = await getDebugSession(sessionId!, token);
                setDebugData(d);
              } catch (e: any) {
                setDebugData({ error: e.message });
              } finally {
                setDebugLoading(false);
              }
            }}
            style={{
              marginLeft: 16, fontSize: 11, padding: "2px 10px",
              background: "var(--bg-secondary)", color: "var(--text-secondary)",
              border: "1px solid var(--border)", borderRadius: 4, cursor: "pointer",
            }}
          >
            {debugLoading ? "Loading..." : "Debug"}
          </button>
        </h2>
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
        {debugData && (
          <pre style={{
            marginTop: 12, padding: 12, background: "var(--bg-primary)",
            border: "1px solid var(--border)", borderRadius: 6,
            fontSize: 11, fontFamily: "var(--font-mono)",
            maxHeight: 400, overflow: "auto", whiteSpace: "pre-wrap",
          }}>
            {JSON.stringify(debugData, null, 2)}
          </pre>
        )}
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
