"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { useEntraTenant } from "@/components/EntraTenantProvider";
import { useMe } from "@/components/MeProvider";
import { api, qs } from "@/lib/api";
import { when } from "@/lib/format";
import { hasPrivilege } from "@/lib/iam";
import type { EntraTemplate, EntraUser } from "@/lib/types";

export default function DirectoryUsersPage() {
  const { me } = useMe();
  const { tenantId } = useEntraTenant();
  const canWrite = hasPrivilege(me, "admin.entra.write");
  const [rows, setRows] = useState<EntraUser[]>([]);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [upn, setUpn] = useState("");
  const [title, setTitle] = useState("");
  const [department, setDepartment] = useState("");
  const [location, setLocation] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [templates, setTemplates] = useState<EntraTemplate[]>([]);
  const [created, setCreated] = useState<EntraUser | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    if (!tenantId) {
      setRows([]);
      return;
    }
    api<EntraUser[]>(`/admin/entra/users${qs({ tenant_id: tenantId, q: q.trim(), status })}`)
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    if (!tenantId) {
      setTemplates([]);
      return;
    }
    api<EntraTemplate[]>(`/admin/entra/templates${qs({ tenant_id: tenantId })}`)
      .then(setTemplates)
      .catch(() => setTemplates([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  function applyTemplate(id: string) {
    setTemplateId(id);
    const template = templates.find((row) => row.id === id);
    if (!template) return;
    if (template.job_title) setTitle(template.job_title);
    if (template.department) setDepartment(template.department);
    if (template.usage_location) setLocation(template.usage_location);
  }

  async function createUser() {
    setSaving(true);
    setError(null);
    setCreated(null);
    try {
      const user = await api<EntraUser>("/admin/entra/users", {
        method: "POST",
        body: JSON.stringify({
          tenant_id: tenantId,
          display_name: name.trim(),
          user_principal_name: upn.trim(),
          job_title: title,
          department,
          usage_location: location.trim().toUpperCase(),
          template_id: templateId || null,
        }),
      });
      setCreated(user);
      setName("");
      setUpn("");
      setTitle("");
      setDepartment("");
      setLocation("");
      setTemplateId("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create user");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h2 className="font-display text-2xl">Entra users</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        These identities live in Microsoft Entra. Create, disable, and edit them here; Looking Glass keeps a synced copy.
      </p>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}
      {created?.temporary_password && (
        <div className="panel-pad mt-4 text-sm">
          Created <span className="text-glass">{created.display_name}</span>. Temporary password (shown once):{" "}
          <span className="font-mono text-warn">{created.temporary_password}</span>
          {created.warnings?.length ? <div className="mt-2 text-warn">{created.warnings.join(" ")}</div> : null}
        </div>
      )}

      {canWrite && (
        <section className="panel-pad mt-6">
          <h3 className="text-sm font-medium">Create user in Entra</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-6">
            <select className="input" value={templateId} onChange={(e) => applyTemplate(e.target.value)}>
              <option value="">No template</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
            <input className="input" placeholder="Display name" value={name} onChange={(e) => setName(e.target.value)} />
            <input
              className="input"
              placeholder="user@yourtenant.onmicrosoft.com"
              value={upn}
              onChange={(e) => setUpn(e.target.value)}
            />
            <input className="input" placeholder="Job title" value={title} onChange={(e) => setTitle(e.target.value)} />
            <input
              className="input"
              placeholder="Department"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
            />
            <input
              className="input"
              placeholder="Location, e.g. GB"
              maxLength={2}
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
            <button className="btn-primary" disabled={!tenantId || !name.trim() || !upn.trim() || saving} onClick={createUser}>
              Create in Entra
            </button>
          </div>
        </section>
      )}

      <div className="mt-6 grid gap-2 md:grid-cols-4">
        <input
          className="input md:col-span-2"
          placeholder="Search name, email or UPN"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
        />
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option>
          <option value="active">Active</option>
          <option value="disabled">Disabled</option>
        </select>
        <button className="btn-ghost" onClick={load}>
          Filter
        </button>
      </div>

      <div className="table-wrap mt-4">
        <table className="admin-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Status</th>
              <th>Title</th>
              <th>Licenses</th>
              <th>Last synced</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link href={`/entra/users/${row.id}`} className="font-medium text-mist-100 hover:text-glass">
                    {row.display_name}
                  </Link>
                  <div className="text-xs text-mist-500">{row.user_principal_name || row.email}</div>
                </td>
                <td>
                  <StatusBadge status={row.status} />
                </td>
                <td className="text-mist-400">
                  {row.job_title || "—"}
                  {row.department ? <div className="text-xs text-mist-500">{row.department}</div> : null}
                </td>
                <td className="text-mist-400">{row.assigned_licenses?.length ? row.assigned_licenses.length : "—"}</td>
                <td className="whitespace-nowrap text-mist-400">{when(row.last_synced_at)}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={5} className="py-8 text-center text-mist-500">
                  No Entra users yet. Connect Graph in Admin and run a sync.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
