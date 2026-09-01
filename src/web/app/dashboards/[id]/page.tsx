"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { KpiCard } from "@/components/KpiCard";
import { SpendChart } from "@/components/SpendChart";
import { BreakdownChart } from "@/components/BreakdownChart";
import { CompareChart } from "@/components/CompareChart";
import { kindSwatch } from "@/lib/colors";
import { api, qs } from "@/lib/api";
import { money } from "@/lib/format";
import type { BreakdownRow, CostPoint, CostSummary, Dashboard, Granularity, NamedSeries, Recommendation, Widget } from "@/lib/types";

export default function DashboardDetailPage() {
  const params = useParams<{ id: string }>();
  const [board, setBoard] = useState<Dashboard | null>(null);
  const [draft, setDraft] = useState("");
  const [widgetType, setWidgetType] = useState<Widget["type"]>("growth");
  const [groupBy, setGroupBy] = useState("resource");
  const [granularity, setGranularity] = useState<Granularity>("week");
  const [choices, setChoices] = useState<BreakdownRow[]>([]);
  const [picked, setPicked] = useState<string[]>([]);

  function load() {
    api<Dashboard>(`/dashboards/${params.id}`).then((d) => {
      setBoard(d);
      setDraft(d.name);
    });
  }

  useEffect(load, [params.id]);

  useEffect(() => {
    if (widgetType !== "growth") return;
    api<BreakdownRow[]>(`/costs/breakdown${qs({ group_by: groupBy, limit: 40 })}`)
      .then(setChoices)
      .catch(() => setChoices([]));
  }, [widgetType, groupBy]);

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
  }

  async function addWidget() {
    if (!board) return;
    const widget: Widget = {
      id: `w-${Date.now()}`,
      type: widgetType,
      title:
        widgetType === "growth"
          ? `Growth · ${picked.length ? `${picked.length} items` : groupBy} · ${granularity}`
          : `${widgetType} · ${groupBy}`,
      group_by: groupBy,
      date_range: granularity === "month" ? "365d" : granularity === "week" ? "84d" : "30d",
      granularity,
      item_keys:
        widgetType === "growth"
          ? picked.map((key) =>
              ["management_group", "subscription", "resource_group", "account", "project", "resource"].includes(groupBy) &&
              !key.startsWith(`${groupBy}:`)
                ? `${groupBy}:${key}`
                : key
            )
          : [],
    };
    await save({ ...board, widgets: [...board.widgets, widget] });
    setPicked([]);
  }

  async function removeWidget(id: string) {
    if (!board) return;
    await save({ ...board, widgets: board.widgets.filter((w) => w.id !== id) });
  }

  function toggleItem(key: string) {
    setPicked((current) => {
      if (current.includes(key)) return current.filter((item) => item !== key);
      if (current.length >= 8) return current;
      return [...current, key];
    });
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
      <div className="flex flex-wrap items-end justify-between gap-3">
        <input
          className="bg-transparent font-display text-3xl outline-none"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => draft !== board.name && save({ ...board, name: draft })}
        />
      </div>
      <div className="panel-pad mt-6 space-y-3">
        <div className="flex flex-wrap gap-2">
          <select className="input w-40" value={widgetType} onChange={(e) => setWidgetType(e.target.value as Widget["type"])}>
            <option value="growth">Growth over time</option>
            <option value="kpi">KPI</option>
            <option value="timeseries">Total time series</option>
            <option value="breakdown">Breakdown</option>
            <option value="table">Table</option>
            <option value="recommendations">Savings</option>
          </select>
          <select className="input w-48" value={groupBy} onChange={(e) => { setGroupBy(e.target.value); setPicked([]); }}>
            <option value="management_group">Management group / org</option>
            <option value="subscription">Azure subscription</option>
            <option value="resource_group">Azure resource group</option>
            <option value="account">AWS account</option>
            <option value="project">GCP project</option>
            <option value="resource">Resource</option>
            <option value="service">Service</option>
            <option value="provider">Provider</option>
            <option value="tag:team">Tag: team</option>
            <option value="tag:project">Tag: project</option>
          </select>
          {(widgetType === "growth" || widgetType === "timeseries") && (
            <select className="input w-36" value={granularity} onChange={(e) => setGranularity(e.target.value as Granularity)}>
              <option value="day">Daily</option>
              <option value="week">Weekly</option>
              <option value="month">Monthly</option>
            </select>
          )}
          <button className="btn-primary" onClick={addWidget} disabled={widgetType === "growth" && picked.length === 0}>
            Add widget
          </button>
        </div>
        {widgetType === "growth" && (
          <div>
            <p className="mb-2 text-xs text-mist-500">
              Select up to 8 items at this hierarchy level. The widget charts their {granularity} cost.
            </p>
            <div className="flex max-h-40 flex-wrap gap-2 overflow-y-auto">
              {choices.map((item) => {
                const on = picked.includes(item.key);
                return (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => toggleItem(item.key)}
                    className={`chip ${on ? kindSwatch(groupBy).chip : ""}`}
                  >
                    {item.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
      <div className="mt-8 grid gap-4 lg:grid-cols-2">
        {board.widgets.map((widget) => (
          <WidgetCard key={widget.id} widget={widget} onRemove={() => removeWidget(widget.id)} />
        ))}
      </div>
    </Shell>
  );
}

function WidgetCard({ widget, onRemove }: { widget: Widget; onRemove: () => void }) {
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [series, setSeries] = useState<CostPoint[]>([]);
  const [rows, setRows] = useState<BreakdownRow[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [growth, setGrowth] = useState<NamedSeries[]>([]);
  const grain = widget.granularity || "day";

  useEffect(() => {
    const params = qs({
      group_by: widget.group_by,
      provider: widget.provider,
      tag_key: widget.tag_key,
      tag_value: widget.tag_value,
      granularity: grain,
    });
    if (widget.type === "kpi") api<CostSummary>("/costs/summary").then(setSummary);
    if (widget.type === "timeseries") api<CostPoint[]>(`/costs/series${params}`).then(setSeries);
    if (widget.type === "breakdown" || widget.type === "table") {
      api<BreakdownRow[]>(`/costs/breakdown${qs({ group_by: widget.group_by, limit: 8 })}`).then(setRows);
    }
    if (widget.type === "recommendations") api<Recommendation[]>("/recommendations").then(setRecs);
    if (widget.type === "growth") {
      api<NamedSeries[]>(
        `/costs/compare${qs({
          group_by: widget.group_by,
          granularity: grain,
          keys: (widget.item_keys || []).join(","),
          limit: 8,
        })}`
      ).then(setGrowth);
    }
  }, [widget, grain]);

  return (
    <section className={`panel-pad ${widget.type === "timeseries" || widget.type === "growth" ? "lg:col-span-2" : ""}`}>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm text-mist-400">{widget.title}</h2>
        <button className="text-xs text-mist-500 hover:text-rose" onClick={onRemove}>
          Remove
        </button>
      </div>
      {widget.type === "kpi" && summary && (
        <KpiCard label="In-scope spend" value={money(summary.period_cost, summary.currency)} hint={`${summary.open_recommendations} open savings`} />
      )}
      {widget.type === "timeseries" && <SpendChart series={series} currency="GBP" />}
      {widget.type === "growth" && <CompareChart series={growth} currency="GBP" granularity={grain} />}
      {widget.type === "breakdown" && <BreakdownChart rows={rows} currency="GBP" />}
      {widget.type === "table" && (
        <ul className="space-y-2 text-sm">
          {rows.map((r) => (
            <li key={r.key} className="flex justify-between border-b border-white/5 pb-2">
              <span>{r.label}</span>
              <span className="font-mono">{money(r.cost)}</span>
            </li>
          ))}
        </ul>
      )}
      {widget.type === "recommendations" && (
        <ul className="space-y-3 text-sm">
          {recs.slice(0, 5).map((r) => (
            <li key={r.id}>
              <div className="font-medium">{r.title}</div>
              <div className="text-mist-400">{money(r.monthly_savings, r.currency)} / month</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
