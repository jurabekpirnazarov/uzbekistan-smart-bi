import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type BusinessType, type Recommendation, type RecoResult, type Region, type Target } from "../api/client";
import { useChat } from "../App";
import { ModelBadge, SyntheticBanner } from "../components/Banners";
import { formatFeature, formatUzs } from "../format";

// One colour per factor position (design palette first, then neutrals).
const FACTOR_COLORS = ["#1f3f7a", "#3fb8af", "#e3a72f", "#6b8fd6", "#8fd0ca", "#c98b2a", "#9aa7bd", "#c8423a"];
const TARGETS: { value: Target | ""; label: string }[] = [
  { value: "", label: "Balanced (profile weights)" },
  { value: "high_growth", label: "High growth" },
  { value: "stable_demand", label: "Stable demand" },
  { value: "low_competition", label: "Low competition" },
];

export function RecommendPage() {
  const [params, setParams] = useSearchParams();
  const { showOnMap } = useChat();
  const [types, setTypes] = useState<BusinessType[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [businessType, setBusinessType] = useState(params.get("business_type") ?? "bakery");
  const [region, setRegion] = useState(params.get("region") ?? "");
  const [budget, setBudget] = useState(params.get("budget") ?? "");
  const [target, setTarget] = useState<Target | "">((params.get("target") as Target) ?? "");
  const [result, setResult] = useState<Recommendation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [voted, setVoted] = useState<1 | -1 | null>(null);

  useEffect(() => {
    Promise.all([api.businessTypes(), api.regions()])
      .then(([t, r]) => {
        setTypes(t);
        setRegions(r);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  const run = (bt = businessType, rg = region, bd = budget, tg = target) => {
    setLoading(true);
    setVoted(null);
    const p = new URLSearchParams({ business_type: bt });
    if (rg) p.set("region", rg);
    if (bd) p.set("budget", bd);
    if (tg) p.set("target", tg);
    setParams(p, { replace: true });
    api
      .recommend({
        business_type: bt,
        region: rg || null,
        budget_uzs: bd ? Number(bd) : null,
        target: tg || null,
        limit: 15,
      })
      .then((r) => {
        setResult(r);
        setError(null);
        setOpen(r.results[0]?.entity.soato ?? null);
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  // run once on load (URL parameters pre-fill the form; e.g. links from the map)
  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const profile = types.find((t) => t.business_type === businessType);
  const factorOrder = profile?.factors.map((f) => f.feature) ?? [];
  const regionName = regions.find((r) => r.soato === result?.scope.region_soato)?.name_en;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Business location recommendation</h1>
          <p className="muted">
            Ranks every district (or the districts of one region) with the <strong>Business Opportunity Score</strong>{" "}
            — an analytical model built only from official statistics. Every score shows its factor breakdown.
          </p>
        </div>
      </div>
      <SyntheticBanner show={result?.data_mode === "demo"} />

      <form
        className="controls reco-form"
        onSubmit={(e) => {
          e.preventDefault();
          run();
        }}
      >
        <label>
          Business type
          <select value={businessType} onChange={(e) => setBusinessType(e.target.value)}>
            {types.map((t) => (
              <option key={t.business_type} value={t.business_type}>
                {t.display_name.en}
              </option>
            ))}
          </select>
        </label>
        <label>
          Region
          <select value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">All of Uzbekistan</option>
            {regions.map((r) => (
              <option key={r.soato} value={r.soato}>
                {r.name_en}
              </option>
            ))}
          </select>
        </label>
        <label>
          Budget (UZS, optional)
          <input
            inputMode="numeric"
            value={budget}
            onChange={(e) => setBudget(e.target.value.replace(/[^\d]/g, ""))}
            placeholder={profile ? `typical min ${profile.min_budget_uzs.toLocaleString("en-US")}` : ""}
          />
        </label>
        <label>
          Goal
          <select value={target} onChange={(e) => setTarget(e.target.value as Target | "")}>
            {TARGETS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="btn" disabled={loading}>
          {loading ? "Scoring…" : "Score locations"}
        </button>
      </form>

      {error && <div className="alert">{error}</div>}

      {result && (
        <>
          <div className="reco-summary card">
            <div>
              <ModelBadge>Analytical model</ModelBadge>
              <h2>
                {result.display_name.en} · {regionName ?? "all of Uzbekistan"}
              </h2>
              <p className="muted small">
                {result.scope.ranked} of {result.scope.candidates} territories ranked
                {result.excluded_insufficient_data.length
                  ? ` · ${result.excluded_insufficient_data.length} excluded for insufficient data`
                  : ""}
                {result.scope.level === "district" ? "" : " (region level)"}
              </p>
            </div>
            <div className="stack-actions">
              <button
                type="button"
                className="btn secondary"
                onClick={() =>
                  showOnMap({
                    level: result.scope.level as "region" | "district",
                    soatos: result.results.slice(0, 5).map((r) => r.entity.soato),
                    region: result.scope.region_soato,
                  })
                }
              >
                View top 5 on map
              </button>
              <span className="feedback" aria-label="Was this useful?">
                <button
                  type="button"
                  className={`icon-btn ${voted === 1 ? "on" : ""}`}
                  aria-label="Useful"
                  disabled={voted !== null}
                  onClick={() => {
                    setVoted(1);
                    void api.feedback({ request_id: result.request_id, target: "recommendation", rating: 1 });
                  }}
                >
                  👍
                </button>
                <button
                  type="button"
                  className={`icon-btn ${voted === -1 ? "on" : ""}`}
                  aria-label="Not useful"
                  disabled={voted !== null}
                  onClick={() => {
                    setVoted(-1);
                    void api.feedback({ request_id: result.request_id, target: "recommendation", rating: -1 });
                  }}
                >
                  👎
                </button>
              </span>
            </div>
          </div>

          {result.budget_warning && (
            <div className="banner warn">
              Your budget is below the typical minimum for this business ({formatUzs(result.min_budget_uzs)}). This is a
              warning, not a filter.
            </div>
          )}

          <FactorLegend factors={profile?.factors.map((f) => ({ feature: f.feature, label: f.label })) ?? []} weights={result.weights} />

          <ol className="reco-list">
            {result.results.map((r) => (
              <ResultCard
                key={r.entity.soato}
                r={r}
                order={factorOrder}
                open={open === r.entity.soato}
                onToggle={() => setOpen(open === r.entity.soato ? null : r.entity.soato)}
              />
            ))}
          </ol>

          {result.excluded_insufficient_data.length > 0 && (
            <details className="card excluded">
              <summary>Excluded for insufficient data ({result.excluded_insufficient_data.length})</summary>
              <ul>
                {result.excluded_insufficient_data.map((e) => (
                  <li key={e.entity.soato}>
                    {e.entity.name} — coverage {(e.coverage * 100).toFixed(0)}%, missing: {e.missing_features.join(", ")}
                  </li>
                ))}
              </ul>
            </details>
          )}

          <p className="disclaimer">{result.disclaimer}</p>
        </>
      )}
    </>
  );
}

function FactorLegend({ factors, weights }: { factors: { feature: string; label: string }[]; weights: Record<string, number> }) {
  return (
    <div className="factor-legend" aria-label="Factor colours and weights">
      {factors.map((f, i) => (
        <span key={f.feature}>
          <i style={{ background: FACTOR_COLORS[i % FACTOR_COLORS.length] }} />
          {f.label} <span className="muted">{Math.round((weights[f.feature] ?? 0) * 100)}%</span>
        </span>
      ))}
    </div>
  );
}

function ResultCard({ r, order, open, onToggle }: { r: RecoResult; order: string[]; open: boolean; onToggle: () => void }) {
  const byFeature = Object.fromEntries(r.breakdown.map((b) => [b.feature, b]));
  return (
    <li className="card reco-card">
      <button type="button" className="reco-row" onClick={onToggle} aria-expanded={open}>
        <span className="reco-rank">{r.rank}</span>
        <span className="reco-name">
          <strong>{r.entity.name}</strong>
          <span className="muted small-inline">
            rank range {r.rank_range[0]}–{r.rank_range[1]} · coverage {(r.coverage * 100).toFixed(0)}%
          </span>
        </span>
        <span className="score-bar" aria-label={`Score ${r.score.toFixed(1)} of 100`}>
          {order.map((f, i) =>
            byFeature[f] && byFeature[f].contribution > 0 ? (
              <span
                key={f}
                style={{ width: `${byFeature[f].contribution}%`, background: FACTOR_COLORS[i % FACTOR_COLORS.length] }}
                title={`${byFeature[f].label}: ${byFeature[f].contribution.toFixed(1)}`}
              />
            ) : null,
          )}
        </span>
        <span className="reco-score">{r.score.toFixed(1)}</span>
      </button>
      {r.warnings.length > 0 && (
        <ul className="warnings">
          {r.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {open && (
        <div className="breakdown">
          <table>
            <thead>
              <tr>
                <th scope="col">Factor</th>
                <th scope="col">Official value</th>
                <th scope="col" className="num">
                  Normalised
                </th>
                <th scope="col" className="num">
                  Weight
                </th>
                <th scope="col" className="num">
                  Contribution
                </th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {r.breakdown.map((b) => (
                <tr key={b.feature}>
                  <td>
                    {b.label} <span className="muted">({b.direction === "-" ? "lower is better" : "higher is better"})</span>
                  </td>
                  <td>
                    {formatFeature(b.feature, b.raw)} {b.year ? <span className="muted">· {b.year}</span> : null}
                  </td>
                  <td className="num">{b.normalized != null ? b.normalized.toFixed(0) : "—"}</td>
                  <td className="num">{(b.weight * 100).toFixed(0)}%</td>
                  <td className="num">{b.contribution.toFixed(1)}</td>
                  <td>
                    {b.sources
                      .filter((s) => s.dataset_id)
                      .map((s) => (
                        <a key={s.indicator} href={s.url ?? "https://siat.stat.uz"} target="_blank" rel="noreferrer">
                          SIAT {s.dataset_id}
                        </a>
                      ))
                      .reduce<React.ReactNode[]>((acc, el, i) => (i ? [...acc, ", ", el] : [el]), [])}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Score = Σ weight × normalised value (0–100 percentile within the scope). Contributions add up to the score.
          </p>
          <div className="stack-actions">
            <Link className="link" to={`/forecast?indicator=population_total&level=${r.entity.level}&soato=${r.entity.soato}`}>
              Population forecast →
            </Link>
            <Link className="link" to={`/map?level=${r.entity.level}&focus=${r.entity.soato}${r.entity.region_soato ? `&region=${r.entity.region_soato}` : ""}`}>
              Show on map →
            </Link>
          </div>
        </div>
      )}
    </li>
  );
}
