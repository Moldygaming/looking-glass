"use client";

import { ChevronRight } from "lucide-react";
import { ProviderBadge } from "@/components/ProviderBadge";
import { CategoryBadge, ColorDot, KindBadge } from "@/components/TypeBadge";
import { categorySwatch, kindSwatch } from "@/lib/colors";
import { moneyExact, pct } from "@/lib/format";
import type { CostObject } from "@/lib/types";

export function ObjectTable({
  rows,
  selected,
  currency,
  currentKind,
  onToggle,
  onDrill,
}: {
  rows: CostObject[];
  selected: string[];
  currency: string;
  currentKind: string | null;
  onToggle: (key: string) => void;
  onDrill: (row: CostObject) => void;
}) {
  if (!rows.length) {
    return <p className="py-8 text-center text-sm text-mist-500">No cost objects in this view.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-mist-500">
          <tr>
            <th className="w-8 pb-2"></th>
            <th className="pb-2">Object</th>
            <th className="pb-2">Type</th>
            <th className="pb-2">Workload</th>
            <th className="pb-2 text-right">Period</th>
            <th className="pb-2 text-right">Prior</th>
            <th className="pb-2 text-right">Growth</th>
            <th className="pb-2 text-right">Share</th>
            <th className="w-8 pb-2"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const checked = selected.includes(row.key);
            const growthTone =
              row.delta_pct == null ? "text-mist-500" : row.delta_pct > 8 ? "text-rose" : row.delta_pct < 0 ? "text-glass" : "text-mist-100";
            const accent =
              row.kind === "resource" ? categorySwatch(row.category || "", row.service || "").hex : kindSwatch(row.kind).hex;
            return (
              <tr key={row.key} className={`border-t border-white/5 ${checked ? "bg-glass/5" : "hover:bg-white/5"}`}>
                <td className="py-2">
                  <input
                    type="checkbox"
                    className="accent-glass"
                    checked={checked}
                    readOnly
                    onClick={() => onToggle(row.key)}
                  />
                </td>
                <td className="py-2">
                  <div className="flex items-center gap-2">
                    <ColorDot hex={accent} />
                    {row.provider && <ProviderBadge provider={row.provider} />}
                    <button
                      type="button"
                      className="text-left hover:text-glass"
                      onClick={() => (row.has_children ? onDrill(row) : onToggle(row.key))}
                    >
                      {row.label}
                    </button>
                  </div>
                </td>
                <td>
                  <KindBadge kind={row.kind || currentKind || "resource"} />
                </td>
                <td>
                  {row.kind === "resource" || row.kind === "category" || row.kind === "service" ? (
                    <CategoryBadge category={row.category} service={row.service} />
                  ) : (
                    <span className="text-mist-500">—</span>
                  )}
                </td>
                <td className="text-right font-mono">{moneyExact(row.cost, currency)}</td>
                <td className="text-right font-mono text-mist-400">{moneyExact(row.prior_cost, currency)}</td>
                <td className={`text-right font-mono ${growthTone}`}>{row.delta_pct == null ? "—" : pct(row.delta_pct)}</td>
                <td className="text-right font-mono text-mist-400">{(row.share * 100).toFixed(1)}%</td>
                <td className="py-2">
                  {row.has_children && (
                    <button type="button" className="text-mist-400 hover:text-glass" onClick={() => onDrill(row)} title="Drill in">
                      <ChevronRight size={16} />
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
