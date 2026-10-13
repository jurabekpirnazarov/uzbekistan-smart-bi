import { useEffect, useState } from "react";
import {
  api,
  type MonitoringAgent,
  type MonitoringData,
  type MonitoringModels,
  type MonitoringReco,
} from "../api/client";

const fmtDate = (s: string | null | undefined) => (s ? new Date(s).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—");
const STATUS_LABEL: Record<string, string> = {
  ok: "✓ updated",
  no_change: "✓ no new data",
  failed: "✕ failed",
  running: "… running",
};
const ms = (v: number | null) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);

export function MonitoringPage() {
  const [data, setData] = useState<MonitoringData | null>(null);
  const [models, setModels] = useState<MonitoringModels | null>(null);
  const [reco, setReco] = useState<MonitoringReco | null>(null);
  const [agent, setAgent] = useState<MonitoringAgent | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    Promise.all([api.monitoring.data(), api.monitoring.models(), api.monitoring.recommendations(), api.monitoring.agent()])
      .then(([d, m, r, a]) => {
        setData(d);
        setModels(m);
        setReco(r);
        setAgent(a);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)));
  };
  useEffect(load, []);

  const failed = data?.quality_checks.filter((c) => !c.passed).length ?? 0;
  const driftAlerts = models?.drift.filter((d) => d.alert).length ?? 0;
  const selected = models?.leaderboard.filter((r) => r.selected) ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Monitoring</h1>
          <p className="muted">
            Data freshness and quality, forecast accuracy and drift, recommendation stability, and AI analyst usage.
            Batch metrics refresh with <code>python manage.py monitor</code>.
          </p>
        </div>
        <div className="stack-actions">
          <button type="button" className="btn secondary" onClick={load}>
            Refresh
          </button>
          <a className="btn secondary" href="http://localhost:5000" target="_blank" rel="noreferrer">
            MLflow
          </a>
          <a className="btn secondary" href="http://localhost:8000/metrics" target="_blank" rel="noreferrer">
            /metrics
          </a>
        </div>
      </div>
      {error && <div className="alert">{error}</div>}

      <section className="kpis" aria-label="Health summary">
        <Kpi label="Observations" value={data ? data.observations.toLocaleString("en-US") : "—"} sub={`data age ${data?.age_days ?? "—"} days`} />
        <Kpi
          label="Quality checks"
          value={data ? `${data.quality_checks.length - failed}/${data.quality_checks.length}` : "—"}
          sub={failed ? `${failed} failing` : "all passing"}
          bad={failed > 0}
        />
        <Kpi label="Drift alerts (PSI > 0.2)" value={models ? String(driftAlerts) : "—"} sub={`${models?.drift.length ?? 0} features checked`} bad={driftAlerts > 0} />
        <Kpi label={`AI runs (${agent?.window_days ?? 7} days)`} value={agent ? String(agent.runs) : "—"} sub={agent ? `p95 ${ms(agent.p95_ms)}` : ""} />
        <Kpi
          label="Unverified numbers"
          value={agent ? String(agent.verification_failures) : "—"}
          sub="in AI answers"
          bad={(agent?.verification_failures ?? 0) > 0}
        />
      </section>

      <section className="card pipeline-card">
        <div className="card-head">
          <div>
            <h2>Data refresh pipeline</h2>
            <p className="muted small">
              Every {data?.pipeline.every_days ?? "—"} day(s) at {data?.pipeline.at ?? "—"} · next run after{" "}
              {fmtDate(data?.pipeline.next_due_after)} · run now with <code>python manage.py refresh</code>
            </p>
          </div>
        </div>
        <div className="table-scroll">
          <table className="compact">
            <thead>
              <tr>
                <th scope="col">Started</th>
                <th scope="col">Trigger</th>
                <th scope="col">Status</th>
                <th scope="col">New SIAT datasets</th>
                <th scope="col">Steps</th>
              </tr>
            </thead>
            <tbody>
              {data?.pipeline.runs.length ? (
                data.pipeline.runs.map((r) => (
                  <tr key={r.started_at} className={r.status === "failed" ? "alert-row" : ""}>
                    <td>{fmtDate(r.started_at)}</td>
                    <td>{r.trigger}</td>
                    <td title={r.error ?? ""}>{STATUS_LABEL[r.status] ?? r.status}</td>
                    <td>{r.datasets_changed.length ? r.datasets_changed.join(", ") : "none"}</td>
                    <td className="muted">
                      {r.steps.map((s) => `${s.name}${s.status === "ok" ? "" : ` (${s.status})`}`).join(" → ")}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="muted">
                    No runs yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <div className="mon-grid">
        <section className="card">
          <h2>Data health</h2>
          <p className="muted small">
            Last retrieved {fmtDate(data?.last_retrieved_at)} · snapshot {fmtDate(data?.snapshot_at)}
          </p>
          <ul className="checks">
            {data?.quality_checks.map((c) => (
              <li key={c.check} className={c.passed ? "ok" : "bad"}>
                {c.passed ? "✓" : "✕"} {c.check.split("_").join(" ")}
              </li>
            ))}
          </ul>
          <h3>Missing district-year cells</h3>
          <table className="compact">
            <tbody>
              {data?.missing_ratio.slice(0, 6).map((m) => (
                <tr key={m.indicator}>
                  <td>{m.indicator}</td>
                  <td className="num">{(m.ratio * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Ingestion runs</h3>
          <table className="compact">
            <tbody>
              {data?.ingestion_runs.slice(0, 4).map((r) => (
                <tr key={r.started_at}>
                  <td>{fmtDate(r.started_at)}</td>
                  <td>{r.status}</td>
                  <td className="num">{r.rows_loaded.toLocaleString("en-US")} rows</td>
                  <td className="num">{r.rows_rejected} rejected</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card">
          <h2>Forecast models</h2>
          <p className="muted small">
            Run {models?.run_id ?? "—"} · trained {fmtDate(models?.trained_at)}
          </p>
          <div className="table-scroll">
            <table className="compact">
              <thead>
                <tr>
                  <th scope="col">Indicator</th>
                  <th scope="col">Level</th>
                  <th scope="col">Model</th>
                  <th scope="col" className="num">
                    sMAPE h1
                  </th>
                  <th scope="col" className="num">
                    vs naive
                  </th>
                </tr>
              </thead>
              <tbody>
                {selected.map((r) => (
                  <tr key={`${r.indicator}-${r.level}`}>
                    <td>{r.indicator}</td>
                    <td>{r.level}</td>
                    <td>{r.model}</td>
                    <td className="num">{r.smape_h1 != null ? `${r.smape_h1.toFixed(1)}%` : "—"}</td>
                    <td className="num">
                      {r.improvement_vs_naive_pct_h1 != null && r.model !== "naive_last"
                        ? `${r.improvement_vs_naive_pct_h1 >= 0 ? "−" : "+"}${Math.abs(r.improvement_vs_naive_pct_h1).toFixed(0)}%`
                        : "base"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Realised error of last year&apos;s forecast</h3>
          <table className="compact">
            <tbody>
              {models?.realised_error.map((r) => (
                <tr key={r.indicator}>
                  <td>{r.indicator}</td>
                  <td>{r.model}</td>
                  <td className="num">MAPE {r.mape.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Feature drift (PSI, previous vs latest year)</h3>
          <table className="compact">
            <tbody>
              {models?.drift.map((d) => (
                <tr key={d.feature} className={d.alert ? "alert-row" : ""}>
                  <td>{d.feature}</td>
                  <td className="muted">{d.years}</td>
                  <td className="num">
                    {d.psi.toFixed(3)} {d.alert ? "⚠" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card">
          <h2>AI analyst</h2>
          <dl className="facts">
            <dt>Runs / errors</dt>
            <dd>
              {agent?.runs ?? "—"} / {agent?.errors ?? "—"}
            </dd>
            <dt>Rule-based (no key) runs</dt>
            <dd>{agent?.fallback_runs ?? "—"}</dd>
            <dt>Latency p50 / p95</dt>
            <dd>
              {ms(agent?.p50_ms ?? null)} / {ms(agent?.p95_ms ?? null)}
            </dd>
            <dt>Tokens / est. cost</dt>
            <dd>
              {agent?.tokens.toLocaleString("en-US") ?? "—"} / ${agent?.cost_usd.toFixed(4) ?? "—"}
            </dd>
          </dl>
          <h3>Tool calls</h3>
          <table className="compact">
            <tbody>
              {agent?.tools.map((t) => (
                <tr key={t.tool}>
                  <td>{t.tool}</td>
                  <td className="num">{t.calls}</td>
                  <td className="num">{t.failures ? `${t.failures} failed` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Recent questions</h3>
          <ul className="recent">
            {agent?.recent.slice(0, 8).map((r) => (
              <li key={r.created_at}>
                <span>{r.question}</span>
                <span className="muted small-inline">
                  {r.lang} · {r.mode} · {r.status} · {ms(r.latency_ms)} · {r.tool_count} tools
                  {r.verification_failures ? ` · ⚠ ${r.verification_failures} unverified` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="card">
          <h2>Recommendations</h2>
          <dl className="facts">
            <dt>Feedback</dt>
            <dd>
              👍 {reco?.feedback.up ?? 0} · 👎 {reco?.feedback.down ?? 0}
            </dd>
          </dl>
          <h3>Requests by business type</h3>
          <table className="compact">
            <tbody>
              {reco?.requests.map((r) => (
                <tr key={r.business_type}>
                  <td>{r.business_type}</td>
                  <td className="num">{r.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Stability (top-5 Jaccard vs previous run)</h3>
          <table className="compact">
            <tbody>
              {reco?.stability.map((s) => (
                <tr key={s.business_type}>
                  <td>{s.business_type}</td>
                  <td className="num">{s.jaccard.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </>
  );
}

function Kpi({ label, value, sub, bad = false }: { label: string; value: string; sub?: string; bad?: boolean }) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      <span className={`kpi-change ${bad ? "neg" : "muted"}`}>{sub}</span>
    </div>
  );
}
