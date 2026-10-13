// The single API client for the app. Every backend call goes through here.

export type Level = "country" | "region" | "district";

export interface HealthStatus {
  status: "ok" | "degraded";
  db: "ok" | "down";
  version: string;
}

export interface Source {
  name: string;
  url: string | null;
  siat_dataset_id: number | null;
}

export interface Meta {
  indicator: string | null;
  unit: string | null;
  period: string | null;
  sources: Source[];
  is_synthetic: boolean;
  retrieved_at: string | null;
}

export interface Indicator {
  code: string;
  name_en: string;
  category: string;
  unit: string;
  additive: boolean;
  higher_is_better: boolean;
  levels: Level[];
  year_min: number | null;
  year_max: number | null;
  source_name: string | null;
  siat_dataset_id: number | null;
}

export interface Region {
  soato: string;
  name_en: string;
  name_uz: string | null;
  name_ru: string | null;
  districts: number;
}

export interface District {
  soato: string;
  name_en: string;
  name_uz: string | null;
  name_ru: string | null;
  kind: string;
  region_soato: string;
}

export interface RankingItem {
  rank: number;
  soato: string;
  name: string;
  kind: string | null;
  region_soato: string | null;
  value: number;
  share: number | null;
}

export interface Ranking {
  level: Level;
  year: number;
  years_available: number[];
  items: RankingItem[];
  total: number | null;
  meta: Meta;
}

export interface TimeSeries {
  level: Level;
  soato: string;
  name: string;
  points: { year: number; value: number }[];
  meta: Meta;
}

export interface Kpi {
  indicator: string;
  label: string;
  unit: string;
  year: number;
  value: number;
  change_pct: number | null;
}

export interface Overview {
  kpis: Kpi[];
  regions: number;
  districts: number;
  cities: number;
  meta: Meta;
}

// --- map ------------------------------------------------------------------------------------

export interface GeoFeature {
  type: "Feature";
  geometry: { type: string; coordinates: unknown };
  properties: {
    soato: string;
    name_en: string;
    name_uz: string | null;
    kind: string | null;
    region_soato: string | null;
    geom_approx: boolean;
    centroid: [number, number];
    value: number | null;
    rank: number | null;
    share: number | null;
  };
}

export interface GeoLayer {
  type: "FeatureCollection";
  features: GeoFeature[];
  metric: string;
  level: "region" | "district";
  year: number;
  years_available: number[];
  min: number | null;
  max: number | null;
  meta: Meta;
}

// --- recommendations ------------------------------------------------------------------------

export interface Factor {
  feature: string;
  weight: number;
  direction: "+" | "-";
  label: string;
}

export interface BusinessType {
  business_type: string;
  display_name: { en: string; uz: string; ru: string };
  min_budget_uzs: number;
  default_level: string;
  factors: Factor[];
}

export type Target = "high_growth" | "stable_demand" | "low_competition";

export interface RecommendRequest {
  business_type: string;
  region?: string | null;
  budget_uzs?: number | null;
  target?: Target | null;
  weights_override?: Record<string, number> | null;
  limit?: number;
}

export interface BreakdownItem {
  feature: string;
  label: string;
  direction: "+" | "-";
  raw: number | null;
  year: number | null;
  normalized: number | null;
  weight: number;
  contribution: number;
  is_synthetic: boolean;
  sources: { indicator: string; dataset_id: number | null; url: string | null }[];
}

export interface RecoEntity {
  level: string;
  soato: string;
  name: string;
  region_soato: string | null;
  kind: string | null;
}

export interface RecoResult {
  rank: number;
  entity: RecoEntity;
  score: number;
  rank_range: [number, number];
  coverage: number;
  breakdown: BreakdownItem[];
  warnings: string[];
}

export interface Recommendation {
  request_id: string;
  scope: { level: string; region_soato: string | null; candidates: number; ranked: number };
  business_type: string;
  display_name: { en: string; uz: string; ru: string };
  data_mode: "official" | "demo";
  disclaimer: string;
  weights: Record<string, number>;
  years_used: Record<string, number | null>;
  budget_warning: boolean;
  min_budget_uzs: number;
  results: RecoResult[];
  excluded_insufficient_data: { entity: RecoEntity; coverage: number; missing_features: string[] }[];
}

// --- forecasts ------------------------------------------------------------------------------

export interface ForecastPoint {
  year: number;
  horizon: number;
  yhat: number;
  lo80: number | null;
  hi80: number | null;
  lo95: number | null;
  hi95: number | null;
}

export interface Forecast {
  indicator: string;
  level: Level;
  soato: string;
  name: string;
  history: { year: number; value: number }[];
  forecast: ForecastPoint[];
  model: string;
  backtest: Record<string, number | null>;
  history_points: number;
  low_confidence: boolean;
  note: string;
  meta: Meta;
}

// --- monitoring -----------------------------------------------------------------------------

export interface MonitoringData {
  observations: number;
  last_retrieved_at: string | null;
  age_days: number | null;
  sources: { name: string; url: string | null; retrieved_at: string | null }[];
  ingestion_runs: { started_at: string; status: string; datasets_ok: number; rows_loaded: number; rows_rejected: number }[];
  quality_checks: { check: string; passed: boolean }[];
  missing_ratio: { indicator: string; ratio: number }[];
  snapshot_at: string | null;
}

