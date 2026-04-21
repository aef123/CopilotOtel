import { useState, useEffect } from "react";
import { getSessions } from "../api/client";
import { useAuth } from "../auth/useAuth";
import type { Session } from "../api/types";
import { SessionGrid } from "./SessionGrid";
import { SessionList } from "./SessionList";

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
  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const token = await getAccessToken();
        const data = await getSessions(token);
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
  }, []);

  const toggleView = (v: ViewMode) => {
    setView(v);
    localStorage.setItem("sessionsView", v);
  };

  const filtered = statusFilter === "all"
    ? sessions
    : sessions.filter((s) => s.status.toLowerCase() === statusFilter);

  if (loading) return <div className="loading">Loading sessions...</div>;
  if (error) return <div className="error-message">{error}</div>;

  return (
    <>
      <div className="filters">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All Status</option>
          <option value="active">Active</option>
          <option value="idle">Idle</option>
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
