import { useState, useEffect } from "react";
import { getSessions, getLookback, setLookback, LOOKBACK_OPTIONS } from "../api/client";
import type { LookbackWindow } from "../api/client";
import { useAuth } from "../auth/useAuth";
import type { Session } from "../api/types";
import { SessionGrid } from "./SessionGrid";
import { SessionList } from "./SessionList";
import { WatcherPanel } from "./WatcherPanel";

type ViewMode = "grid" | "list";

export function SessionsPage() {
  const { getAccessToken } = useAuth();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState<ViewMode>(
    () => (localStorage.getItem("sessionsView") as ViewMode) || "grid"
  );
  const [statusFilter, setStatusFilter] = useState("all");
  const [lookback, setLookbackState] = useState<LookbackWindow>(getLookback);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const token = await getAccessToken();
        const data = await getSessions(token, lookback);
        if (mounted) setSessions(data);
      } catch (e: any) {
        if (mounted) setError(e.message);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 10000);
    return () => { mounted = false; clearInterval(interval); };
  }, [lookback]);

  const toggleView = (v: ViewMode) => {
    setView(v);
    localStorage.setItem("sessionsView", v);
  };

  const handleLookback = (v: LookbackWindow) => {
    setLookbackState(v);
    setLookback(v);
    setLoading(true);
  };

  const filtered = statusFilter === "all"
    ? sessions
    : sessions.filter((s) => s.status.toLowerCase() === statusFilter);

  if (loading) return <div className="loading">Loading sessions...</div>;
  if (error) return <div className="error-message">{error}</div>;

  return (
    <>
      <WatcherPanel />
      <div className="filters">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All Status</option>
          <option value="responding">Responding</option>
          <option value="active">Active</option>
          <option value="idle">Idle</option>
        </select>
        <select value={lookback} onChange={(e) => handleLookback(e.target.value as LookbackWindow)}>
          {LOOKBACK_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <div className="view-tabs">
          <button className={`view-tab ${view === "grid" ? "active" : ""}`} onClick={() => toggleView("grid")}>
            Grid
          </button>
          <button className={`view-tab ${view === "list" ? "active" : ""}`} onClick={() => toggleView("list")}>
            List
          </button>
        </div>
      </div>
      {view === "grid" ? <SessionGrid sessions={filtered} /> : <SessionList sessions={filtered} />}
    </>
  );
}
