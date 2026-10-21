"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/Shell";
import { KpiCard } from "@/components/KpiCard";
import { ProviderBadge } from "@/components/ProviderBadge";
import { useMe } from "@/components/MeProvider";
import { api, qs } from "@/lib/api";
import { when } from "@/lib/format";
import { hasPrivilege } from "@/lib/iam";
import type {
  ServiceAdoProject,
  ServiceConnection,
  ServiceSummary,
  ServiceSync,
  ServiceWorkItem,
} from "@/lib/types";

const SOURCES = [
  { id: "", label: "All sources" },
  { id: "azure_devops", label: "Azure DevOps" },
  { id: "freshservice", label: "Freshservice" },
] as const;

const KINDS = [
  { id: "", label: "All types" },
  { id: "work_item", label: "Work items" },
  { id: "ticket", label: "Tickets" },
  { id: "problem", label: "Problems" },
  { id: "change", label: "Changes" },
] as const;

const KIND_LABEL: Record<string, string> = {
  work_item: "Work item",
  ticket: "Ticket",
  problem: "Problem",
  change: "Change",
};

export default function ServiceWorkPage() {
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "service.write", "connections.write");
  const canConnect = hasPrivilege(me, "connections.write");
  const [connections, setConnections] = useState<ServiceConnection[]>([]);
  const [summary, setSummary] = useState<ServiceSummary | null>(null);
  const [items, setItems] = useState<ServiceWorkItem[]>([]);
  const [source, setSource] = useState("");
  const [kind, setKind] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [mine, setMine] = useState(true);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [adoId, setAdoId] = useState("");
  const [projects, setProjects] = useState<ServiceAdoProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState<"load" | "sync" | "save" | "projects" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const adoConnections = useMemo(
    () => connections.filter((row) => row.provider === "azure_devops"),
    [connections]
  );
  const freshservice = useMemo(
    () => connections.filter((row) => row.provider === "freshservice"),
    [connections]
  );
  const selectedAdo = adoConnections.find((row) => row.id === adoId) || null;

  const loadItems = useCallback(
    async (next: { source: string; kind: string; showClosed: boolean; mine: boolean; q: string }) => {
      const searching = Boolean(next.q);
      const rows = await api<ServiceWorkItem[]>(
        `/service/items${qs({
          source: next.source,
          kind: next.kind,
          open_only: next.showClosed ? "false" : "true",
          assigned_to_me: searching || !next.mine ? "false" : "true",
          q: next.q,
        })}`
      );
      setItems(rows);
      return rows;
    },
    []
  );

  const loadProjects = useCallback(async (connection: ServiceConnection) => {
    if (!connection.credentials_configured) {
      setProjects([]);
      setProjectError("Add an organisation and personal access token before choosing a project.");
      return;
    }
    setBusy("projects");
    setProjectError(null);
    try {
      const rows = await api<ServiceAdoProject[]>(`/service/projects${qs({ connection_id: connection.id })}`);
      setProjects(rows);
      setProjectId((current) => {
        if (current && rows.some((row) => row.id === current)) return current;
        return connection.service_project_id || rows[0]?.id || "";
      });
    } catch (err) {
      setProjects([]);
      setProjectError(err instanceof Error ? err.message : "Could not list projects");
    } finally {
      setBusy((current) => (current === "projects" ? null : current));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await api<ServiceConnection[]>("/service/connections");
        if (cancelled) return;
        setConnections(rows);
        const ado = rows.find((row) => row.provider === "azure_devops");
        if (ado) {
          setAdoId(ado.id);
          setProjectId(ado.service_project_id || "");
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load service work");
      } finally {
        if (!cancelled) setBusy(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    if (!adoId) return;
    const connection = adoConnections.find((row) => row.id === adoId);
    if (!connection) return;
    setProjectId(connection.service_project_id || "");
    void loadProjects(connection);
  }, [adoId, adoConnections, loadProjects]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [counts] = await Promise.all([
          api<ServiceSummary>(`/service/summary${qs({ assigned_to_me: mine ? "true" : "false" })}`),
          loadItems({ source, kind, showClosed, mine, q: debouncedQuery }),
        ]);
        if (!cancelled) setSummary(counts);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load work");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source, kind, showClosed, mine, debouncedQuery, loadItems]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    // Once the server search has caught up, keep its rows. Assignee email is
    // matched on the server and is not on the row shown in the table.
    if (debouncedQuery.toLowerCase() === needle) return items;
    return items.filter((row) =>
      [row.title, row.external_id, row.state, row.priority, row.assignee, row.requester, row.project_name, row.item_type, row.connection_name]
        .join(" ")
        .toLowerCase()
        .includes(needle)
    );
  }, [items, query, debouncedQuery]);

  async function reload() {
    const [rows, counts] = await Promise.all([
      api<ServiceConnection[]>("/service/connections"),
      api<ServiceSummary>(`/service/summary${qs({ assigned_to_me: mine ? "true" : "false" })}`),
    ]);
    setConnections(rows);
    setSummary(counts);
    await loadItems({ source, kind, showClosed, mine, q: debouncedQuery });
  }

  async function saveProject() {
    if (!selectedAdo || !projectId) return;
    const project = projects.find((row) => row.id === projectId);
    if (!project) return;
    setBusy("save");
    setError(null);
    setMessage(null);
    try {
      const saved = await api<ServiceConnection>("/service/project", {
        method: "PUT",
        body: JSON.stringify({
          connection_id: selectedAdo.id,
          project_id: project.id,
          project_name: project.name,
        }),
      });
      setConnections((current) => current.map((row) => (row.id === saved.id ? saved : row)));
      setMessage(`Work items will come from ${saved.service_project_name}. Sync to load them.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the project");
    } finally {
      setBusy(null);
    }
  }

  async function sync() {
    setBusy("sync");
    setError(null);
    setMessage(null);
    try {
      const result = await api<ServiceSync>("/service/sync", { method: "POST" });
      await reload();
      const summaryText = `Sync finished. ${result.written} records from ${result.connections} connection${result.connections === 1 ? "" : "s"}.`;
      if (result.errors.length) setError(result.errors.join(" "));
      if (result.connections || !result.errors.length) setMessage(summaryText);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setBusy(null);
    }
  }

  const chosenName = selectedAdo?.service_project_name || "";

  return (
    <Shell>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-mist-500">Service</p>
          <h1 className="font-display text-3xl">Work</h1>
          <p className="mt-2 max-w-2xl text-sm text-mist-400">
            Azure DevOps work items from one project, plus Freshservice tickets, problems, and changes.
            {mine ? " Showing items assigned to you." : " Showing every assignee."}
            {summary?.last_sync_at ? ` Last sync ${when(summary.last_sync_at)}.` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canConnect && (
            <Link href="/connections/new" className="btn-ghost">
              Add connection
            </Link>
          )}
          {canWrite && (
            <button className="btn-primary" onClick={sync} disabled={Boolean(busy) || !connections.length}>
              {busy === "sync" ? "Syncing…" : "Sync"}
            </button>
          )}
        </div>
      </div>

      {error && <div className="panel-pad mt-6 text-sm text-rose">{error}</div>}
      {message && <div className="panel-pad mt-6 text-sm text-glass">{message}</div>}

      <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Open work items" value={String(summary?.open_work_items ?? 0)} hint={mine ? "Assigned to you" : chosenName || "One Azure DevOps project"} />
        <KpiCard label="Open tickets" value={String(summary?.open_tickets ?? 0)} hint={mine ? "Assigned to you" : "Freshservice"} />
        <KpiCard label="Open problems" value={String(summary?.open_problems ?? 0)} hint={mine ? "Assigned to you" : "Freshservice"} />
        <KpiCard label="Open changes" value={String(summary?.open_changes ?? 0)} hint={mine ? "Assigned to you" : "Freshservice"} />
      </div>

      {!connections.length && busy !== "load" && !error && (
        <div className="panel-pad mt-6 max-w-xl">
          <h2 className="font-display text-xl">Nothing connected yet</h2>
          <p className="mt-2 text-sm text-mist-400">
            Add a Freshservice connection, or an Azure DevOps connection, then choose one project and sync.
          </p>
          {canConnect && (
            <Link href="/connections/new" className="btn-primary mt-4 inline-flex">
              Add connection
            </Link>
          )}
        </div>
      )}

      {adoConnections.length > 0 && (
        <section className="panel-pad mt-6 space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="font-display text-xl">Azure DevOps project</h2>
              <p className="mt-1 text-sm text-mist-400">
                Work items come from one project. This is separate from the projects monitored on DevOps health.
                {chosenName ? ` Current project: ${chosenName}.` : " No project selected yet."}
              </p>
            </div>
            <ProviderBadge provider="azure_devops" />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="label">Connection</label>
              <select className="input" value={adoId} onChange={(e) => setAdoId(e.target.value)}>
                {adoConnections.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Project</label>
              <select
                className="input"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                disabled={!projects.length}
              >
                {!projects.length && <option value="">{busy === "projects" ? "Loading projects…" : "No projects loaded"}</option>}
                {projects.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {projectError && <p className="text-sm text-rose">{projectError}</p>}
          <div className="flex flex-wrap items-center gap-3">
            {canWrite && (
              <button className="btn-primary" onClick={saveProject} disabled={Boolean(busy) || !projectId}>
                {busy === "save" ? "Saving…" : "Use this project"}
              </button>
            )}
            {selectedAdo && (
              <Link href={`/connections/${selectedAdo.id}`} className="btn-ghost text-xs">
                Connection settings
              </Link>
            )}
          </div>
        </section>
      )}

      {freshservice.length > 0 && (
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <ProviderBadge provider="freshservice" />
          {freshservice.map((row) => (
            <Link key={row.id} href={`/connections/${row.id}`} className="chip hover:text-glass">
              {row.name}
              {row.domain ? ` · ${row.domain}` : ""}
              {row.last_error ? " · error" : ""}
            </Link>
          ))}
        </div>
      )}
      {freshservice.some((row) => row.last_error) && (
        <div className="panel-pad mt-4 text-sm text-rose">
          {freshservice
            .filter((row) => row.last_error)
            .map((row) => (
              <p key={row.id}>
                {row.name}: {row.last_error}
              </p>
            ))}
        </div>
      )}

      {connections.length > 0 && (
      <section className="panel-pad mt-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-display text-xl">Queue</h2>
            <p className="mt-1 text-sm text-mist-400">
              {visible.length} shown.{" "}
              {debouncedQuery
                ? "Search covers every assignee."
                : mine
                  ? "Assigned to you."
                  : "Every assignee."}{" "}
              Open items are the default. Closed records stay stored so you can include them.
            </p>
          </div>
          <input
            className="input max-w-xs"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search title, assignee, requester"
          />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {SOURCES.map((row) => (
            <button
              key={row.id || "all-sources"}
              className={source === row.id ? "tab tab-active" : "tab"}
              onClick={() => setSource(row.id)}
            >
              {row.label}
            </button>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {KINDS.map((row) => (
            <button
              key={row.id || "all-kinds"}
              className={kind === row.id ? "tab tab-active" : "tab"}
              onClick={() => setKind(row.id)}
            >
              {row.label}
            </button>
          ))}
          <label className="ml-1 flex items-center gap-2 text-sm text-mist-400">
            <input
              type="checkbox"
              className="accent-glass"
              checked={mine}
              onChange={(e) => setMine(e.target.checked)}
            />
            Assigned to me
          </label>
          <label className="flex items-center gap-2 text-sm text-mist-400">
            <input
              type="checkbox"
              className="accent-glass"
              checked={showClosed}
              onChange={(e) => setShowClosed(e.target.checked)}
            />
            Include closed
          </label>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Item</th>
                <th>State</th>
                <th>Priority</th>
                <th>People</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="chip">{KIND_LABEL[row.kind] || row.item_type || row.kind}</span>
                      {row.item_type && row.item_type !== KIND_LABEL[row.kind] && (
                        <span className="text-xs text-mist-500">{row.item_type}</span>
                      )}
                    </div>
                    {row.url ? (
                      <a className="mt-1 block hover:text-glass" href={row.url} target="_blank" rel="noreferrer">
                        #{row.external_id} {row.title}
                      </a>
                    ) : (
                      <div className="mt-1">
                        #{row.external_id} {row.title}
                      </div>
                    )}
                    <div className="mt-1 text-xs text-mist-500">
                      {row.connection_name}
                      {row.project_name ? ` · ${row.project_name}` : ""}
                    </div>
                  </td>
                  <td>{row.state || "—"}</td>
                  <td>{row.priority || "—"}</td>
                  <td>
                    <div>{row.assignee || "Unassigned"}</div>
                    {row.requester && <div className="text-xs text-mist-500">Requester {row.requester}</div>}
                  </td>
                  <td className="whitespace-nowrap font-mono text-xs">{when(row.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!visible.length && busy !== "load" && (
            <p className="mt-4 text-sm text-mist-500">
              {items.length || debouncedQuery
                ? "Nothing matches this search."
                : mine
                  ? "Nothing assigned to you in this view. Clear Assigned to me to see every item. Sync again so Freshservice assignees are stored."
                  : "No work in this view. Choose an Azure DevOps project or add Freshservice, then sync."}
            </p>
          )}
        </div>
      </section>
      )}
    </Shell>
  );
}
