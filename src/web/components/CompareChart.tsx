"use client";

import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { NamedSeries } from "@/lib/types";
import { seriesColor } from "@/lib/colors";
import { money, periodLabel } from "@/lib/format";

export function CompareChart({
  series,
  currency,
  granularity,
}: {
  series: NamedSeries[];
  currency: string;
  granularity: string;
}) {
  const dates = Array.from(new Set(series.flatMap((item) => item.points.map((point) => point.date)))).sort();
  const data = dates.map((date) => {
    const row: Record<string, string | number> = { date, label: periodLabel(date, granularity) };
    for (const item of series) {
      row[item.key] = item.points.find((point) => point.date === date)?.cost ?? 0;
    }
    return row;
  });

  if (!series.length) {
    return <p className="py-10 text-center text-sm text-mist-500">Tick cost objects below to chart them over time.</p>;
  }

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ left: 8, right: 8, top: 8, bottom: 0 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "#8b9bb4", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis
            tick={{ fill: "#8b9bb4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(value) => money(Number(value), currency)}
            width={72}
          />
          <Tooltip
            contentStyle={{ background: "#121a2c", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12 }}
            formatter={(value, name) => [money(Number(value), currency), series.find((item) => item.key === name)?.label || String(name)]}
            labelStyle={{ color: "#8b9bb4" }}
          />
          <Legend formatter={(value) => series.find((item) => item.key === value)?.label || value} />
          {series.map((item) => (
            <Line
              key={item.key}
              type="monotone"
              dataKey={item.key}
              name={item.key}
              stroke={seriesColor(item.kind, item.category)}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
