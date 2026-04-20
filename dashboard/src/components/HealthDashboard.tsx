import { useState, useEffect } from "react";
import { getHealth } from "../api/client";
import type { HealthSummary } from "../api/types";
import { formatTokens } from "../utils/format";

export function HealthDashboard() {
  const [health, setHealth] = useState<HealthSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    const load = () => {
      getHealth()
        .then((h) => { if (mounted) setHealth(h); })
        .catch((e) => { if (mounted) setError(e.message); })
        .finally(() => { if (mounted) setLoading(false); });
    };
    load();
    const interval = setInterval(load, 15000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) return <div className="loading">Loading health...</div>;
  if (error) return <div className="error-message">{error}</div>;
  if (!health) return null;

  return (
    <>
      <h2>Health</h2>
      <div className="health-grid">
        <div className="health-card">
          <div className="label">Active Sessions</div>
          <div className="value" style={{ color: "var(--green)" }}>{health.activeSessions}</div>
        </div>
        <div className="health-card">
          <div className="label">Idle Sessions</div>
          <div className="value" style={{ color: "var(--yellow)" }}>{health.idleSessions}</div>
        </div>
        <div className="health-card">
          <div className="label">Total Sessions</div>
          <div className="value">{health.totalSessions}</div>
        </div>
        <div className="health-card">
          <div className="label">Total Tokens</div>
          <div className="value">{formatTokens(health.totalTokens)}</div>
        </div>
      </div>
      <div className="health-grid">
        <div className="health-card">
          <div className="label">Avg Response Time</div>
          <div className="value">{health.avgResponseTime.toFixed(1)}s</div>
        </div>
        <div className="health-card">
          <div className="label">Top Model</div>
          <div className="value" style={{ fontSize: 18 }}>{health.topModel || "N/A"}</div>
        </div>
      </div>
    </>
  );
}
