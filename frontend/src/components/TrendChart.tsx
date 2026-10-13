import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axisValue, formatValue } from "../format";

const LINE = "#3B6FD4";
const AXIS = "#7A8699";

export function TrendChart({ points, unit }: { points: { year: number; value: number }[]; unit: string }) {
  return (
    <div style={{ width: "100%", height: 280 }}>
      <ResponsiveContainer>
        <LineChart data={points} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} stroke={AXIS} strokeOpacity={0.2} />
          <XAxis dataKey="year" stroke={AXIS} fontSize={12} />
          <YAxis
            tickFormatter={(v: number) => axisValue(v, unit)}
            stroke={AXIS}
            fontSize={12}
            width={56}
            domain={["auto", "auto"]}
          />
          <Tooltip
            formatter={(v: number) => [formatValue(v, unit), "Value"]}
            labelFormatter={(y) => `Year ${y}`}
            contentStyle={{ borderRadius: 8, fontSize: 13 }}
          />
          <Line type="monotone" dataKey="value" stroke={LINE} strokeWidth={2.5} dot={{ r: 3 }} activeDot={{ r: 5 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
