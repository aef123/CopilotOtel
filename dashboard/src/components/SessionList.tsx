import { useNavigate } from "react-router-dom";
import type { Session } from "../api/types";
import { formatDuration, formatTokens, timeAgo } from "../utils/format";

export function SessionList({ sessions }: { sessions: Session[] }) {
  const nav = useNavigate();

  if (sessions.length === 0) {
    return <div className="empty-state">No sessions found</div>;
  }

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Status</th>
          <th>Source</th>
          <th>Session ID</th>
          <th>Machine</th>
          <th>Last prompt</th>
          <th>Model</th>
          <th>Turns</th>
          <th>Tokens</th>
          <th>Duration</th>
          <th>Last activity</th>
        </tr>
      </thead>
      <tbody>
        {sessions.map((s) => (
          <tr key={s.sessionId} onClick={() => nav(`/sessions/${s.sessionId}`)}>
            <td><span className={`badge badge-${s.status.toLowerCase()}`}>{s.status}</span></td>
            <td>{s.source && <span className={`badge badge-source-${s.source.toLowerCase()}`}>{s.source}</span>}</td>
            <td className="mono session-id-cell">{s.sessionId}</td>
            <td>{s.machine || "Unknown"}</td>
            <td className="prompt-cell" title={s.lastPrompt}>{formatPrompt(s.lastPrompt)}</td>
            <td>{s.model}</td>
            <td>{s.turns}</td>
            <td>{formatTokens(s.inputTokens + s.outputTokens)}</td>
            <td>{formatDuration(s.durationMs)}</td>
            <td>{timeAgo(s.lastActivity)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function formatPrompt(prompt?: string): string {
  if (!prompt) return "—";
  if (prompt === "<REDACTED>") return "<redacted — set OTEL_LOG_USER_PROMPTS=1>";
  return prompt.length > 90 ? prompt.slice(0, 87) + "…" : prompt;
}
