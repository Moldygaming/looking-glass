"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";

export default function DashboardsPage() {
  const [rows, setRows] = useState<Dashboard[]>([]);
  const [name, setName] = useState("");

  function load() {
    api<Dashboard[]>("/dashboards").then(setRows);
  }

  useEffect(load, []);

  async function create() {
    if (!name.trim()) return;
    const created = await api<Dashboard>("/dashboards", {
      method: "POST",
      body: JSON.stringify({
        name,
        description: "",
        visibility: "private",
        widgets: [
          { id: "w1", type: "kpi", title: "Period spend", group_by: "service", date_range: "30d" },
          { id: "w2", type: "timeseries", title: "Daily cost", group_by: "service", date_range: "30d" },
          { id: "w3", type: "breakdown", title: "By service", group_by: "service", date_range: "30d" },
        ],
      }),
    });
    setName("");
    window.location.href = `/dashboards/${created.id}`;
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl">Dashboards</h1>
          <p className="mt-2 text-sm text-mist-400">Build your own views. Widget queries always respect tag-based access.</p>
        </div>
        <div className="flex gap-2">
          <input className="input w-56" placeholder="New dashboard name" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn-primary" onClick={create}>
            Create
          </button>
        </div>
      </div>
      <div className="mt-8 grid gap-4 md:grid-cols-2">
        {rows.map((d) => (
          <Link key={d.id} href={`/dashboards/${d.id}`} className="panel-pad transition hover:border-glass/40">
            <div className="text-xs uppercase tracking-[0.16em] text-mist-500">{d.visibility}</div>
            <div className="mt-2 font-display text-xl">{d.name}</div>
            <p className="mt-2 text-sm text-mist-400">{d.description || `${d.widgets.length} widgets`}</p>
          </Link>
        ))}
      </div>
    </Shell>
  );
}
