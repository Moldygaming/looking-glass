"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { kindSwatch } from "@/lib/colors";
import { widgetQuery } from "@/lib/widgetQuery";
import type { BreakdownRow, CostFacets, Granularity, Widget } from "@/lib/types";

const TYPES: { id: Widget["type"]; label: string }[] = [
  { id: "table", label: "Table" },
  { id: "breakdown", label: "Breakdown chart" },
  { id: "growth", label: "Compare over time" },
  { id: "timeseries", label: "Total trend" },
  { id: "kpi", label: "KPI" },
  { id: "recommendations", label: "Savings" },
];

const GROUPS = [
  ["account", "Account / subscription"],
  ["resource", "Resource"],
  ["resource_group", "Resource group"],
  ["service", "Service"],
  ["resource_type", "Resource type"],
  ["category", "Category"],
  ["region", "Region"],
  ["provider", "Cloud"],
  ["org", "Organisation"],
  ["meter", "Meter"],
  ["tag:team", "Tag: team"],
  ["tag:project", "Tag: project"],
  ["tag:env", "Tag: env"],
];

const empty: Omit<Widget, "id"> = {
  type: "table",
  title: "",
  group_by: "account",
  date_range: "30d",
  granularity: "month",
  provider: "",
  category: "",
  resource_type: "",
  service: "",
  q: "",
  tag_filters: [{ key: "", value: "" }],
  item_keys: [],
  limit: 20,
};

