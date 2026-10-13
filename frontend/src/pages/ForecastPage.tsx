import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type District, type Forecast, type Indicator, type Level, type Region } from "../api/client";
import { ModelBadge } from "../components/Banners";
import { ForecastChart } from "../components/ForecastChart";
import { formatValue } from "../format";

const MODEL_NAMES: Record<string, string> = {
  naive_last: "Naive (last value)",
  naive_drift: "Naive drift",
  linear_trend: "Linear trend",
  holt: "Holt damped trend",
  gbm_panel: "Gradient boosting (panel)",
};

export function ForecastPage() {
  const [params, setParams] = useSearchParams();
  const indicator = params.get("indicator") ?? "population_total";
  const level = (params.get("level") ?? "country") as Level;
  const soato = params.get("soato") ?? "1700";

  const [targets, setTargets] = useState<string[]>([]);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [districts, setDistricts] = useState<District[]>([]);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);

  const regionSoato = level === "region" ? soato : level === "district" ? soato.slice(0, 4) : "";

  useEffect(() => {
    Promise.all([api.forecastTargets(), api.indicators(), api.regions()])
      .then(([t, i, r]) => {
        setTargets(t);
        setIndicators(i);
        setRegions(r);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (regionSoato) api.districts(regionSoato).then(setDistricts).catch(() => setDistricts([]));
    else setDistricts([]);
  }, [regionSoato]);

  useEffect(() => {
    api
      .forecast(indicator, level, soato)
      .then((f) => {
        setForecast(f);
        setError(null);
      })
      .catch((e: unknown) => {
        setForecast(null);
        setError(String(e));
      });
  }, [indicator, level, soato]);

  const set = (patch: Record<string, string>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) p.set(k, v);
    setParams(p, { replace: true });
  };
  const ind = indicators.find((i) => i.code === indicator);
  const unit = ind?.unit ?? forecast?.meta.unit ?? "";
  const bt = forecast?.backtest ?? {};

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Forecast</h1>
          <p className="muted">
            Backtested statistical models. Forecasts are <strong>model predictions</strong>, never official statistics.
          </p>
        </div>
      </div>

      <section className="controls" aria-label="Forecast options">
        <label className="grow">
          Indicator
          <select value={indicator} onChange={(e) => set({ indicator: e.target.value })}>
            {targets.map((t) => (
              <option key={t} value={t}>
                {indicators.find((i) => i.code === t)?.name_en ?? t}
              </option>
            ))}
          </select>
        </label>
        <label>
          Region
          <select
            value={regionSoato}
            onChange={(e) => (e.target.value ? set({ level: "region", soato: e.target.value }) : set({ level: "country", soato: "1700" }))}
          >
            <option value="">Uzbekistan (national)</option>
            {regions.map((r) => (
              <option key={r.soato} value={r.soato}>
                {r.name_en}
              </option>
            ))}
          </select>
        </label>
        {regionSoato && (
          <label>
            District / city
            <select
              value={level === "district" ? soato : ""}
              onChange={(e) =>
                e.target.value ? set({ level: "district", soato: e.target.value }) : set({ level: "region", soato: regionSoato })
              }
            >
              <option value="">Whole region</option>
              {districts.map((d) => (
                <option key={d.soato} value={d.soato}>
                  {d.name_en}
                </option>
              ))}
            </select>
          </label>
        )}
      </section>

      {error && <div className="alert">{error}</div>}

      {forecast && (
        <div className="grid">
          <section className="card">
            <div className="card-head">
              <div>
                <h2>
                  {ind?.name_en ?? indicator} · {forecast.name}
                </h2>
                <p className="muted">
                  History {forecast.history[0]?.year}–{forecast.history[forecast.history.length - 1]?.year} · forecast to{" "}
                  {forecast.forecast[forecast.forecast.length - 1]?.year}
                </p>
              </div>
              <ModelBadge />
            </div>
            <ForecastChart f={forecast} unit={unit} />
            {forecast.low_confidence && (
              <div className="banner warn">
                Low confidence: only {forecast.history_points} yearly points of history (services data starts in 2020).
              </div>
            )}
          </section>

          <section className="card">
            <h2>Model</h2>
            <dl className="facts">
              <dt>Selected model</dt>
              <dd>{MODEL_NAMES[forecast.model] ?? forecast.model}</dd>
              <dt>Backtest sMAPE (1 year ahead)</dt>
              <dd>{bt.smape_h1 != null ? `${bt.smape_h1.toFixed(2)}%` : "—"}</dd>
              <dt>Backtest sMAPE (2 years ahead)</dt>
              <dd>{bt.smape_h2 != null ? `${bt.smape_h2.toFixed(2)}%` : "—"}</dd>
              <dt>vs naive baseline (1 year)</dt>
              <dd>{improvementText(forecast.model, bt.improvement_vs_naive_pct_h1)}</dd>
            </dl>
            <table className="compact">
              <thead>
                <tr>
                  <th scope="col">Year</th>
                  <th scope="col" className="num">
                    Forecast
                  </th>
                  <th scope="col" className="num">
                    80% interval
                  </th>
                </tr>
              </thead>
              <tbody>
                {forecast.forecast.map((p) => (
                  <tr key={p.year}>
                    <td>{p.year}</td>
                    <td className="num">{formatValue(p.yhat, unit)}</td>
                    <td className="num">
                      {p.lo80 != null && p.hi80 != null ? `${formatValue(p.lo80, unit, true)} – ${formatValue(p.hi80, unit, true)}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">
              {forecast.note} Intervals come from backtest errors (rolling origin, last 3 years) and widen with the
              horizon. Source of history: SIAT dataset {forecast.meta.sources[0]?.siat_dataset_id ?? "—"}.
            </p>
          </section>
        </div>
      )}
    </>
  );
}

function improvementText(model: string, pct: number | null | undefined): string {
  if (model === "naive_last") return "this is the naive baseline";
  if (pct == null) return "—";
  return `${Math.abs(pct).toFixed(1)}% ${pct >= 0 ? "lower" : "higher"} error than naive`;
}
