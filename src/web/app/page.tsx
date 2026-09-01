"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { KpiCard } from "@/components/KpiCard";
import { SpendChart } from "@/components/SpendChart";
import { BreakdownChart } from "@/components/BreakdownChart";
import { api } from "@/lib/api";
import { money, pct } from "@/lib/format";
import type { CostSummary, Me } from "@/lib/types";

export default function OverviewPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api<Me>("/me"), api<CostSummary>("/costs/summary")])
      .then(([user, data]) => {
        setMe(user);
        setSummary(data);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <Shell>
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-mist-500">FinOps</p>
          <h1 className="font-display text-3xl">Cloud spend, through the glass</h1>
          {me && (
            <p className="mt-2 text-sm text-mist-400">
              {me.is_admin
                ? "Full organisation view. Platform admins are not limited by data scopes."
                : me.scopes.length
                  ? `Showing cost that matches your data scopes: ${me.scopes.map((s) => `${s.tag_key}=${s.tag_value}`).join(", ")}.`
                  : "You have no data scopes yet, so no cost data is visible."}
            </p>
          )}
        </div>
      </div>
      {error && <div className="panel-pad mb-6 text-rose">{error}</div>}
      {summary && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              label="Last 30 days"
              value={money(summary.period_cost, summary.currency)}
              hint={`${pct(summary.delta_pct)} vs prior 30 days`}
              tone={summary.delta_pct > 8 ? "bad" : summary.delta_pct < 0 ? "good" : "default"}
            />
            <KpiCard
              label="Month forecast"
              value={money(summary.forecast_month, summary.currency)}
              hint={`${summary.connections} connected cloud instances`}
            />
            <KpiCard
              label="Open savings"
              value={money(summary.potential_monthly_savings, summary.currency)}
              hint={`${summary.open_recommendations} recommendations`}
              tone="good"
            />
            <KpiCard
              label="Untagged spend"
              value={money(summary.untagged_cost, summary.currency)}
              hint="Missing team tag"
              tone={summary.untagged_cost > 0 ? "warn" : "good"}
            />
          </div>
          <div className="mt-6 grid gap-4 xl:grid-cols-5">
            <section className="panel-pad xl:col-span-3">
              <h2 className="mb-4 text-sm font-medium text-mist-400">Daily cost</h2>
              <SpendChart series={summary.series} currency={summary.currency} />
            </section>
            <section className="panel-pad xl:col-span-2">
              <h2 className="mb-4 text-sm font-medium text-mist-400">By provider</h2>
              <BreakdownChart rows={summary.by_provider} currency={summary.currency} />
            </section>
          </div>
        </>
      )}
    </Shell>
  );
}
