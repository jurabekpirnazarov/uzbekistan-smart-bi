// Display formatting only — every number is already computed by the backend.

const nf = (digits: number) => new Intl.NumberFormat("en-US", { maximumFractionDigits: digits });

export function formatValue(value: number, unit: string, compact = false): string {
  if (unit === "UZS") {
    const abs = Math.abs(value);
    if (abs >= 1e12) return `${nf(1).format(value / 1e12)} trln UZS`;
    if (abs >= 1e9) return `${nf(1).format(value / 1e9)} bln UZS`;
    if (abs >= 1e6) return `${nf(1).format(value / 1e6)} mln UZS`;
    return `${nf(0).format(value)} UZS`;
  }
  if (unit === "persons") {
    if (compact && Math.abs(value) >= 1e6) return `${nf(2).format(value / 1e6)} M`;
    if (compact && Math.abs(value) >= 1e3) return `${nf(1).format(value / 1e3)} K`;
    return nf(0).format(value);
  }
  if (unit.startsWith("%")) return `${nf(1).format(value)}${unit === "%" ? "%" : ""}`;
  if (compact && Math.abs(value) >= 1e3) return `${nf(1).format(value / 1e3)} K`;
  return nf(1).format(value);
}

export function axisValue(value: number, unit: string): string {
  if (unit === "UZS") {
    if (Math.abs(value) >= 1e12) return `${nf(0).format(value / 1e12)}T`;
    if (Math.abs(value) >= 1e9) return `${nf(0).format(value / 1e9)}B`;
  }
  if (Math.abs(value) >= 1e6) return `${nf(1).format(value / 1e6)}M`;
  if (Math.abs(value) >= 1e3) return `${nf(0).format(value / 1e3)}K`;
  return nf(1).format(value);
}

export function unitLabel(unit: string): string {
  if (unit === "% of previous year") return "% of previous year (100 = no change)";
  return unit;
}

export function formatPct(v: number | null): string {
  if (v === null) return "—";
  return `${v >= 0 ? "+" : ""}${nf(1).format(v)}%`;
}

export const CATEGORY_LABELS: Record<string, string> = {
  population: "Population",
  business: "Business activity",
  services: "Market services",
  health: "Health facilities",
  economy: "Economy",
};

/** Raw value of a scoring feature, in the unit the feature is defined in (ml/features/definitions.yaml). */
export function formatFeature(feature: string, raw: number | null): string {
  if (raw === null || raw === undefined) return "—";
  if (feature === "is_city") return raw >= 0.5 ? "City" : "District";
  if (feature === "population") return `${nf(0).format(raw)} people`;
  if (feature === "region_small_business_share") return `${nf(1).format(raw)}% of GVA`;
  if (feature.endsWith("_per_capita")) return `${nf(0).format(raw)} UZS / person`;
  if (feature.endsWith("_per_10k")) return `${nf(2).format(raw)} per 10k people`;
  if (feature === "business_density") return `${nf(1).format(raw)} per 1,000 people`;
  if (feature === "urbanization" || feature.includes("growth") || feature.includes("rate") || feature.includes("cagr")) {
    const pct = raw * 100;
    return `${feature === "urbanization" ? "" : pct >= 0 ? "+" : ""}${nf(1).format(pct)}%`;
  }
  return nf(2).format(raw);
}

export const LEVEL_LABEL: Record<string, string> = { country: "Country", region: "Region", district: "District / city" };

export function formatUzs(v: number): string {
  return formatValue(v, "UZS");
}
