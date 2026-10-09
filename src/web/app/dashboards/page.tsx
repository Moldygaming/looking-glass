"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";

export default function DashboardsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<Dashboard[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    api<Dashboard[]>("/dashboards")
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(load, []);

  async function create(event?: React.FormEvent) {
    event?.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api<Dashboard>("/dashboards", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim() || "Untitled dashboard",
          description: "",
          visibility: "private",
          widgets: [],
        }),
      });
      setName("");
      router.push(`/dashboards/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the dashboard.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl">Dashboards</h1>
          <p className="mt-2 text-sm text-mist-400">
            Custom reports: filter by cloud, category, resource type and tags, then group by account or resource.
          </p>
        </div>
        <form className="flex gap-2" onSubmit={create}>
          <input
            className="input w-56"
            placeholder="New dashboard name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button className="btn-primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create"}
          </button>
        </form>
      </div>
      {error && <div className="panel-pad mt-4 text-sm text-rose">{error}</div>}
      <div className="mt-8 grid gap-4 md:grid-cols-2">
        {rows.map((d) => (
          <Link key={d.id} href={`/dashboards/${d.id}`} className="panel-pad transition hover:border-glass/40">
            <div className="text-xs uppercase tracking-[0.16em] text-mist-500">{d.visibility}</div>
            <div className="mt-2 font-display text-xl">{d.name}</div>
            <p className="mt-2 text-sm text-mist-400">{d.description || `${d.widgets.length} widgets`}</p>
          </Link>
        ))}
        {!rows.length && !error && <p className="text-sm text-mist-500">No dashboards yet. Create one to start a report.</p>}
      </div>
    </Shell>
  );
}
