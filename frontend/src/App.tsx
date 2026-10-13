import { useEffect, useMemo, useState } from "react";
import {
  api,
  type HealthStatus,
  type Indicator,
  type Level,
  type Overview,
  type Ranking,
  type Region,
  type TimeSeries,
} from "./api/client";
import { RankingChart } from "./components/RankingChart";
import { TrendChart } from "./components/TrendChart";
import { formatPct, formatValue, unitLabel } from "./format";

type Selected = { level: Level; soato: string };

const CATEGORY_LABELS: Record<string, string> = {
  population: "Population",
  business: "Business activity",
  services: "Market services",
  health: "Health facilities",
  economy: "Economy",
};

export function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [indicator, setIndicator] = useState("population_total");
  const [level, setLevel] = useState<"region" | "district">("region");
  const [region, setRegion] = useState("");
  const [year, setYear] = useState<number | undefined>(undefined);

  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [loadingRanking, setLoadingRanking] = useState(false);
  const [selected, setSelected] = useState<Selected>({ level: "country", soato: "1700" });
  const [series, setSeries] = useState<TimeSeries | null>(null);

  // Initial load: health, KPIs, catalogue.
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    Promise.all([api.overview(), api.indicators(), api.regions()])
      .then(([o, i, r]) => {
        setOverview(o);
        setIndicators(i);
        setRegions(r);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  const current = indicators.find((i) => i.code === indicator);
  const districtLevelAvailable = current?.levels.includes("district") ?? false;
  const effectiveLevel = level === "district" && !districtLevelAvailable ? "region" : level;

  // Ranking for the current selection.
  useEffect(() => {
    if (!indicators.length) return;
    setLoadingRanking(true);
    api
      .ranking(indicator, effectiveLevel, year, effectiveLevel === "district" && region ? region : undefined)
      .then((r) => {
        setRanking(r);
        setError(null);
      })
      .catch((e: unknown) => {
        setRanking(null);
        setError(String(e));
      })
      .finally(() => setLoadingRanking(false));
  }, [indicator, effectiveLevel, region, year, indicators.length]);

  // Trend for the selected territory (country by default).
  useEffect(() => {
    if (!indicators.length) return;
    const lv = current?.levels.includes(selected.level) ? selected.level : "country";
    const soato = lv === selected.level ? selected.soato : "1700";
    api
      .timeseries(indicator, lv, soato)
      .then(setSeries)
      .catch(() => setSeries(null));
  }, [indicator, selected, indicators.length, current]);

  const grouped = useMemo(() => {
    const g: Record<string, Indicator[]> = {};
    for (const i of indicators) (g[i.category] ??= []).push(i);
    return g;
  }, [indicators]);

  const unit = current?.unit ?? "";
  const source = ranking?.meta.sources[0];

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">Official SIAT statistics</p>
          <h1>Uzbekistan Smart Business Intelligence</h1>
        </div>
        <StatusPill health={health} />
      </header>

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

      <section className="controls" aria-label="Filters">
        <label>
          Indicator
          <select
            value={indicator}
            onChange={(e) => {
              setIndicator(e.target.value);
              setYear(undefined);
            }}
          >
            {Object.entries(grouped).map(([cat, list]) => (
              <optgroup key={cat} label={CATEGORY_LABELS[cat] ?? cat}>
                {list.map((i) => (
                  <option key={i.code} value={i.code}>
                    {i.name_en}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>

        <div className="segmented" role="group" aria-label="Level">
          <button
            type="button"
            className={effectiveLevel === "region" ? "active" : ""}
            onClick={() => setLevel("region")}
          >
            Regions
          </button>
          <button
            type="button"
            className={effectiveLevel === "district" ? "active" : ""}
            disabled={!districtLevelAvailable}
            title={districtLevelAvailable ? "" : "No district-level official data for this indicator"}
            onClick={() => setLevel("district")}
          >
            Districts
          </button>
        </div>

        {effectiveLevel === "district" && (
          <label>
            Region
            <select value={region} onChange={(e) => setRegion(e.target.value)}>
              <option value="">All regions</option>
              {regions.map((r) => (
                <option key={r.soato} value={r.soato}>
                  {r.name_en}
                </option>
              ))}
            </select>
          </label>
        )}

        <label>
          Year
          <select
            value={year ?? ranking?.year ?? ""}
            onChange={(e) => setYear(Number(e.target.value))}
            disabled={!ranking}
          >
            {(ranking?.years_available ?? []).map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
      </section>

      {error && <div className="alert">{error}</div>}

      <main className="grid">
        <section className="card ranking" aria-busy={loadingRanking}>
          <div className="card-head">
            <div>
              <h2>{current?.name_en ?? "…"}</h2>
              <p className="muted">
                {ranking ? `${ranking.items.length} ${effectiveLevel === "region" ? "regions" : "territories"}` : ""}
                {ranking ? ` · ${ranking.year} · ${unitLabel(unit)}` : ""}
              </p>
            </div>
            {ranking?.total != null && (
              <div className="total">
                <span className="muted">Total</span>
                <strong>{formatValue(ranking.total, unit, true)}</strong>
              </div>
            )}
          </div>
          {ranking && (
            <RankingChart
              items={ranking.items.slice(0, 15)}
              unit={unit}
              selected={selected.level === effectiveLevel ? selected.soato : null}
              onSelect={(soato) => setSelected({ level: effectiveLevel, soato })}
            />
          )}
          {ranking && ranking.items.length > 15 && (
            <p className="muted small">Chart shows the top 15. The table below lists all.</p>
          )}
        </section>

        <section className="card trend">
          <div className="card-head">
            <div>
              <h2>Trend · {series?.name ?? "…"}</h2>
              <p className="muted">{series?.meta.period ?? ""}</p>
            </div>
            {selected.level !== "country" && (
              <button type="button" className="link" onClick={() => setSelected({ level: "country", soato: "1700" })}>
                Show national
              </button>
            )}
          </div>
          {series && series.points.length > 0 ? (
            <TrendChart points={series.points} unit={unit} />
          ) : (
            <p className="muted">No time series available.</p>
          )}
          <p className="muted small">Click a bar or a table row to see its trend.</p>
        </section>

        <section className="card table-card">
          <table>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Territory</th>
                {effectiveLevel === "district" && <th scope="col">Type</th>}
                <th scope="col" className="num">
                  Value
                </th>
                {ranking?.total != null && (
                  <th scope="col" className="num">
                    Share
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {ranking?.items.map((r) => (
                <tr
                  key={r.soato}
                  className={selected.soato === r.soato ? "selected" : ""}
                  onClick={() => setSelected({ level: effectiveLevel, soato: r.soato })}
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && setSelected({ level: effectiveLevel, soato: r.soato })}
                >
                  <td>{r.rank}</td>
                  <td>{r.name}</td>
                  {effectiveLevel === "district" && <td className="muted">{r.kind}</td>}
                  <td className="num">{formatValue(r.value, unit)}</td>
                  {ranking.total != null && (
                    <td className="num">{r.share != null ? `${(r.share * 100).toFixed(1)}%` : "—"}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </main>

      <footer className="footer">
        <span>
          Source:{" "}
          {source?.url ? (
            <a href={source.url} target="_blank" rel="noreferrer">
              SIAT dataset {source.siat_dataset_id}
            </a>
          ) : (
            "SIAT (siat.stat.uz)"
          )}
          {current?.source_name ? ` — ${current.source_name}` : ""}
        </span>
        {ranking?.meta.retrieved_at && (
          <span>Retrieved {new Date(ranking.meta.retrieved_at).toLocaleDateString("en-GB")}</span>
        )}
        <span>Official statistics only — no synthetic data shown.</span>
      </footer>
    </div>
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
