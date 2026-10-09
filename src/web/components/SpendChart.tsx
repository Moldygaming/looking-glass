"use client";

import { useId } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip } from "@/components/ChartTooltip";
import type { CostPoint } from "@/lib/types";
import { chartPeriodLabel, moneyAxis, tickStep } from "@/lib/format";

export function SpendChart({
  series,
  currency,
  granularity = "day",
}: {
  series: CostPoint[];
  currency: string;
  granularity?: string;
}) {
  const gradientId = useId().replace(/:/g, "");
  const data = series.map((point) => ({
    ...point,
    label: chartPeriodLabel(point.date, granularity),
  }));
  if (!data.length) {
    return <p className="py-16 text-center text-sm text-mist-500">No spend in this period.</p>;
  }
  return (
    <div className="h-80 w-full min-w-0">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 8, left: 4, bottom: 4 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2ee6c7" stopOpacity={0.28} />
              <stop offset="100%" stopColor="#2ee6c7" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis
            dataKey="label"
            interval={tickStep(data.length)}
            minTickGap={22}
            tick={{ fill: "#8b9bb4", fontSize: 11 }}
            tickMargin={8}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#8b9bb4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={52}
            tickFormatter={(value) => moneyAxis(Number(value), currency)}
          />
          <Tooltip
            cursor={{ stroke: "rgba(46,230,199,0.35)", strokeWidth: 1 }}
            content={<ChartTooltip currency={currency} />}
          />
          <Area type="monotone" dataKey="cost" name="Cost" stroke="#2ee6c7" fill={`url(#${gradientId})`} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
