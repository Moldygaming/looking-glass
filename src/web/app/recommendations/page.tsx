"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { ProviderBadge } from "@/components/ProviderBadge";
import { CategoryBadge } from "@/components/TypeBadge";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import type { Recommendation } from "@/lib/types";

const labels: Record<string, string> = {
  unattached_disk: "Unattached disk",
  idle_compute: "Idle compute",
  orphan_ip: "Orphan IP",
  untagged: "Untagged spend",
  rightsize: "Right-size",
};

export default function RecommendationsPage() {
  const [rows, setRows] = useState<Recommendation[]>([]);

  function load() {
    api<Recommendation[]>("/recommendations").then(setRows);
  }
  useEffect(load, []);

  async function patch(id: string, status: "accepted" | "dismissed") {
    await api(`/recommendations/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
    load();
  }

  const total = rows.reduce((sum, r) => sum + r.monthly_savings, 0);

  return (
    <Shell>
      <h1 className="font-display text-3xl">Savings recommendations</h1>
      <p className="mt-2 text-sm text-mist-400">
        Rule-based findings from the last 14 days of ingested cost. You only see resources your tag scopes allow.
      </p>
      <div className="panel-pad mt-6 max-w-sm">
        <div className="text-xs uppercase tracking-[0.16em] text-mist-500">Potential monthly save</div>
        <div className="mt-2 font-mono text-3xl text-glass">{money(total)}</div>
      </div>
      <div className="mt-6 grid gap-4">
        {rows.map((r) => (
          <article key={r.id} className="panel-pad">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <ProviderBadge provider={r.provider} />
                  <CategoryBadge service={r.resource_name} />
                  <span className="chip">{labels[r.category] || r.category}</span>
                </div>
                <h2 className="mt-3 text-lg font-medium">{r.title}</h2>
                <p className="mt-1 text-sm text-mist-400">{r.description}</p>
                <p className="mt-2 text-xs text-mist-500">
                  {r.resource_name} · {Object.entries(r.tags).map(([k, v]) => `${k}=${v}`).join(" · ") || "no tags"}
                </p>
              </div>
              <div className="text-right">
                <div className="font-mono text-xl text-glass">{money(r.monthly_savings, r.currency)}</div>
                <div className="text-xs text-mist-500">per month</div>
                <div className="mt-3 flex gap-2">
                  <button className="btn-primary" onClick={() => patch(r.id, "accepted")}>
                    Accept
                  </button>
                  <button className="btn-ghost" onClick={() => patch(r.id, "dismissed")}>
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
          </article>
        ))}
      </div>
    </Shell>
  );
}
