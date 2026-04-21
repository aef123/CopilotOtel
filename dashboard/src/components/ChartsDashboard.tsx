import { useState, useEffect } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, PieChart, Pie, Cell, Legend,
} from "recharts";
import { getTokenUsage, getModelUsage, getToolUsage } from "../api/client";
import { useAuth } from "../auth/useAuth";
import type { TokenUsagePoint, ModelUsage, ToolUsage } from "../api/types";

const COLORS = ["#a855f7", "#4ade80", "#facc15", "#f87171", "#58a6ff", "#c084fc", "#06d6a0"];

export function ChartsDashboard() {
  const { getAccessToken } = useAuth();
  const [tokenData, setTokenData] = useState<TokenUsagePoint[]>([]);
  const [modelData, setModelData] = useState<ModelUsage[]>([]);
  const [toolData, setToolData] = useState<ToolUsage[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getAccessToken().then((token) =>
      Promise.all([getTokenUsage(token), getModelUsage(token), getToolUsage(token)])
        .then(([t, m, tl]) => {
          setTokenData(t);
          setModelData(m);
          setToolData(tl);
        })
        .finally(() => setLoading(false))
    );
  }, []);

  if (loading) return <div className="loading">Loading charts...</div>;

  const style = getComputedStyle(document.documentElement);
  const textMuted = style.getPropertyValue("--text-muted").trim() || "#9990b8";
  const border = style.getPropertyValue("--border").trim() || "#2d2854";
  const accent = style.getPropertyValue("--accent").trim() || "#a855f7";
  const green = style.getPropertyValue("--green").trim() || "#4ade80";

  return (
    <>
      <h2>Charts</h2>

      <div className="charts-row-full">
        <div className="chart-card">
          <div className="chart-card-title">Token Usage Over Time</div>
          {tokenData.length === 0 ? (
            <div className="chart-empty">No token data yet</div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={tokenData}>
                <CartesianGrid strokeDasharray="3 3" stroke={border} />
                <XAxis
                  dataKey="timestamp"
                  tick={{ fill: textMuted, fontSize: 11 }}
                  tickFormatter={(v) => new Date(v).toLocaleTimeString()}
                />
                <YAxis tick={{ fill: textMuted, fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-surface)", border: `1px solid ${border}`, color: "var(--text)" }}
                />
                <Line type="monotone" dataKey="input" stroke={accent} strokeWidth={2} dot={false} name="Input" />
                <Line type="monotone" dataKey="output" stroke={green} strokeWidth={2} dot={false} name="Output" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="charts-row">
        <div className="chart-card">
          <div className="chart-card-title">Tokens by Model</div>
          {modelData.length === 0 ? (
            <div className="chart-empty">No model data</div>
          ) : (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={modelData}
                  dataKey="totalInput"
                  nameKey="model"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  label={(props: any) => props.name || props.model || ""}
                >
                  {modelData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Legend />
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="chart-card">
          <div className="chart-card-title">Top Tools</div>
          {toolData.length === 0 ? (
            <div className="chart-empty">No tool data</div>
          ) : (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={toolData.slice(0, 10)} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke={border} />
                <XAxis type="number" tick={{ fill: textMuted, fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="tool"
                  width={120}
                  tick={{ fill: textMuted, fontSize: 11 }}
                />
                <Tooltip
                  contentStyle={{ background: "var(--bg-surface)", border: `1px solid ${border}`, color: "var(--text)" }}
                />
                <Bar dataKey="count" fill={accent} radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </>
  );
}
