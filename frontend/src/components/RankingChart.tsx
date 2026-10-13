import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RankingItem } from "../api/client";
import { axisValue, formatValue } from "../format";

const BAR = "#3FB8AF";
const BAR_SELECTED = "#E3A72F";
const AXIS = "#7A8699";

interface Props {
  items: RankingItem[];
  unit: string;
  selected: string | null;
  onSelect: (soato: string) => void;
}

export function RankingChart({ items, unit, selected, onSelect }: Props) {
  const height = Math.max(220, items.length * 28 + 40);
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer>
        <BarChart data={items} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
          <CartesianGrid horizontal={false} stroke={AXIS} strokeOpacity={0.2} />
          <XAxis
            type="number"
            tickFormatter={(v: number) => axisValue(v, unit)}
            stroke={AXIS}
            fontSize={12}
            domain={unit.startsWith("%") ? ["auto", "auto"] : [0, "auto"]}
          />
          <YAxis type="category" dataKey="name" width={150} stroke={AXIS} fontSize={12} interval={0} />
          <Tooltip
            cursor={{ fillOpacity: 0.08 }}
            formatter={(v: number) => [formatValue(v, unit), "Value"]}
            contentStyle={{ borderRadius: 8, fontSize: 13 }}
          />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} onClick={(d: RankingItem) => onSelect(d.soato)} cursor="pointer">
            {items.map((it) => (
              <Cell key={it.soato} fill={it.soato === selected ? BAR_SELECTED : BAR} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
