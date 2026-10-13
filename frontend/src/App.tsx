import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { api, type HealthStatus, type MapFocus } from "./api/client";
import { type AskRequest, ChatPanel } from "./components/ChatPanel";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { ForecastPage } from "./pages/ForecastPage";
import { HomePage } from "./pages/HomePage";
import { MapPage } from "./pages/MapPage";
import { MonitoringPage } from "./pages/MonitoringPage";
import { RecommendPage } from "./pages/RecommendPage";

interface ChatApi {
  ask: (question?: string) => void;
  showOnMap: (focus: MapFocus) => void;
}

const ChatContext = createContext<ChatApi>({ ask: () => undefined, showOnMap: () => undefined });
export const useChat = () => useContext(ChatContext);

const NAV = [
  { to: "/", label: "Home", end: true },
  { to: "/map", label: "Map" },
  { to: "/recommend", label: "Recommend" },
  { to: "/analytics", label: "Analytics" },
  { to: "/forecast", label: "Forecast" },
  { to: "/monitoring", label: "Monitoring" },
];

export function App() {
  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  );
}

function Layout() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthStatus | null>(null);
  // ?ask=... opens the AI analyst with that question (shareable question links)
  const [request, setRequest] = useState<AskRequest | null>(() => {
    const q = new URLSearchParams(window.location.search).get("ask");
    return q ? { id: 1, text: q } : null;
  });
  const [chatOpen, setChatOpen] = useState(Boolean(request));

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const ask = useCallback((q?: string) => {
    setRequest({ id: Date.now(), text: q });
    setChatOpen(true);
  }, []);
  const showOnMap = useCallback(
    (f: MapFocus) => {
      const p = new URLSearchParams({ level: f.level, focus: f.soatos.join(",") });
      if (f.region) p.set("region", f.region);
      navigate(`/map?${p.toString()}`);
    },
    [navigate],
  );
  const ctx = useMemo(() => ({ ask, showOnMap }), [ask, showOnMap]);

  return (
    <ChatContext.Provider value={ctx}>
      <div className="shell">
        <header className="topbar">
          <NavLink to="/" className="brand" aria-label="Home">
            <span className="brand-mark" aria-hidden="true">◆</span>
            <span>
              <span className="eyebrow">Official SIAT statistics</span>
              <span className="brand-name">Uzbekistan Smart BI</span>
            </span>
          </NavLink>
          <nav className="nav" aria-label="Main">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="topbar-actions">
            <StatusPill health={health} />
            <button type="button" className="ask-btn" onClick={() => ask()}>
              ✦ Ask AI analyst
            </button>
          </div>
        </header>

        <main className="page">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/recommend" element={<RecommendPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/forecast" element={<ForecastPage />} />
            <Route path="/monitoring" element={<MonitoringPage />} />
            <Route path="*" element={<p className="muted">Page not found.</p>} />
          </Routes>
        </main>

        <footer className="footer">
          <span>
            Source: <a href="https://siat.stat.uz" target="_blank" rel="noreferrer">SIAT — State Statistics Committee</a>.
            Official statistics, model predictions and AI interpretation are always shown separately.
          </span>
          <span>Scores and forecasts are decision support, not a guarantee.</span>
        </footer>

        {!chatOpen && (
          <button type="button" className="fab" onClick={() => ask()} aria-label="Open AI analyst">
            ✦ Ask AI
          </button>
        )}
        <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} request={request} onShowMap={showOnMap} />
      </div>
    </ChatContext.Provider>
  );
}

function StatusPill({ health }: { health: HealthStatus | null }) {
  const ok = health?.db === "ok";
  const text = !health ? "API offline" : ok ? `Live · v${health.version}` : "Database offline";
  return (
    <span className={`pill ${ok ? "ok" : "bad"}`}>
      <span className="dot" aria-hidden="true" />
      {text}
    </span>
  );
}
