"use client";

import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip } from "@/components/ChartTooltip";
import type { NamedSeries } from "@/lib/types";
import { chartPeriodLabel, moneyAxis, shortChartName, tickStep } from "@/lib/format";

const PALETTE = ["#2ee6c7", "#7aa2ff", "#f4b942", "#fb7185", "#c084fc", "#34d399", "#fb923c", "#38bdf8"];

export function CompareChart({
  series,
  currency,
  granularity,
}: {
  series: NamedSeries[];
  currency: string;
  granularity: string;
}) {
  const tracks = useMemo(
    () =>
      series.map((item, index) => ({
        id: `s${index}`,
        label: shortChartName(item.label),
        full: item.label,
        color: PALETTE[index % PALETTE.length],
        points: item.points,
      })),
    [series]
  );
  const [hidden, setHidden] = useState<string[]>([]);
  useEffect(() => {
    setHidden([]);
  }, [series]);
  const visible = tracks.filter((track) => !hidden.includes(track.id));
  const dates = Array.from(new Set(tracks.flatMap((track) => track.points.map((point) => point.date)))).sort();
  const data = dates.map((date) => {
    const row: Record<string, string | number> = { date, label: chartPeriodLabel(date, granularity) };
    for (const track of tracks) {
      row[track.id] = track.points.find((point) => point.date === date)?.cost ?? 0;
    }
    return row;
  });
  const names = Object.fromEntries(tracks.map((track) => [track.id, track.label]));

  if (!series.length) {
    return <p className="py-16 text-center text-sm text-mist-500">Tick cost objects below to chart them over time.</p>;
  }

  return (
    <div className="min-w-0">
      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 12, right: 12, left: 4, bottom: 8 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
            <XAxis
              dataKey="label"
              interval={tickStep(data.length)}
              minTickGap={24}
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
              cursor={{ stroke: "rgba(255,255,255,0.12)", strokeWidth: 1 }}
              content={<ChartTooltip currency={currency} names={names} />}
            />
            {visible.map((track) => (
              <Line
                key={track.id}
                type="monotone"
                dataKey={track.id}
                name={track.label}
                stroke={track.color}
                strokeWidth={2.25}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {tracks.map((track) => {
          const off = hidden.includes(track.id);
          return (
            <button
              key={track.id}
              type="button"
              title={track.full}
              onClick={() =>
                setHidden((current) => (off ? current.filter((id) => id !== track.id) : [...current, track.id]))
              }
              className={`inline-flex max-w-full items-center gap-2 rounded-full border px-2.5 py-1 text-xs ${
                off ? "border-white/5 text-mist-500 line-through opacity-50" : "border-white/10 text-mist-100"
              }`}
            >
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: track.color }} />
              <span className="truncate">{track.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