export function WidgetBuilder({
  initial,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  initial?: Widget | null;
  onSubmit: (widget: Omit<Widget, "id"> & { id?: string }) => void;
  onCancel?: () => void;
  submitLabel: string;
}) {
  const [form, setForm] = useState<Omit<Widget, "id">>(() => ({ ...empty, ...stripId(initial) }));
  const [tags, setTags] = useState<Record<string, string[]>>({});
  const [facets, setFacets] = useState<CostFacets | null>(null);
  const [choices, setChoices] = useState<BreakdownRow[]>([]);

  useEffect(() => {
    api<Record<string, string[]>>("/costs/tags").then(setTags).catch(() => setTags({}));
    api<CostFacets>("/costs/facets").then(setFacets).catch(() => setFacets(null));
  }, []);

  useEffect(() => {
    if (form.type !== "growth") return;
    api<BreakdownRow[]>(`/costs/breakdown${widgetQuery({ ...form, id: "preview" } as Widget, { limit: 40 })}`)
      .then(setChoices)
      .catch(() => setChoices([]));
  }, [form.type, form.group_by, form.provider, form.category, form.resource_type, form.service, form.q, JSON.stringify(form.tag_filters)]);

  function set<K extends keyof Omit<Widget, "id">>(key: K, value: Omit<Widget, "id">[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  const provider = form.provider || "";
  const category = form.category || "";
  const resourceTypes = useMemo(() => {
    const rows = facets?.resource_types || [];
    return rows.filter((item) => (!provider || item.provider === provider) && (!category || item.category === category));
  }, [facets, provider, category]);
  const services = useMemo(() => {
    const rows = facets?.services || [];
    return rows.filter((item) => (!provider || item.provider === provider) && (!category || item.category === category));
  }, [facets, provider, category]);
  const categories = facets?.categories || [];
  const clouds = facets?.providers || ["azure", "aws", "gcp"];

  const tagRows = form.tag_filters?.length ? form.tag_filters : [{ key: "", value: "" }];
  const titlePlaceholder = useMemo(() => {
    const bits = [form.provider || "All clouds", form.category || form.resource_type || "all resources", `by ${form.group_by}`];
    return bits.join(" · ");
  }, [form.provider, form.category, form.resource_type, form.group_by]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="xl:col-span-2">
          <label className="label">Title</label>
          <input className="input" value={form.title || ""} placeholder={titlePlaceholder} onChange={(e) => set("title", e.target.value)} />
        </div>
        <div>
          <label className="label">Visualization</label>
          <select className="input" value={form.type} onChange={(e) => set("type", e.target.value as Widget["type"])}>
            {TYPES.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Group by</label>
          <select className="input" value={form.group_by} onChange={(e) => { set("group_by", e.target.value); set("item_keys", []); }}>
            {GROUPS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Cloud</label>
          <select
            className="input"
            value={form.provider || ""}
            onChange={(e) => {
              set("provider", e.target.value || null);
              set("resource_type", null);
              set("service", null);
            }}
          >
            <option value="">All clouds</option>
            {clouds.map((item) => (
              <option key={item} value={item}>
                {item === "azure" ? "Azure" : item === "aws" ? "AWS" : item === "gcp" ? "GCP" : item}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Category</label>
          <select
            className="input"
            value={form.category || ""}
            onChange={(e) => {
              set("category", e.target.value || null);
              set("resource_type", null);
              set("service", null);
            }}
          >
            <option value="">All categories</option>
            {categories.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Resource type</label>
          <select className="input" value={form.resource_type || ""} onChange={(e) => set("resource_type", e.target.value || null)}>
            <option value="">All resource types</option>
            {resourceTypes.map((item) => (
              <option key={`${item.provider}:${item.name}`} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Service</label>
          <select className="input" value={form.service || ""} onChange={(e) => set("service", e.target.value || null)}>
            <option value="">All services</option>
            {services.map((item) => (
              <option key={`${item.provider}:${item.name}`} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Search</label>
          <input className="input" value={form.q || ""} placeholder="Name contains…" onChange={(e) => set("q", e.target.value || null)} />
        </div>
        {(form.type === "growth" || form.type === "timeseries" || form.type === "kpi" || form.type === "table") && (
          <div>
            <label className="label">Time grain</label>
            <select className="input" value={form.granularity || "month"} onChange={(e) => set("granularity", e.target.value as Granularity)}>
              <option value="day">Daily</option>
              <option value="week">Weekly</option>
              <option value="month">Monthly</option>
            </select>
          </div>
        )}
      </div>

      <div>
        <label className="label">Tag filters</label>
        <div className="space-y-2">
          {tagRows.map((row, index) => (
            <div key={index} className="grid grid-cols-[1fr_1fr_auto] gap-2">
              <select
                className="input"
                value={row.key}
                onChange={(e) => {
                  const next = [...tagRows];
                  next[index] = { ...next[index], key: e.target.value, value: "" };
                  set("tag_filters", next);
                }}
              >
                <option value="">Tag key</option>
                {Object.keys(tags).map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>
              <select
                className="input"
                value={row.value}
                disabled={!row.key}
                onChange={(e) => {
                  const next = [...tagRows];
                  next[index] = { ...next[index], value: e.target.value };
                  set("tag_filters", next);
                }}
              >
                <option value="">Tag value</option>
                {(tags[row.key] || []).map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
              <button type="button" className="btn-ghost" onClick={() => set("tag_filters", tagRows.filter((_, i) => i !== index))}>
                Remove
              </button>
            </div>
          ))}
        </div>
        <button type="button" className="btn-ghost mt-2 text-xs" onClick={() => set("tag_filters", [...tagRows, { key: "", value: "" }])}>
          Add tag filter
        </button>
        <p className="hint">Categories, resource types and services come from cost already ingested from your clouds.</p>
      </div>

      {form.type === "growth" && (
        <div>
          <label className="label">Compare specific items (optional)</label>
          <p className="mb-2 text-xs text-mist-500">Leave empty to chart the top items after filters. Select up to 8 to pin them.</p>
          <div className="flex max-h-40 flex-wrap gap-2 overflow-y-auto">
            {choices.map((item) => {
              const on = (form.item_keys || []).includes(item.key);
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => {
                    const current = form.item_keys || [];
                    const next = on ? current.filter((key) => key !== item.key) : current.length >= 8 ? current : [...current, item.key];
                    set("item_keys", next);
                  }}
                  className={`chip ${on ? kindSwatch(form.group_by).chip : ""}`}
                >
                  {item.label}
                </button>
              );
            })}
            {!choices.length && <span className="text-xs text-mist-500">No items match these filters yet.</span>}
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          onClick={() =>
            onSubmit({
              ...form,
              title: form.title.trim() || titlePlaceholder,
              date_range: form.granularity === "month" ? "365d" : form.granularity === "week" ? "84d" : "30d",
              tag_filters: (form.tag_filters || []).filter((item) => item.key && item.value),
              item_keys: form.item_keys || [],
            })
          }
        >
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="btn-ghost" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

function stripId(widget?: Widget | null): Partial<Omit<Widget, "id">> {
  if (!widget) return {};
  const { id: _id, ...rest } = widget;
  return rest;
}
