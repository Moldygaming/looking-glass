"use client";

import { useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/Shell";
import { BreakdownChart } from "@/components/BreakdownChart";
import { CompareChart } from "@/components/CompareChart";
import { HierarchyTree } from "@/components/HierarchyTree";
import { api, qs } from "@/lib/api";
import { grainNoun } from "@/lib/format";
import type { BreakdownRow, Granularity, HierarchyNode, NamedSeries } from "@/lib/types";

export default function CostsPage() {
  const [provider, setProvider] = useState("");
  const [q, setQ] = useState("");
  const [granularity, setGranularity] = useState<Granularity>("day");
  const [breakdown, setBreakdown] = useState<BreakdownRow[]>([]);
  const [tree, setTree] = useState<HierarchyNode[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [series, setSeries] = useState<NamedSeries[]>([]);
  const [tagKey, setTagKey] = useState("");
  const [tagValue, setTagValue] = useState("");
  const [tags, setTags] = useState<Record<string, string[]>>({});

  useEffect(() => {
    api<Record<string, string[]>>("/costs/tags").then(setTags).catch(() => setTags({}));
  }, []);

  const filterQs = useMemo(
    () => ({ provider, q, tag_key: tagKey, tag_value: tagValue, granularity }),
    [provider, q, tagKey, tagValue, granularity]
  );

  useEffect(() => {
    api<BreakdownRow[]>(`/costs/breakdown${qs({ ...filterQs, group_by: "service", limit: 12 })}`)
      .then(setBreakdown)
      .catch(() => setBreakdown([]));
    api<HierarchyNode[]>(`/costs/tree${qs(filterQs)}`)
      .then(setTree)
      .catch(() => setTree([]));
    setSelected([]);
  }, [filterQs]);

  useEffect(() => {
    if (!selected.length) {
      setSeries([]);
      return;
    }
    api<NamedSeries[]>(`/costs/compare${qs({ ...filterQs, keys: selected.join(","), limit: 8 })}`)
      .then(setSeries)
      .catch(() => setSeries([]));
  }, [filterQs, selected]);

  function toggle(key: string) {
    setSelected((current) => {
      if (current.includes(key)) return current.filter((item) => item !== key);
      if (current.length >= 8) return current;
      return [...current, key];
    });
  }

  const grain = grainNoun(granularity);
  const currentLabel = granularity === "week" ? "This week" : granularity === "month" ? "This month" : "Today";
  const previousLabel = granularity === "week" ? "Last week" : granularity === "month" ? "Last month" : "Yesterday";

  return (
    <Shell>
      <h1 className="font-display text-3xl">Cost explorer</h1>
      <p className="mt-2 max-w-3xl text-sm text-mist-400">
        Group and compare cost by hierarchy: management groups, subscriptions, AWS accounts, GCP projects, resource
        groups and individual resources. Select any mix to chart {grain} growth.
      </p>
      <div className="mt-6 grid gap-3 md:grid-cols-4">
        <select className="input" value={granularity} onChange={(e) => setGranularity(e.target.value as Granularity)}>
          <option value="day">Daily</option>
          <option value="week">Weekly</option>
          <option value="month">Monthly</option>
        </select>
        <select className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="">All clouds</option>
          <option value="azure">Azure</option>
          <option value="aws">AWS</option>
          <option value="gcp">GCP</option>
        </select>
        <select
          className="input"
          value={tagKey}
          onChange={(e) => {
            setTagKey(e.target.value);
            setTagValue("");
          }}
        >
          <option value="">Any tag key</option>
          {Object.keys(tags).map((key) => (
            <option key={key} value={key}>
              {key}
            </option>
          ))}
        </select>
        <select className="input" value={tagValue} onChange={(e) => setTagValue(e.target.value)} disabled={!tagKey}>
          <option value="">Any value</option>
          {(tags[tagKey] || []).map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </div>
      <input
        className="input mt-3"
        placeholder="Search resource, subscription, account, project, resource group…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <section className="panel-pad mt-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm text-mist-400">
            Growth over time {selected.length ? `· ${selected.length} selected` : "· select scopes in the tree"}
          </h2>
          {selected.length > 0 && (
            <button className="text-xs text-mist-500 hover:text-mist-100" onClick={() => setSelected([])}>
              Clear selection
            </button>
          )}
        </div>
        <CompareChart series={series} currency={tree[0]?.currency || "GBP"} granularity={granularity} />
      </section>
      <div className="mt-6 grid gap-4 xl:grid-cols-5">
        <section className="panel-pad xl:col-span-2">
          <h2 className="mb-3 text-sm text-mist-400">By service</h2>
          <BreakdownChart rows={breakdown} currency={tree[0]?.currency || "GBP"} />
        </section>
        <section className="panel-pad xl:col-span-3">
          <h2 className="mb-3 text-sm text-mist-400">Hierarchy · {grain} cost</h2>
          <HierarchyTree
            nodes={tree}
            selected={selected}
            onToggle={toggle}
            currentLabel={currentLabel}
            previousLabel={previousLabel}
          />
        </section>
      </div>
    </Shell>
  );
}
