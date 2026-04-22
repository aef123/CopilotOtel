import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { SessionsPage } from "./components/SessionsPage";
import { SessionDetail } from "./components/SessionDetail";
import { TraceDetail } from "./components/TraceDetail";
import { ChartsDashboard } from "./components/ChartsDashboard";
import { DebugPage } from "./components/DebugPage";

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter basename="/dashboard">
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<SessionsPage />} />
            <Route path="sessions/:sessionId" element={<SessionDetail />} />
            <Route path="sessions/:sessionId/traces/:traceId" element={<TraceDetail />} />
            <Route path="charts" element={<ChartsDashboard />} />
            <Route path="debug" element={<DebugPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
