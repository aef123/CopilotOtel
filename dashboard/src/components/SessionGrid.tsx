import { useNavigate } from "react-router-dom";
import type { Session } from "../api/types";
import { formatDuration, formatTokens, timeAgo } from "../utils/format";

export function SessionGrid({ sessions }: { sessions: Session[] }) {
  const nav = useNavigate();

  if (sessions.length === 0) {
    return <div className="empty-state">No sessions found</div>;
  }

  return (
    <div className="session-grid">
      {sessions.map((s) => (
        <div
          key={s.sessionId}
          className={`session-card ${s.status === "Active" ? "session-card-active" : ""}`}
          onClick={() => nav(`/sessions/${s.sessionId}`)}
        >
          <div className="session-card-header">
            <span className={`badge badge-${s.status.toLowerCase()}`}>{s.status}</span>
            {s.source && <span className={`badge badge-source-${s.source.toLowerCase()}`}>{s.source}</span>}
            <span className="session-card-heartbeat">{timeAgo(s.lastActivity)}</span>
          </div>
          <div className="session-card-machine">{s.machine || "Unknown"}</div>
          <div className="session-card-id">{s.sessionId.slice(0, 12)}...</div>
          <div className="session-card-meta">
            {s.model && <span className="session-card-model">{s.model}</span>}
            {s.version && <span className="session-card-version">v{s.version}</span>}
          </div>
          <div className="session-card-times">
            <span>Turns: {s.turns}</span>
            <span>{formatDuration(s.durationMs)}</span>
          </div>
          <div className="session-card-tokens">
            <div>
              <div className="token-label">Input</div>
              {formatTokens(s.inputTokens)}
            </div>
            <div>
              <div className="token-label">Output</div>
              {formatTokens(s.outputTokens)}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
