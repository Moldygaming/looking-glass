"use client";

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip } from "@/components/ChartTooltip";
import type { BreakdownRow } from "@/lib/types";
import { categorySwatch } from "@/lib/colors";
import { moneyAxis, shortChartName } from "@/lib/format";

export function BreakdownChart({ rows, currency }: { rows: BreakdownRow[]; currency: string }) {
  const data = rows.map((row) => ({
    ...row,
    short: shortChartName(row.label, 18),
    fill: categorySwatch("", row.label).hex,
  }));
  const height = Math.max(240, Math.min(420, 36 + data.length * 34));

  if (!data.length) {
    return <p className="py-16 text-center text-sm text-mist-500">No breakdown for this split.</p>;
  }

  return (
    <div className="w-full min-w-0" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 48, left: 4, bottom: 8 }} barCategoryGap="28%">
          <XAxis
            type="number"
            tick={{ fill: "#8b9bb4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(value) => moneyAxis(Number(value), currency)}
          />
          <YAxis
            type="category"
            dataKey="short"
            width={108}
            tick={{ fill: "#c5d0e0", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            interval={0}
          />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={<ChartTooltip currency={currency} />}
          />
          <Bar dataKey="cost" name="Cost" radius={[0, 6, 6, 0]} maxBarSize={22}>
            {data.map((row) => (
              <Cell key={row.key} fill={row.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
