"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { KpiCard } from "@/components/KpiCard";
import { SpendChart } from "@/components/SpendChart";
import { BreakdownChart } from "@/components/BreakdownChart";
import { CompareChart } from "@/components/CompareChart";
import { WidgetBuilder } from "@/components/WidgetBuilder";
import { api } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { widgetHint, widgetQuery } from "@/lib/widgetQuery";
import type { BreakdownRow, CostPoint, CostSummary, Dashboard, NamedSeries, Recommendation, Widget } from "@/lib/types";

export default function DashboardDetailPage() {
  const params = useParams<{ id: string }>();
  const [board, setBoard] = useState<Dashboard | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<Widget | null>(null);
  const [adding, setAdding] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    api<Dashboard>(`/dashboards/${params.id}`).then((d) => {
      setBoard(d);
      setDraft(d.name);
    });
  }

  useEffect(load, [params.id]);

  async function save(next: Dashboard) {
    const updated = await api<Dashboard>(`/dashboards/${params.id}`, {
      method: "PUT",
      body: JSON.stringify({
        name: next.name,
        description: next.description,
        visibility: next.visibility,
        shared_group_id: next.shared_group_id,
        widgets: next.widgets,
      }),
    });
    setBoard(updated);
    setError(null);
    return updated;
  }

  async function addWidget(draftWidget: Omit<Widget, "id"> & { id?: string }) {
    if (!board) return;
    try {
      const widget: Widget = { ...draftWidget, id: `w-${Date.now()}` };
      await save({ ...board, widgets: [...board.widgets, widget] });
      setAdding(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the widget.");
    }
  }

  async function updateWidget(draftWidget: Omit<Widget, "id"> & { id?: string }) {
    if (!board || !editing) return;
    await save({
      ...board,
      widgets: board.widgets.map((item) => (item.id === editing.id ? { ...item, ...draftWidget, id: editing.id } : item)),
    });
    setEditing(null);
  }

  async function removeWidget(id: string) {
    if (!board) return;
    await save({ ...board, widgets: board.widgets.filter((item) => item.id !== id) });
    if (editing?.id === id) setEditing(null);
  }

  if (!board) {
    return (
      <Shell>
        <p className="text-mist-400">Loading dashboard…</p>
      </Shell>
    );
  }

  return (
    <Shell>
      <input
        className="w-full bg-transparent font-display text-3xl outline-none"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => draft !== board.name && save({ ...board, name: draft })}
      />
      <p className="mt-2 max-w-3xl text-sm text-mist-400">
        Build a report from filters: cloud, category, resource type and tags, then group by account, resource or any other cost object.
      </p>
      {error && <div className="panel-pad mt-4 text-sm text-rose">{error}</div>}

      <section className="panel-pad mt-6">
        {editing ? (
          <>
            <h2 className="mb-3 text-sm text-mist-400">Edit widget</h2>
            <WidgetBuilder
              key={editing.id}
              initial={editing}
              submitLabel="Save widget"
              onSubmit={updateWidget}
              onCancel={() => setEditing(null)}
            />
          </>
        ) : adding ? (
          <>
            <h2 className="mb-3 text-sm text-mist-400">Add a report widget</h2>
            <WidgetBuilder submitLabel="Add widget" onSubmit={addWidget} onCancel={() => setAdding(false)} />
          </>
        ) : (
          <button type="button" className="btn-primary" onClick={() => setAdding(true)}>
            Add widget
          </button>
        )}
      </section>

      <div className="mt-8 grid gap-4 lg:grid-cols-2">
        {board.widgets.map((widget) => (
          <WidgetCard
            key={widget.id}
            widget={widget}
            onEdit={() => {
              setEditing(widget);
              setAdding(false);
            }}
            onRemove={() => removeWidget(widget.id)}
          />
        ))}
      </div>
    </Shell>
  );
}

function WidgetCard({ widget, onEdit, onRemove }: { widget: Widget; onEdit: () => void; onRemove: () => void }) {
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [series, setSeries] = useState<CostPoint[]>([]);
  const [rows, setRows] = useState<BreakdownRow[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [growth, setGrowth] = useState<NamedSeries[]>([]);
  const grain = widget.granularity || "day";
  const query = widgetQuery(widget);

  useEffect(() => {
    if (widget.type === "kpi") api<CostSummary>(`/costs/summary${query}`).then(setSummary).catch(() => setSummary(null));
    if (widget.type === "timeseries") api<CostPoint[]>(`/costs/series${query}`).then(setSeries).catch(() => setSeries([]));
    if (widget.type === "breakdown" || widget.type === "table") {
      api<BreakdownRow[]>(`/costs/breakdown${query}`).then(setRows).catch(() => setRows([]));
    }
    if (widget.type === "recommendations") api<Recommendation[]>("/recommendations").then(setRecs).catch(() => setRecs([]));
    if (widget.type === "growth") {
      api<NamedSeries[]>(`/costs/compare${query}`).then(setGrowth).catch(() => setGrowth([]));
    }
  }, [widget, query]);

  const wide = widget.type === "timeseries" || widget.type === "growth" || widget.type === "table";

  return (
    <section className={`panel-pad ${wide ? "lg:col-span-2" : ""}`}>
      <div className="mb-1 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-medium">{widget.title}</h2>
          <p className="mt-1 text-xs text-mist-500">{widgetHint(widget)}</p>
        </div>
        <div className="flex gap-2">
          <button className="text-xs text-mist-500 hover:text-mist-100" onClick={onEdit}>
            Edit
          </button>
          <button className="text-xs text-mist-500 hover:text-rose" onClick={onRemove}>
            Remove
          </button>
        </div>
      </div>
      {widget.type === "kpi" && summary && (
        <div className="mt-4">
          <KpiCard label="In-scope spend" value={money(summary.period_cost, summary.currency)} hint={widgetHint(widget)} />
        </div>
      )}
      {widget.type === "timeseries" && <SpendChart series={series} currency="GBP" granularity={grain} />}
      {widget.type === "growth" && <CompareChart series={growth} currency="GBP" granularity={grain} />}
      {widget.type === "breakdown" && <BreakdownChart rows={rows} currency="GBP" />}
      {widget.type === "table" && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-mist-500">
              <tr>
                <th className="pb-2">Name</th>
                <th className="pb-2 text-right">Cost</th>
                <th className="pb-2 text-right">Share</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-t border-white/5">
                  <td className="py-2">{row.label}</td>
                  <td className="py-2 text-right font-mono">{money(row.cost)}</td>
                  <td className="py-2 text-right font-mono text-mist-400">{pct(row.share * 100)}</td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={3} className="py-6 text-center text-mist-500">
                    No cost matched these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {widget.type === "recommendations" && (
        <ul className="mt-4 space-y-3 text-sm">
          {recs.slice(0, 5).map((item) => (
            <li key={item.id}>
              <div className="font-medium">{item.title}</div>
              <div className="text-mist-400">{money(item.monthly_savings, item.currency)} / month</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
