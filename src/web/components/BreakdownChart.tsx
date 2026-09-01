"use client";

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { BreakdownRow } from "@/lib/types";
import { categorySwatch } from "@/lib/colors";
import { money } from "@/lib/format";

export function BreakdownChart({ rows, currency }: { rows: BreakdownRow[]; currency: string }) {
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <BarChart data={rows} layout="vertical" margin={{ left: 16, right: 16, top: 8, bottom: 8 }}>
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="label"
            width={120}
            tick={{ fill: "#8b9bb4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{ background: "#121a2c", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12 }}
            formatter={(v) => money(Number(v), currency)}
          />
          <Bar dataKey="cost" radius={[0, 8, 8, 0]}>
            {rows.map((row) => (
              <Cell key={row.key} fill={categorySwatch("", row.label).hex} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
