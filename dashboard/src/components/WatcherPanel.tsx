import { useEffect, useState } from "react";
import { getWatcherState } from "../api/client";
import type { WatcherSession } from "../api/types";
import { useAuth } from "../auth/useAuth";

/**
 * Live + orphan sessions reported by the copilot-session-watcher daemon.
 * Sourced from Loki via /dashboard-api/sessions/state. Polls every 10s.
 *
 * "Live" means the daemon currently sees a healthy pidfile + alive owning PID.
 * "Orphan" means the pidfile/lock is on disk but the owning process is gone.
 */
export function WatcherPanel() {
  const { getAccessToken } = useAuth();
  const [sessions, setSessions] = useState<WatcherSession[] | null>(null);
  const [queriedAt, setQueriedAt] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const token = await getAccessToken();
        const data = await getWatcherState(token);
        if (!mounted) return;
        setSessions(data.sessions);
        setQueriedAt(data.queriedAt);
        setError(data.error ?? "");
      } catch (e: any) {
        if (mounted) setError(e.message);
      }
    };
    load();
    const t = setInterval(load, 10000);
    return () => { mounted = false; clearInterval(t); };
  }, []);

  if (sessions === null && !error) {
    return <div className="watcher-panel loading">Loading watcher state...</div>;
  }

  const live = (sessions ?? []).filter((s) =>
    s.state === "live" || s.state === "active" || s.state === "idle");
  const orphan = (sessions ?? []).filter((s) => s.state === "orphan");
  const byHostLive = countBy(live, (s) => s.host);
  const byHostOrphan = countBy(orphan, (s) => s.host);

  return (
    <div className="watcher-panel">
      <div className="watcher-header">
        <h2>Watcher</h2>
        <div className="watcher-summary">
          <span className="badge badge-live">{live.length} live</span>
          <span className="badge badge-orphan">{orphan.length} orphan</span>
          {queriedAt && <span className="watcher-stamp">at {formatTime(queriedAt)}</span>}
        </div>
      </div>
      {error && <div className="watcher-error">{error}</div>}
      {sessions && sessions.length === 0 && !error && (
        <div className="watcher-empty">No watcher sessions in the last 5 min.</div>
      )}
      {sessions && sessions.length > 0 && (
        <>
          <div className="watcher-host-rows">
            {Object.keys({ ...byHostLive, ...byHostOrphan }).sort().map((host) => (
              <div className="watcher-host-row" key={host}>
                <span className="watcher-host-name">{host}</span>
                {byHostLive[host] > 0 && (
                  <span className="badge badge-live">{byHostLive[host]} live</span>
                )}
                {byHostOrphan[host] > 0 && (
                  <span className="badge badge-orphan">{byHostOrphan[host]} orphan</span>
                )}
              </div>
            ))}
          </div>
          <table className="data-table compact">
            <thead>
              <tr>
                <th>Tool</th>
                <th>State</th>
                <th>Host</th>
                <th>Session ID</th>
                <th>Last seen (s)</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={`${s.host}|${s.sessionId}|${s.epoch}`}>
                  <td><span className={`tool-badge tool-${s.tool}`}>{s.tool}</span></td>
                  <td><span className={`state-badge state-${s.state}`}>{s.state}</span></td>
                  <td>{s.host}</td>
                  <td className="mono">{short(s.sessionId)}</td>
                  <td>{s.lastObservedAgeSeconds}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function countBy<T>(items: T[], key: (t: T) => string): Record<string, number> {
  const acc: Record<string, number> = {};
  for (const it of items) {
    const k = key(it);
    acc[k] = (acc[k] ?? 0) + 1;
  }
  return acc;
}

function short(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString();
  } catch {
    return iso;
  }
}
