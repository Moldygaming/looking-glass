"use client";

import { moneyExact } from "@/lib/format";

type PayloadItem = {
  name?: string;
  value?: number | string;
  color?: string;
  dataKey?: string;
  payload?: { label?: string };
};

export function ChartTooltip({
  active,
  payload,
  label,
  currency = "GBP",
  names,
}: {
  active?: boolean;
  payload?: PayloadItem[];
  label?: string;
  currency?: string;
  names?: Record<string, string>;
}) {
  if (!active || !payload?.length) return null;
  const rows = [...payload]
    .filter((item) => item.value !== undefined && item.value !== null)
    .sort((a, b) => Number(b.value) - Number(a.value));
  const heading = String(payload[0]?.payload?.label || label || "");
  return (
    <div className="max-w-xs rounded-xl border border-white/15 bg-[#0c1220]/95 px-3 py-2 shadow-2xl backdrop-blur">
      <div className="mb-1.5 text-xs font-medium text-mist-400">{heading}</div>
      <ul className="space-y-1">
        {rows.map((item) => {
          const key = String(item.dataKey || item.name || "");
          const title = names?.[key] || String(item.name || key);
          return (
            <li key={key} className="flex items-center justify-between gap-4 text-xs">
              <span className="flex min-w-0 items-center gap-2 text-mist-100">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: item.color }} />
                <span className="truncate">{title}</span>
              </span>
              <span className="shrink-0 font-mono text-white">{moneyExact(Number(item.value), currency)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
