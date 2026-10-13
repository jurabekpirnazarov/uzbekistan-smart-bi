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
