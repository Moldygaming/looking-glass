"use client";

import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CostPoint } from "@/lib/types";
import { money } from "@/lib/format";

export function SpendChart({ series, currency }: { series: CostPoint[]; currency: string }) {
  const data = series.map((p) => ({
    ...p,
    label: p.date.slice(5),
  }));
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ left: 8, right: 8, top: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="spend" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2ee6c7" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#2ee6c7" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="label" tick={{ fill: "#8b9bb4", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis
            tick={{ fill: "#8b9bb4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => money(Number(v), currency)}
            width={72}
          />
          <Tooltip
            contentStyle={{ background: "#121a2c", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12 }}
            formatter={(v) => money(Number(v), currency)}
            labelStyle={{ color: "#8b9bb4" }}
          />
          <Area type="monotone" dataKey="cost" stroke="#2ee6c7" fill="url(#spend)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