export interface LeaderboardRow {
  indicator: string;
  level: string;
  model: string;
  selected: boolean;
  smape_h1?: number | null;
  smape_h2?: number | null;
  improvement_vs_naive_pct_h1?: number | null;
}

export interface MonitoringModels {
  run_id: string | null;
  trained_at: string | null;
  leaderboard: LeaderboardRow[];
  drift: { feature: string; years: string; psi: number; alert: boolean }[];
  realised_error: { indicator: string; model: string; mape: number }[];
}

export interface MonitoringReco {
  requests: { business_type: string; count: number }[];
  most_recommended: [string, number][];
  stability: { business_type: string; jaccard: number }[];
  feedback: { up: number; down: number };
}

export interface AgentRunRow {
  created_at: string;
  question: string;
  lang: string;
  intent: string | null;
  mode: string;
  status: string;
  latency_ms: number;
  tool_count: number;
  verification_failures: number;
}

export interface MonitoringAgent {
  window_days: number;
  runs: number;
  errors: number;
  fallback_runs: number;
  p50_ms: number | null;
  p95_ms: number | null;
  tokens: number;
  cost_usd: number;
  verification_failures: number;
  tools: { tool: string; calls: number; failures: number }[];
  recent: AgentRunRow[];
}

// --- transport ------------------------------------------------------------------------------

const API_BASE = "/api/v1";

async function request<T>(path: string, allow503 = false, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
  });
  if (!res.ok && !(allow503 && res.status === 503)) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.message) message = body.message;
    } catch {
      /* not JSON */
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  // /health returns 503 with a valid body when the database is down.
  health: () => request<HealthStatus>("/health", true),
  overview: () => request<Overview>("/overview"),
  indicators: () => request<Indicator[]>("/indicators"),
  regions: () => request<Region[]>("/regions"),
  districts: (region: string) => request<District[]>(`/regions/${region}/districts`),
  ranking: (indicator: string, level: "region" | "district", year?: number, region?: string) =>
    request<Ranking>(`/statistics${qs({ indicator, level, year, region })}`),
  timeseries: (indicator: string, level: Level, soato: string) =>
    request<TimeSeries>(`/timeseries/${indicator}/${level}/${soato}`),
  geo: (level: "region" | "district", metric: string, year?: number, region?: string) =>
    request<GeoLayer>(`/geo/${level === "region" ? "regions" : "districts"}${qs({ metric, year, region })}`),
  businessTypes: () => request<BusinessType[]>("/business-types"),
  recommend: (body: RecommendRequest) =>
    request<Recommendation>("/recommend", false, { method: "POST", body: JSON.stringify(body) }),
  forecast: (indicator: string, level: Level, soato: string, horizon = 3) =>
    request<Forecast>(`/forecast/${indicator}/${level}/${soato}${qs({ horizon })}`),
  forecastTargets: () => request<string[]>("/forecast-targets"),
  feedback: (body: { request_id?: string | null; target: "chat" | "recommendation"; rating: 1 | -1; comment?: string }) =>
    request<{ id: number }>("/feedback", false, { method: "POST", body: JSON.stringify(body) }),
  monitoring: {
    data: () => request<MonitoringData>("/monitoring/data"),
    models: () => request<MonitoringModels>("/monitoring/models"),
    recommendations: () => request<MonitoringReco>("/monitoring/recommendations"),
    agent: () => request<MonitoringAgent>("/monitoring/agent"),
  },
};

// --- AI analyst chat (SSE over POST) -------------------------------------------------------

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface MapFocus {
  level: "region" | "district";
  soatos: string[];
  region?: string | null;
}

export interface ChatResult {
  request_id: string;
  map_focus: MapFocus | null;
  recommendation: { business_type: string; region: string | null } | null;
  is_synthetic: boolean;
}

export interface Verification {
  checked: number;
  unsupported: string[];
}

export interface ChatHandlers {
  onToken: (text: string) => void;
  onToolCall: (tool: { name: string; label: string; args: Record<string, unknown> }) => void;
  onVerification?: (v: Verification) => void;
  onResult?: (r: ChatResult) => void;
  onDone: () => void;
  onError: (message: string) => void;
}

export interface ChatStatus {
  enabled: boolean;
  mode: "llm" | "fallback";
  model: string | null;
}

export async function chatStatus(): Promise<ChatStatus> {
  return request("/chat/status");
}

export async function streamChat(messages: ChatTurn[], h: ChatHandlers, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ messages }),
    signal,
  });
  if (!res.ok || !res.body) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.message) message = body.message;
    } catch {
      /* not JSON */
    }
    h.onError(message);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (!data) continue;
      const payload = JSON.parse(data);
      if (event === "token") h.onToken(payload.text);
      else if (event === "tool_call") h.onToolCall(payload);
      else if (event === "verification") h.onVerification?.(payload);
      else if (event === "result") h.onResult?.(payload);
      else if (event === "error") h.onError(payload.message);
      else if (event === "done") h.onDone();
    }
  }
}
