import { useState } from "react";
import { useAuth } from "../auth/useAuth";
import { getDebugSession } from "../api/client";

export function DebugPage() {
  const { getAccessToken } = useAuth();
  const [sessionId, setSessionId] = useState("");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleQuery = async () => {
    if (!sessionId.trim()) return;
    setLoading(true);
    setError("");
    setData(null);
    try {
      const token = await getAccessToken();
      const d = await getDebugSession(sessionId.trim(), token);
      setData(d);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <h2>Debug Session</h2>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          type="text"
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleQuery()}
          placeholder="Paste session ID..."
          style={{
            flex: 1, padding: "8px 12px",
            background: "var(--bg-secondary)", color: "var(--text-primary)",
            border: "1px solid var(--border)", borderRadius: 6,
            fontFamily: "var(--font-mono)", fontSize: 13,
          }}
        />
        <button
          onClick={handleQuery}
          disabled={loading}
          style={{
            padding: "8px 20px", background: "var(--accent)",
            color: "#fff", border: "none", borderRadius: 6,
            cursor: loading ? "wait" : "pointer", fontSize: 13,
          }}
        >
          {loading ? "Querying..." : "Query"}
        </button>
      </div>
      {error && <div className="error-message">{error}</div>}
      {data && (
        <pre style={{
          padding: 16, background: "var(--bg-secondary)",
          border: "1px solid var(--border)", borderRadius: 8,
          fontSize: 12, fontFamily: "var(--font-mono)",
          maxHeight: "70vh", overflow: "auto", whiteSpace: "pre-wrap",
          color: "var(--text-primary)",
        }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </>
  );
}
