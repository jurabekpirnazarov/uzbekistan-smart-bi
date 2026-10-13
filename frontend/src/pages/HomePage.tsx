import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type GeoLayer, type Overview } from "../api/client";
import { useChat } from "../App";
import { MapView } from "../components/MapView";
import { formatPct, formatValue } from "../format";

const EXAMPLES = [
  "I have 700 million UZS. Where in Fergana region should I open a bakery?",
  "Toshkent viloyatida dorixona ochish uchun eng yaxshi tuman qaysi?",
  "Сравни Самарканд и Бухару по населению и услугам.",
  "Which regions grew fastest in operating businesses since 2020?",
];

export function HomePage() {
  const { ask } = useChat();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [layer, setLayer] = useState<GeoLayer | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.overview().then(setOverview).catch((e: unknown) => setError(String(e)));
    api.geo("region", "population_total").then(setLayer).catch(() => setLayer(null));
  }, []);

  return (
    <>
      <section className="hero">
        <div className="hero-text">
          <h1>Where should your next business open?</h1>
          <p className="muted">
            Official SIAT statistics for 14 regions and 208 districts and cities, turned into rankings, forecasts and
            a transparent Business Opportunity Score. Ask in English, O‘zbekcha or Русский.
          </p>
          <form
            className="ask-box"
            onSubmit={(e) => {
              e.preventDefault();
              if (q.trim()) ask(q.trim());
            }}
          >
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Ask AI anything about business in Uzbekistan…"
              aria-label="Ask the AI analyst"
            />
            <button type="submit" disabled={!q.trim()}>
              Ask
            </button>
          </form>
          <div className="chips">
            {EXAMPLES.map((e) => (
              <button key={e} type="button" className="chip" onClick={() => ask(e)}>
                {e}
              </button>
            ))}
          </div>
        </div>
        <Link to="/map" className="hero-map" aria-label="Open the 3D map">
          <MapView layer={layer} unit="persons" extrude interactive={false} height={340} />
          <span className="hero-map-label">Population by region · open the 3D map →</span>
        </Link>
      </section>

      {error && <div className="alert">{error}</div>}

      {overview && (
        <section className="kpis" aria-label="Key figures">
          {overview.kpis.map((k) => (
            <div className="kpi" key={k.indicator}>
              <span className="kpi-label">
                {k.label} · {k.year}
              </span>
              <span className="kpi-value">{formatValue(k.value, k.unit, true)}</span>
              <span className={`kpi-change ${k.change_pct !== null && k.change_pct < 0 ? "neg" : "pos"}`}>
                {formatPct(k.change_pct)} vs {k.year - 1}
              </span>
            </div>
          ))}
          <div className="kpi">
            <span className="kpi-label">Territories</span>
            <span className="kpi-value">{overview.regions} regions</span>
            <span className="kpi-change muted">
              {overview.districts} districts · {overview.cities} cities
            </span>
          </div>
        </section>
      )}

      <section className="feature-grid" aria-label="What you can do">
        <Link to="/recommend" className="feature">
          <strong>Recommend a location</strong>
          <span className="muted">11 business types scored for every district, with the full factor breakdown.</span>
        </Link>
        <Link to="/map" className="feature">
          <strong>Explore the 3D map</strong>
          <span className="muted">Any indicator by region or district, with sources on hover.</span>
        </Link>
        <Link to="/forecast" className="feature">
          <strong>Forecast</strong>
          <span className="muted">Backtested models with 80% and 95% intervals — clearly marked as predictions.</span>
        </Link>
        <Link to="/monitoring" className="feature">
          <strong>Monitoring</strong>
          <span className="muted">Data freshness, quality checks, model accuracy, drift and AI usage.</span>
        </Link>
      </section>
    </>
  );
}
