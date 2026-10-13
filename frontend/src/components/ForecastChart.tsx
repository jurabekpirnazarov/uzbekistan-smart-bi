import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Forecast } from "../api/client";
import { axisValue, formatValue } from "../format";

const HISTORY = "#1f3f7a";
const FORECAST = "#e3a72f";
const AXIS = "#7A8699";

interface Row {
  year: number;
  history?: number;
  forecast?: number;
  band80?: [number, number];
  band95?: [number, number];
}

/** History (solid) + forecast (dashed) with 80 % and 95 % bands. */
export function ForecastChart({ f, unit }: { f: Forecast; unit: string }) {
  const rows: Row[] = f.history.map((p) => ({ year: p.year, history: p.value }));
  const last = f.history[f.history.length - 1];
  if (last) {
    const r = rows[rows.length - 1];
    r.forecast = last.value; // connect the dashed line to the last observation
    r.band80 = [last.value, last.value];
    r.band95 = [last.value, last.value];
  }
  for (const p of f.forecast) {
    rows.push({
      year: p.year,
      forecast: p.yhat,
      band80: p.lo80 != null && p.hi80 != null ? [p.lo80, p.hi80] : undefined,
      band95: p.lo95 != null && p.hi95 != null ? [p.lo95, p.hi95] : undefined,
    });
  }
  return (
    <div style={{ width: "100%", height: 340 }}>
      <ResponsiveContainer>
        <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} stroke={AXIS} strokeOpacity={0.2} />
          <XAxis dataKey="year" stroke={AXIS} fontSize={12} />
          <YAxis tickFormatter={(v: number) => axisValue(v, unit)} stroke={AXIS} fontSize={12} width={60} domain={["auto", "auto"]} />
          <Tooltip
            formatter={(v: number | [number, number], name: string) =>
              Array.isArray(v) ? [`${formatValue(v[0], unit)} – ${formatValue(v[1], unit)}`, name] : [formatValue(v, unit), name]
            }
            labelFormatter={(y) => `Year ${y}`}
            contentStyle={{ borderRadius: 8, fontSize: 13 }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area dataKey="band95" name="95% interval" stroke="none" fill={FORECAST} fillOpacity={0.12} isAnimationActive={false} />
          <Area dataKey="band80" name="80% interval" stroke="none" fill={FORECAST} fillOpacity={0.25} isAnimationActive={false} />
          <Line dataKey="history" name="Official statistic" stroke={HISTORY} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} />
          <Line
            dataKey="forecast"
            name="Model forecast"
            stroke={FORECAST}
            strokeWidth={2.5}
            strokeDasharray="6 4"
            dot={{ r: 3 }}
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
