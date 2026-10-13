import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type GeoFeature, type GeoLayer, type Indicator, type Region } from "../api/client";
import { SyntheticBanner } from "../components/Banners";
import { Legend, MapView } from "../components/MapView";
import { CATEGORY_LABELS, formatValue } from "../format";

const FORECASTABLE = new Set([
  "population_total",
  "enterprises_active",
  "enterprises_new",
  "trade_services_volume",
  "food_services_volume",
  "health_services_volume",
  "market_services_volume",
]);

/** 3D map: regions or districts extruded and coloured by any official indicator. */
export function MapPage() {
  const [params, setParams] = useSearchParams();
  const level = (params.get("level") === "district" ? "district" : "region") as "region" | "district";
  const metric = params.get("metric") ?? "population_total";
  const region = params.get("region") ?? "";
  const focus = useMemo(() => (params.get("focus") ?? "").split(",").filter(Boolean), [params]);

  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [year, setYear] = useState<number | undefined>(undefined);
  const [layer, setLayer] = useState<GeoLayer | null>(null);
  const [extrude, setExtrude] = useState(true);
  const [selected, setSelected] = useState<GeoFeature["properties"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    Promise.all([api.indicators(), api.regions()])
      .then(([i, r]) => {
        setIndicators(i);
        setRegions(r);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  const current = indicators.find((i) => i.code === metric);
  const districtOk = current ? current.levels.includes("district") : true;
  const effLevel = level === "district" && !districtOk ? "region" : level;

  useEffect(() => {
    setLoading(true);
    api
      .geo(effLevel, metric, year, effLevel === "district" && region ? region : undefined)
      .then((l) => {
        setLayer(l);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [effLevel, metric, year, region]);

  const set = (patch: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) p.set(k, v);
      else p.delete(k);
    }
    setParams(p, { replace: true });
  };

  const grouped = useMemo(() => {
    const g: Record<string, Indicator[]> = {};
    for (const i of indicators) (g[i.category] ??= []).push(i);
    return g;
  }, [indicators]);

  const unit = current?.unit ?? "";
  const focusedRows = layer?.features.filter((f) => focus.includes(f.properties.soato)) ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>3D map</h1>
          <p className="muted">
            Height and colour show each territory&apos;s rank for the chosen official indicator. Hover for values, click
            for details.
          </p>
        </div>
      </div>
      <SyntheticBanner show={Boolean(layer?.meta.is_synthetic)} />

      <section className="controls" aria-label="Map options">
        <label className="grow">
          Indicator
          <select
            value={metric}
            onChange={(e) => {
              setYear(undefined);
              set({ metric: e.target.value });
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
          <button type="button" className={effLevel === "region" ? "active" : ""} onClick={() => set({ level: "region", focus: null })}>
            Regions
          </button>
          <button
            type="button"
            className={effLevel === "district" ? "active" : ""}
            disabled={!districtOk}
            title={districtOk ? "" : "No district-level official data for this indicator"}
            onClick={() => set({ level: "district", focus: null })}
          >
            Districts
          </button>
        </div>
        {effLevel === "district" && (
          <label>
            Region
            <select value={region} onChange={(e) => set({ region: e.target.value || null, focus: null })}>
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
          <select value={year ?? layer?.year ?? ""} onChange={(e) => setYear(Number(e.target.value))} disabled={!layer}>
            {(layer?.years_available ?? []).map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <div className="segmented" role="group" aria-label="View">
          <button type="button" className={!extrude ? "active" : ""} onClick={() => setExtrude(false)}>
            2D
          </button>
          <button type="button" className={extrude ? "active" : ""} onClick={() => setExtrude(true)}>
            3D
          </button>
        </div>
      </section>

      {error && <div className="alert">{error}</div>}

      <div className="map-layout">
        <section className="card map-card" aria-busy={loading}>
          <MapView
            layer={layer}
            unit={unit}
            extrude={extrude}
            focus={focus}
            selected={selected?.soato ?? null}
            onSelect={setSelected}
            height="min(68vh, 640px)"
          />
          <Legend layer={layer} unit={unit} />
        </section>

        <aside className="card side-panel" aria-label="Details">
          {selected ? (
            <TerritoryDetails p={selected} unit={unit} metric={metric} year={layer?.year} name={current?.name_en ?? metric} level={effLevel} />
          ) : focusedRows.length ? (
            <>
              <h2>Highlighted by the AI analyst</h2>
              <ol className="plain-list">
                {focusedRows.map((f) => (
                  <li key={f.properties.soato}>
                    <button type="button" className="link" onClick={() => setSelected(f.properties)}>
                      {f.properties.name_en}
                    </button>{" "}
                    <span className="muted">{f.properties.value != null ? formatValue(f.properties.value, unit) : "—"}</span>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <>
              <h2>{current?.name_en ?? "Indicator"}</h2>
              <p className="muted">
                {layer ? `${layer.features.length} territories · ${layer.year}` : "Loading…"}
                {layer?.meta.sources[0]?.siat_dataset_id ? ` · SIAT dataset ${layer.meta.sources[0].siat_dataset_id}` : ""}
              </p>
              <p className="muted small">Click any territory to see its value, rank and links to its trend and forecast.</p>
              <TopList layer={layer} unit={unit} onPick={setSelected} />
            </>
          )}
        </aside>
      </div>
    </>
  );
}

function TopList({ layer, unit, onPick }: { layer: GeoLayer | null; unit: string; onPick: (p: GeoFeature["properties"]) => void }) {
  if (!layer) return null;
  const top = [...layer.features].filter((f) => f.properties.rank != null).sort((a, b) => a.properties.rank! - b.properties.rank!).slice(0, 8);
  return (
    <ol className="plain-list">
      {top.map((f) => (
        <li key={f.properties.soato}>
          <button type="button" className="link" onClick={() => onPick(f.properties)}>
            {f.properties.name_en}
          </button>{" "}
          <span className="muted">{formatValue(f.properties.value!, unit, true)}</span>
        </li>
      ))}
    </ol>
  );
}

function TerritoryDetails({
  p,
  unit,
  metric,
  year,
  name,
  level,
}: {
  p: GeoFeature["properties"];
  unit: string;
  metric: string;
  year?: number;
  name: string;
  level: "region" | "district";
}) {
  const share = typeof p.share === "number" ? p.share : null;
  const approx = p.geom_approx === true || String(p.geom_approx) === "true";
  return (
    <div className="details">
      <p className="eyebrow">{level === "region" ? "Region" : p.kind === "city" ? "City" : "District"}</p>
      <h2>{p.name_en}</h2>
      {p.name_uz && <p className="muted small">{p.name_uz}</p>}
      <dl className="facts">
        <dt>{name}</dt>
        <dd>{p.value != null ? formatValue(Number(p.value), unit) : "No data"}</dd>
        <dt>Rank</dt>
        <dd>{p.rank ?? "—"}</dd>
        {share != null && (
          <>
            <dt>Share of total</dt>
            <dd>{(share * 100).toFixed(1)}%</dd>
          </>
        )}
        <dt>Year</dt>
        <dd>{year ?? "—"}</dd>
      </dl>
      {approx && <p className="muted small">Location is approximate (no official boundary polygon for this district).</p>}
      <div className="stack-actions">
        {FORECASTABLE.has(metric) && (
          <Link className="btn" to={`/forecast?indicator=${metric}&level=${level}&soato=${p.soato}`}>
            Trend &amp; forecast
          </Link>
        )}
        <Link className="btn secondary" to={`/recommend?region=${level === "region" ? p.soato : p.region_soato ?? ""}`}>
          Score businesses here
        </Link>
      </div>
    </div>
  );
}
