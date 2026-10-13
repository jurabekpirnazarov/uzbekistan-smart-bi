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

const API_BASE = "/api/v1";

async function request<T>(path: string, allow503 = false): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: { Accept: "application/json" } });
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
  ranking: (indicator: string, level: "region" | "district", year?: number, region?: string) =>
    request<Ranking>(`/statistics${qs({ indicator, level, year, region })}`),
  timeseries: (indicator: string, level: Level, soato: string) =>
    request<TimeSeries>(`/timeseries/${indicator}/${level}/${soato}`),
};

// --- AI analyst chat (SSE over POST) -------------------------------------------------------

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatHandlers {
  onToken: (text: string) => void;
  onToolCall: (tool: { name: string; label: string; args: Record<string, unknown> }) => void;
  onDone: () => void;
  onError: (message: string) => void;
}

export async function chatStatus(): Promise<{ enabled: boolean; model: string | null }> {
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
    h.onError(`${res.status} ${res.statusText}`);
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
      else if (event === "error") h.onError(payload.message);
      else if (event === "done") h.onDone();
    }
  }
}
