"use client";

import { useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/Shell";
import { BreakdownChart } from "@/components/BreakdownChart";
import { CompareChart } from "@/components/CompareChart";
import { KpiCard } from "@/components/KpiCard";
import { ObjectTable } from "@/components/ObjectTable";
import { PathBuilder } from "@/components/PathBuilder";
import { api, qs } from "@/lib/api";
import { grainNoun, kindLabel, money, pct } from "@/lib/format";
import type {
  BreakdownRow,
  CostDimension,
  CostObject,
  CostObjectFocus,
  CostObjectPage,
  DimensionCatalog,
  Granularity,
  HierarchyPreset,
  LineItems,
  NamedSeries,
} from "@/lib/types";

const PATH_STORE = "lg.cost-path";

export default function CostsPage() {
  const [granularity, setGranularity] = useState<Granularity>("day");
  const [provider, setProvider] = useState("");
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [path, setPath] = useState<string[]>(["provider", "connection", "org", "account", "resource_group", "resource"]);
  const [focus, setFocus] = useState<CostObjectFocus[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [page, setPage] = useState<CostObjectPage | null>(null);
  const [catalog, setCatalog] = useState<DimensionCatalog | null>(null);
  const [splitBy, setSplitBy] = useState("service");
  const [breakdown, setBreakdown] = useState<BreakdownRow[]>([]);
  const [series, setSeries] = useState<NamedSeries[]>([]);
  const [lines, setLines] = useState<LineItems | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stored = window.localStorage.getItem(PATH_STORE);
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length) setPath(parsed);
      } catch {
        /* ignore */
      }
    }
    api<DimensionCatalog>("/costs/dimensions")
      .then((data) => {
        setCatalog(data);
        if (!stored && data.default_path?.length) setPath(data.default_path);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const handle = window.setTimeout(() => setSearch(q), 250);
    return () => window.clearTimeout(handle);
  }, [q]);

  const dimensions: CostDimension[] = catalog?.dimensions || [];
  const presets: HierarchyPreset[] = useMemo(() => {
    const base = catalog?.presets || [];
    const tagDims = dimensions.filter((item) => item.key.startsWith("tag:")).slice(0, 3).map((item) => item.key);
    if (!tagDims.length) return base;
    return [
      ...base,
      {
        id: "allocation",
        name: "Tag allocation",
        description: "Your tags, then service and resource.",
        path: [...tagDims, "service", "resource"],
      },
    ];
  }, [catalog, dimensions]);

  const focusKey = focus.map((item) => item.key).join("|");
  const filterQs = useMemo(
    () => ({
      provider,
      q: search,
      granularity,
      path: path.join(","),
      focus: focusKey,
    }),
    [provider, search, granularity, path, focusKey]
  );

  useEffect(() => {
    window.localStorage.setItem(PATH_STORE, JSON.stringify(path));
  }, [path]);

  useEffect(() => {
    setError(null);
    api<CostObjectPage>(`/costs/objects${qs(filterQs)}`)
      .then(setPage)
      .catch((err: Error) => {
        setPage(null);
        setError(err.message);
      });
    setSelected([]);
  }, [filterQs]);

  useEffect(() => {
    api<BreakdownRow[]>(`/costs/breakdown${qs({ ...filterQs, group_by: splitBy, limit: 12 })}`)
      .then(setBreakdown)
      .catch(() => setBreakdown([]));
  }, [filterQs, splitBy]);

  useEffect(() => {
    if (!selected.length) {
      setSeries([]);
      return;
    }
    api<NamedSeries[]>(`/costs/compare${qs({ ...filterQs, keys: selected.join(","), limit: 8 })}`)
      .then(setSeries)
      .catch(() => setSeries([]));
  }, [filterQs, selected]);

  useEffect(() => {
    api<LineItems>(`/costs/line-items${qs({ ...filterQs, limit: 25 })}`)
      .then(setLines)
      .catch(() => setLines(null));
  }, [filterQs]);

  function toggle(key: string) {
    setSelected((current) => {
      if (current.includes(key)) return current.filter((item) => item !== key);
      if (current.length >= 8) return current;
      return [...current, key];
    });
  }

  function drill(row: CostObject) {
    if (!row.has_children) return;
    setFocus((current) => [...current, { key: row.key, kind: row.kind, label: row.label }]);
  }

  function jumpTo(index: number) {
    setFocus((current) => current.slice(0, index));
  }

  function changePath(next: string[]) {
    setPath(next.length ? next : ["resource"]);
    setFocus([]);
  }

  const grain = grainNoun(granularity);
  const currency = page?.currency || "GBP";
  const currentKind = page?.current_kind;
  const splitOptions = dimensions.filter((item) => item.key !== currentKind);

  return (
    <Shell>
      <h1 className="font-display text-3xl">Cost explorer</h1>
      <p className="mt-2 max-w-3xl text-sm text-mist-400">
        Cost objects are the things you can cut spend by — clouds, accounts, tags, services, meters, resources. Stack
        them into any hierarchy, then drill from coarse to fine.
      </p>

      <div className="mt-6 grid gap-3 md:grid-cols-3">
        <select className="input" value={granularity} onChange={(e) => setGranularity(e.target.value as Granularity)}>
          <option value="day">Last 30 days · daily</option>
          <option value="week">Last 12 weeks · weekly</option>
          <option value="month">Last 12 months · monthly</option>
        </select>
        <select className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="">All clouds</option>
          <option value="azure">Azure</option>
          <option value="aws">AWS</option>
          <option value="gcp">GCP</option>
        </select>
        <input
          className="input"
          placeholder="Search this level…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <section className="panel-pad mt-6">
        <h2 className="mb-3 text-sm text-mist-400">Object hierarchy</h2>
        <PathBuilder path={path} dimensions={dimensions} presets={presets} onChange={changePath} />
      </section>

      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      {page && (
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <KpiCard
            label="This period"
            value={money(page.period_cost, currency)}
            hint={`${page.object_count} ${kindLabel(currentKind || "object").toLowerCase()}${page.object_count === 1 ? "" : "s"}`}
          />
          <KpiCard
            label="Prior period"
            value={money(page.prior_period_cost, currency)}
            hint="Same length, immediately before"
          />
          <KpiCard
            label="Change"
            value={page.delta_pct == null ? "—" : pct(page.delta_pct)}
            tone={page.delta_pct == null ? "default" : page.delta_pct > 8 ? "bad" : page.delta_pct < 0 ? "good" : "default"}
            hint={`Totals for the current ${grain} window`}
          />
        </div>
      )}

      <nav className="mt-6 flex flex-wrap items-center gap-2 text-sm">
        <button type="button" className={!focus.length ? "text-glass" : "text-mist-400 hover:text-mist-100"} onClick={() => setFocus([])}>
          All cost
        </button>
        {focus.map((item, index) => (
          <span key={item.key} className="flex items-center gap-2">
            <span className="text-mist-500">/</span>
            <button type="button" className="hover:text-glass" onClick={() => jumpTo(index + 1)}>
              <span className="text-xs text-mist-500">{kindLabel(item.kind)} · </span>
              {item.label}
            </button>
          </span>
        ))}
        {currentKind && <span className="text-mist-500">/ {kindLabel(currentKind)}</span>}
      </nav>

      <section className="panel-pad mt-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm text-mist-400">
            Compare {selected.length ? `· ${selected.length} selected` : "· tick objects below"}
          </h2>
          {selected.length > 0 && (
            <button className="text-xs text-mist-500 hover:text-mist-100" onClick={() => setSelected([])}>
              Clear selection
            </button>
          )}
        </div>
        <CompareChart series={series} currency={currency} granularity={granularity} />
      </section>

      <section className="panel-pad mt-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm text-mist-400">
            {currentKind ? kindLabel(currentKind) : "Objects"} · period vs prior
          </h2>
          {page?.next_kind && <p className="text-xs text-mist-500">Open a row to drill into {kindLabel(page.next_kind)}</p>}
        </div>
        <ObjectTable
          rows={page?.objects || []}
          selected={selected}
          currency={currency}
          currentKind={currentKind ?? null}
          onToggle={toggle}
          onDrill={drill}
        />
      </section>

      <div className="mt-6 grid gap-4 xl:grid-cols-5">
        <section className="panel-pad xl:col-span-2">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-sm text-mist-400">Split</h2>
            <select className="input max-w-[180px] py-1 text-xs" value={splitBy} onChange={(e) => setSplitBy(e.target.value)}>
              {splitOptions.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <BreakdownChart rows={breakdown} currency={currency} />
        </section>
        <section className="panel-pad xl:col-span-3">
          <h2 className="mb-3 text-sm text-mist-400">
            Line items {lines ? `· ${lines.total}` : ""} in this scope
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-mist-500">
                <tr>
                  <th className="pb-2">When</th>
                  <th className="pb-2">Resource</th>
                  <th className="pb-2">Service</th>
                  <th className="pb-2 text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {(lines?.items || []).map((item) => (
                  <tr key={item.id} className="border-t border-white/5">
                    <td className="py-2 font-mono text-xs text-mist-400">{item.usage_date}</td>
                    <td className="py-2">{item.resource_name}</td>
                    <td className="py-2 text-mist-400">{item.service}</td>
                    <td className="py-2 text-right font-mono">{money(item.cost, item.currency)}</td>
                  </tr>
                ))}
                {!lines?.items.length && (
                  <tr>
                    <td colSpan={4} className="py-6 text-center text-mist-500">
                      No line items in this scope.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </Shell>
  );
}
