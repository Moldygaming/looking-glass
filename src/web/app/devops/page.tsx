"use client";

import Link from "next/link";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/Shell";
import { KpiCard } from "@/components/KpiCard";
import { ProviderBadge } from "@/components/ProviderBadge";
import { useMe } from "@/components/MeProvider";
import { api, qs } from "@/lib/api";
import { ageLabel, when } from "@/lib/format";
import { hasPrivilege } from "@/lib/iam";
import type { Connection, DevOpsProject, DevOpsReport, DevOpsScan } from "@/lib/types";

function pct(value: number) {
  return `${Math.round(value * 100)}%`;
}

const PROJECTS_STORE = "lg.devops.projects.collapsed";

export default function DevOpsHealthPage() {
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "devops.write", "connections.write");
  const [orgs, setOrgs] = useState<Connection[]>([]);
  const [connectionId, setConnectionId] = useState<string>("");
  const [report, setReport] = useState<DevOpsReport | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [projectFilter, setProjectFilter] = useState<string>("all");
  const [projectsOpen, setProjectsOpen] = useState(true);
  const [projectQuery, setProjectQuery] = useState("");
  const [busy, setBusy] = useState<"load" | "save" | "refresh" | "scan" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadOrgs = useCallback(async () => {
    const rows = await api<Connection[]>("/devops/connections");
    setOrgs(rows);
    return rows;
  }, []);

  const loadReport = useCallback(async (id: string) => {
    const data = await api<DevOpsReport>(`/devops/report${qs({ connection_id: id })}`);
    setReport(data);
    setSelected(data.projects.filter((row) => row.monitored).map((row) => row.ado_project_id));
    setError(data.last_error ?? null);
    return data;
  }, []);

  useEffect(() => {
    if (window.localStorage.getItem(PROJECTS_STORE) === "1") setProjectsOpen(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await loadOrgs();
        if (cancelled) return;
        if (!rows.length) {
          setBusy(null);
          return;
        }
        const id = rows[0].id;
        setConnectionId(id);
        await loadReport(id);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load DevOps health");
      } finally {
        if (!cancelled) setBusy(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadOrgs, loadReport]);

  async function switchOrg(id: string) {
    setConnectionId(id);
    setBusy("load");
    setMessage(null);
    try {
      await loadReport(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load report");
    } finally {
      setBusy(null);
    }
  }

  async function saveSelection() {
    if (!connectionId) return;
    setBusy("save");
    setError(null);
    setMessage(null);
    try {
      const projects = await api<DevOpsProject[]>("/devops/projects", {
        method: "PUT",
        body: JSON.stringify({ connection_id: connectionId, project_ids: selected }),
      });
      setReport((current) => (current ? { ...current, projects } : current));
      setMessage(`Monitoring ${projects.filter((row) => row.monitored).length} project${projects.filter((row) => row.monitored).length === 1 ? "" : "s"}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save project selection");
    } finally {
      setBusy(null);
    }
  }

  async function refreshProjects() {
    if (!connectionId) return;
    setBusy("refresh");
    setError(null);
    setMessage(null);
    try {
      const projects = await api<DevOpsProject[]>(`/devops/projects/refresh${qs({ connection_id: connectionId })}`, {
        method: "POST",
      });
      setReport((current) => (current ? { ...current, projects } : current));
      setSelected((current) => {
        const known = new Set(projects.map((row) => row.ado_project_id));
        const kept = current.filter((id) => known.has(id));
        return kept.length ? kept : projects.filter((row) => row.monitored).map((row) => row.ado_project_id);
      });
      setMessage(`Loaded ${projects.length} project${projects.length === 1 ? "" : "s"} from Azure DevOps.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load projects");
    } finally {
      setBusy(null);
    }
  }

  async function runScan() {
    if (!connectionId) return;
    setBusy("scan");
    setError(null);
    setMessage(null);
    try {
      if (report) {
        await api<DevOpsProject[]>("/devops/projects", {
          method: "PUT",
          body: JSON.stringify({ connection_id: connectionId, project_ids: selected }),
        });
      }
      const result = await api<DevOpsScan>(`/devops/scan${qs({ connection_id: connectionId })}`, { method: "POST" });
      await loadReport(connectionId);
      setMessage(
        `Checked ${result.projects} project${result.projects === 1 ? "" : "s"}: ${result.pull_requests} active PRs, ${result.stale_branches} stale branches, ${result.pipeline_alerts} pipeline alerts.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Health check failed");
    } finally {
      setBusy(null);
    }
  }

  const filteredPrs = useMemo(() => {
    const rows = report?.repositories_with_pull_requests || [];
    if (projectFilter === "all") return rows;
    return rows.filter((row) => row.ado_project_id === projectFilter);
  }, [report, projectFilter]);

  const filteredStale = useMemo(() => {
    const rows = report?.repositories_with_stale_branches || [];
    if (projectFilter === "all") return rows;
    return rows.filter((row) => row.ado_project_id === projectFilter);
  }, [report, projectFilter]);

  const filteredAlerts = useMemo(() => {
    const rows = report?.pipeline_alerts || [];
    if (projectFilter === "all") return rows;
    return rows.filter((row) => row.ado_project_id === projectFilter);
  }, [report, projectFilter]);

  const visibleProjects = useMemo(() => {
    const rows = report?.projects || [];
    const needle = projectQuery.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) => `${row.name} ${row.description || ""} ${row.state || ""}`.toLowerCase().includes(needle));
  }, [report, projectQuery]);

  function toggleProjects() {
    setProjectsOpen((open) => {
      const next = !open;
      window.localStorage.setItem(PROJECTS_STORE, next ? "0" : "1");
      return next;
    });
  }

  function selectShown() {
    const ids = visibleProjects.map((row) => row.ado_project_id);
    setSelected((current) => Array.from(new Set([...current, ...ids])));
  }

  function clearShown() {
    const hide = new Set(visibleProjects.map((row) => row.ado_project_id));
    setSelected((current) => current.filter((id) => !hide.has(id)));
  }

  const dirty = useMemo(() => {
    const current = new Set(selected);
    const saved = new Set((report?.projects || []).filter((row) => row.monitored).map((row) => row.ado_project_id));
    if (current.size !== saved.size) return true;
    for (const id of current) if (!saved.has(id)) return true;
    return false;
  }, [selected, report]);

  if (!orgs.length && busy !== "load") {
    return (
      <Shell>
        <p className="text-xs uppercase tracking-[0.18em] text-mist-500">DevOps</p>
        <h1 className="font-display text-3xl">Azure DevOps health</h1>
        <p className="mt-2 max-w-2xl text-sm text-mist-400">
          Connect an Azure DevOps organisation, pick the projects to watch, then review active pull requests, stale
          branches and pipelines that keep failing.
        </p>
        {error && <div className="panel-pad mt-6 text-rose">{error}</div>}
        <div className="panel-pad mt-8 max-w-xl">
          <h2 className="font-display text-xl">No organisation connected</h2>
          <p className="mt-2 text-sm text-mist-400">
            Add an Azure DevOps connection with the organisation name and a personal access token.
          </p>
          {canWrite && (
            <Link href="/connections/new" className="btn-primary mt-4 inline-flex">
              Add Azure DevOps
            </Link>
          )}
        </div>
      </Shell>
    );
  }

  const summary = report?.summary;
  const monitored = report?.projects.filter((row) => row.monitored) || [];

  return (
    <Shell>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-mist-500">DevOps</p>
          <h1 className="font-display text-3xl">Azure DevOps health</h1>
          <p className="mt-2 max-w-2xl text-sm text-mist-400">
            Repositories with open pull requests, branches left idle, and pipelines that fail run after run.
            {report?.last_scan_at ? ` Last check ${when(report.last_scan_at)}.` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {orgs.map((org) => (
            <button
              key={org.id}
              className={org.id === connectionId ? "tab tab-active" : "tab"}
              onClick={() => switchOrg(org.id)}
            >
              {org.name}
            </button>
          ))}
        </div>
      </div>

      {report && (
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <ProviderBadge provider="azure_devops" />
          <span className="chip">{report.organization || "organisation"}</span>
          {report.credentials_configured ? (
            <span className="chip text-glass">token configured</span>
          ) : (
            <span className="chip text-warn">demo snapshot · add a PAT to refresh live</span>
          )}
          <Link href={`/connections/${report.connection_id}`} className="btn-ghost text-xs">
            Connection settings
          </Link>
        </div>
      )}

      {error && <div className="panel-pad mt-6 text-sm text-rose">{error}</div>}
      {message && <div className="panel-pad mt-6 text-sm text-glass">{message}</div>}

      <section className="panel-pad mt-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <button
            type="button"
            className="group flex min-w-0 items-start gap-2 text-left"
            onClick={toggleProjects}
            aria-expanded={projectsOpen}
          >
            <span className="mt-1 text-mist-400 group-hover:text-glass">
              {projectsOpen ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
            </span>
            <span>
              <h2 className="font-display text-xl">
                Projects to monitor
                <span className="ml-2 font-sans text-sm font-normal text-mist-500">
                  {selected.length}/{report?.projects.length ?? 0}
                </span>
              </h2>
              <p className="mt-1 text-sm text-mist-400">
                {projectsOpen
                  ? "Health checks only run on the projects you select. Load the list from Azure DevOps, then save and run a check."
                  : `${selected.length} of ${report?.projects.length ?? 0} projects selected${dirty ? " · unsaved changes" : ""}.`}
              </p>
            </span>
          </button>
          {canWrite && (
            <div className="flex flex-wrap gap-2">
              <button
                className="btn-ghost"
                onClick={refreshProjects}
                disabled={Boolean(busy) || !report?.credentials_configured}
              >
                {busy === "refresh" ? "Loading…" : "Load from Azure DevOps"}
              </button>
              <button className="btn-ghost" onClick={saveSelection} disabled={Boolean(busy) || !dirty}>
                {busy === "save" ? "Saving…" : "Save selection"}
              </button>
              <button
                className="btn-primary"
                onClick={runScan}
                disabled={Boolean(busy) || selected.length === 0 || !report?.credentials_configured}
              >
                {busy === "scan" ? "Checking…" : "Run health check"}
              </button>
            </div>
          )}
        </div>
        {projectsOpen && (
          <>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <input
                className="input max-w-xs"
                placeholder="Filter projects…"
                value={projectQuery}
                onChange={(event) => setProjectQuery(event.target.value)}
              />
              {canWrite && (
                <>
                  <button className="btn-ghost" type="button" onClick={selectShown} disabled={Boolean(busy) || visibleProjects.length === 0}>
                    Select shown
                  </button>
                  <button className="btn-ghost" type="button" onClick={clearShown} disabled={Boolean(busy) || visibleProjects.length === 0}>
                    Clear shown
                  </button>
                </>
              )}
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {visibleProjects.map((project) => {
                const checked = selected.includes(project.ado_project_id);
                return (
                  <label
                    key={project.ado_project_id}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-3 ${
                      checked ? "border-glass/40 bg-glass/5" : "border-white/10 bg-white/[0.02]"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={checked}
                      disabled={!canWrite || Boolean(busy)}
                      onChange={() =>
                        setSelected((current) =>
                          current.includes(project.ado_project_id)
                            ? current.filter((id) => id !== project.ado_project_id)
                            : [...current, project.ado_project_id]
                        )
                      }
                    />
                    <span>
                      <span className="block text-sm font-medium">{project.name}</span>
                      <span className="mt-0.5 block text-xs text-mist-500">
                        {project.description || project.state}
                        {project.last_scan_at ? ` · scanned ${when(project.last_scan_at)}` : ""}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
            {report && report.projects.length === 0 && (
              <p className="mt-3 text-sm text-mist-500">
                No projects loaded yet. Use Load from Azure DevOps after the PAT is saved.
              </p>
            )}
            {report && report.projects.length > 0 && visibleProjects.length === 0 && (
              <p className="mt-3 text-sm text-mist-500">No projects match that filter.</p>
            )}
          </>
        )}
      </section>

      {summary && (
        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            label="Monitored projects"
            value={String(summary.monitored)}
            hint={`${summary.projects} in the organisation`}
          />
          <KpiCard
            label="Active pull requests"
            value={String(summary.active_pull_requests)}
            hint={`${summary.repositories_with_pull_requests} repositories`}
            tone={summary.active_pull_requests > 0 ? "warn" : "good"}
          />
          <KpiCard
            label="Stale branches"
            value={String(summary.stale_branches)}
            hint={`Idle ${report?.thresholds.stale_days || 30}+ days · ${summary.repositories_with_stale_branches} repos`}
            tone={summary.stale_branches > 0 ? "warn" : "good"}
          />
          <KpiCard
            label="Failing pipelines"
            value={String(summary.failing_pipelines)}
            hint={`${report?.thresholds.fail_consecutive || 3} in a row, or ${pct(report?.thresholds.fail_rate || 0.75)} of recent runs`}
            tone={summary.failing_pipelines > 0 ? "bad" : "good"}
          />
        </div>
      )}

      {monitored.length > 1 && (
        <div className="mt-6 flex flex-wrap gap-2">
          <button className={projectFilter === "all" ? "tab tab-active" : "tab"} onClick={() => setProjectFilter("all")}>
            All monitored
          </button>
          {monitored.map((project) => (
            <button
              key={project.ado_project_id}
              className={projectFilter === project.ado_project_id ? "tab tab-active" : "tab"}
              onClick={() => setProjectFilter(project.ado_project_id)}
            >
              {project.name}
            </button>
          ))}
        </div>
      )}

      <section className="mt-6">
        <h2 className="font-display text-xl">Repositories with active pull requests</h2>
        <p className="mt-1 text-sm text-mist-400">Open PRs grouped by repository. Older reviews are listed first.</p>
        <div className="mt-4 grid gap-4">
          {filteredPrs.map((repo) => (
            <article key={`${repo.ado_project_id}-${repo.repo_id}`} className="panel-pad">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="chip">{repo.project_name}</span>
                    <a className="font-medium hover:text-glass" href={repo.url} target="_blank" rel="noreferrer">
                      {repo.repo_name}
                    </a>
                  </div>
                  <p className="mt-1 text-xs text-mist-500">
                    {repo.pr_count} open · oldest {ageLabel(repo.oldest_age_days)}
                  </p>
                </div>
              </div>
              <div className="mt-4 overflow-x-auto">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Pull request</th>
                      <th>Author</th>
                      <th>Age</th>
                      <th>Reviewers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {repo.pull_requests.map((pr) => (
                      <tr key={pr.id}>
                        <td>
                          <a className="hover:text-glass" href={pr.url} target="_blank" rel="noreferrer">
                            #{pr.pr_id} {pr.title}
                          </a>
                          <div className="mt-1 text-xs text-mist-500">
                            {pr.source_branch} → {pr.target_branch}
                            {pr.is_draft ? " · draft" : ""}
                          </div>
                        </td>
                        <td>{pr.created_by || "—"}</td>
                        <td className="font-mono">{ageLabel(pr.age_days)}</td>
                        <td className="font-mono">{pr.reviewer_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          ))}
          {!filteredPrs.length && <p className="text-sm text-mist-500">No active pull requests in the selected projects.</p>}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="font-display text-xl">Repositories with stale branches</h2>
        <p className="mt-1 text-sm text-mist-400">
          Topic branches whose last commit is older than {report?.thresholds.stale_days || 30} days. Default branches are
          ignored.
        </p>
        <div className="mt-4 grid gap-4">
          {filteredStale.map((repo) => (
            <article key={`${repo.ado_project_id}-${repo.repo_id}`} className="panel-pad">
              <div className="flex flex-wrap items-center gap-2">
                <span className="chip">{repo.project_name}</span>
                <a className="font-medium hover:text-glass" href={repo.url} target="_blank" rel="noreferrer">
                  {repo.repo_name}
                </a>
                <span className="text-xs text-mist-500">
                  {repo.branch_count} stale · oldest {ageLabel(repo.oldest_days)}
                </span>
              </div>
              <div className="mt-4 overflow-x-auto">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Branch</th>
                      <th>Last committer</th>
                      <th>Idle</th>
                    </tr>
                  </thead>
                  <tbody>
                    {repo.branches.map((branch) => (
                      <tr key={branch.id}>
                        <td>
                          <a className="font-mono text-sm hover:text-glass" href={branch.url} target="_blank" rel="noreferrer">
                            {branch.branch_name}
                          </a>
                        </td>
                        <td>{branch.last_commit_by || "—"}</td>
                        <td className="font-mono text-warn">{ageLabel(branch.days_stale)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          ))}
          {!filteredStale.length && <p className="text-sm text-mist-500">No stale branches in the selected projects.</p>}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="font-display text-xl">Pipelines consistently failing</h2>
        <p className="mt-1 text-sm text-mist-400">
          Alerts when the latest {report?.thresholds.fail_consecutive || 3} completed runs all failed, or when at least{" "}
          {pct(report?.thresholds.fail_rate || 0.75)} of the last {report?.thresholds.pipeline_lookback || 8} runs failed.
        </p>
        <div className="mt-4 grid gap-4">
          {filteredAlerts.map((alert) => (
            <article key={alert.id} className="panel-pad border-rose/20">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="chip text-rose">alert</span>
                    <span className="chip">{alert.project_name}</span>
                    <a className="font-medium hover:text-glass" href={alert.url} target="_blank" rel="noreferrer">
                      {alert.pipeline_name}
                    </a>
                  </div>
                  <p className="mt-2 text-sm text-mist-400">
                    {alert.reason === "consecutive"
                      ? `${alert.consecutive_failures} consecutive failed runs.`
                      : `${alert.failure_count} of the last ${alert.run_count} runs failed (${pct(alert.failure_rate)}).`}
                    {alert.last_run_at ? ` Last run ${when(alert.last_run_at)}.` : ""}
                  </p>
                </div>
                <div className="text-right">
                  <div className="font-mono text-xl text-rose">{alert.consecutive_failures} in a row</div>
                  <div className="text-xs text-mist-500">{pct(alert.failure_rate)} fail rate</div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {alert.recent_results.map((run, index) => {
                  const failed = (run.result || "").toLowerCase().includes("fail") || run.result === "partiallySucceeded";
                  return (
                    <span
                      key={`${run.id || index}`}
                      className={`chip ${failed ? "border-rose/30 text-rose" : "text-glass"}`}
                      title={run.buildNumber || String(run.id || index)}
                    >
                      {failed ? "fail" : "ok"}
                    </span>
                  );
                })}
              </div>
            </article>
          ))}
          {!filteredAlerts.length && (
            <p className="text-sm text-mist-500">No pipelines are consistently failing in the selected projects.</p>
          )}
        </div>
      </section>
    </Shell>
  );
}
