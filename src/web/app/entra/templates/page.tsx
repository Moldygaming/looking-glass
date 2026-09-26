"use client";

import { useEffect, useState } from "react";
import { useEntraTenant } from "@/components/EntraTenantProvider";
import { useMe } from "@/components/MeProvider";
import { api, qs } from "@/lib/api";
import { hasPrivilege } from "@/lib/iam";
import type { EntraGroup, EntraLicense, EntraTemplate } from "@/lib/types";

const empty = {
  name: "",
  description: "",
  department: "",
  job_title: "",
  usage_location: "",
  group_ids: [] as string[],
  license_sku_ids: [] as string[],
};

export default function EntraTemplatesPage() {
  const { me } = useMe();
  const { tenantId } = useEntraTenant();
  const canWrite = hasPrivilege(me, "admin.entra.write");
  const [rows, setRows] = useState<EntraTemplate[]>([]);
  const [groups, setGroups] = useState<EntraGroup[]>([]);
  const [licenses, setLicenses] = useState<EntraLicense[]>([]);
  const [form, setForm] = useState(empty);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    if (!tenantId) {
      setRows([]);
      return;
    }
    api<EntraTemplate[]>(`/admin/entra/templates${qs({ tenant_id: tenantId })}`)
      .then(setRows)
      .catch((err: Error) => setError(err.message));
    api<EntraGroup[]>(`/admin/entra/groups${qs({ tenant_id: tenantId })}`)
      .then(setGroups)
      .catch(() => setGroups([]));
    api<EntraLicense[]>(`/admin/entra/licenses${qs({ tenant_id: tenantId })}`)
      .then(setLicenses)
      .catch(() => setLicenses([]));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  function toggle(list: string[], value: string) {
    return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
  }

  async function create() {
    if (!tenantId) return;
    setSaving(true);
    setError(null);
    try {
      await api("/admin/entra/templates", {
        method: "POST",
        body: JSON.stringify({ ...form, tenant_id: tenantId, usage_location: form.usage_location.toUpperCase() }),
      });
      setForm(empty);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save template");
    } finally {
      setSaving(false);
    }
  }

  async function remove(row: EntraTemplate) {
    if (!window.confirm(`Delete template “${row.name}”?`)) return;
    setError(null);
    try {
      await api(`/admin/entra/templates/${row.id}`, { method: "DELETE" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete template");
    }
  }

  return (
    <div>
      <h2 className="font-display text-2xl">User templates</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        A template fills department, title, and usage location, then adds groups and licenses when a user is created.
      </p>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      {canWrite && (
        <section className="panel-pad mt-6">
          <h3 className="text-sm font-medium">New template</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            <input className="input" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input
              className="input"
              placeholder="Job title"
              value={form.job_title}
              onChange={(e) => setForm({ ...form, job_title: e.target.value })}
            />
            <input
              className="input"
              placeholder="Department"
              value={form.department}
              onChange={(e) => setForm({ ...form, department: e.target.value })}
            />
            <input
              className="input"
              placeholder="Usage location, e.g. GB"
              maxLength={2}
              value={form.usage_location}
              onChange={(e) => setForm({ ...form, usage_location: e.target.value })}
            />
            <input
              className="input md:col-span-2"
              placeholder="Description"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <fieldset>
              <legend className="label">Groups</legend>
              <div className="mt-2 max-h-48 space-y-1 overflow-auto rounded-md border border-white/10 p-2 text-sm">
                {groups.map((group) => (
                  <label key={group.id} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={form.group_ids.includes(group.entra_id)}
                      onChange={() => setForm({ ...form, group_ids: toggle(form.group_ids, group.entra_id) })}
                    />
                    {group.display_name}
                  </label>
                ))}
                {!groups.length && <p className="text-mist-500">No groups synced.</p>}
              </div>
            </fieldset>
            <fieldset>
              <legend className="label">Licenses</legend>
              <div className="mt-2 max-h-48 space-y-1 overflow-auto rounded-md border border-white/10 p-2 text-sm">
                {licenses.map((license) => (
                  <label key={license.id} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={form.license_sku_ids.includes(license.sku_id)}
                      onChange={() => setForm({ ...form, license_sku_ids: toggle(form.license_sku_ids, license.sku_id) })}
                    />
                    <span>
                      {license.display_name}
                      <span className="ml-2 text-xs text-mist-500">{license.available_units} available</span>
                    </span>
                  </label>
                ))}
                {!licenses.length && <p className="text-mist-500">Refresh licenses before attaching them to a template.</p>}
              </div>
            </fieldset>
          </div>
          <button className="btn-primary mt-4" disabled={!tenantId || !form.name.trim() || saving} onClick={create}>
            Save template
          </button>
        </section>
      )}

      <div className="table-wrap mt-6">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Template</th>
              <th>Defaults</th>
              <th>Access</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <div className="font-medium text-mist-100">{row.name}</div>
                  {row.description && <div className="text-xs text-mist-500">{row.description}</div>}
                </td>
                <td className="text-mist-400">
                  {[row.job_title, row.department, row.usage_location].filter(Boolean).join(" · ") || "—"}
                </td>
                <td className="text-mist-400">
                  {row.group_ids.length} groups · {row.license_sku_ids.length} licenses
                </td>
                <td>
                  {canWrite && (
                    <button className="text-xs text-rose" onClick={() => remove(row)}>
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={4} className="py-8 text-center text-mist-500">
                  No templates yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
