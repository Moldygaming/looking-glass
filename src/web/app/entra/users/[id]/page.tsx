"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AppAssignments } from "@/components/admin/AppAssignments";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { useEntraTenant } from "@/components/EntraTenantProvider";
import { useMe } from "@/components/MeProvider";
import { api, qs } from "@/lib/api";
import { when } from "@/lib/format";
import { hasPrivilege } from "@/lib/iam";
import type { EntraLicense, EntraUser } from "@/lib/types";

export default function DirectoryUserDetailPage() {
  const params = useParams<{ id: string }>();
  const { me } = useMe();
  const { tenantId } = useEntraTenant();
  const canWrite = hasPrivilege(me, "admin.entra.write");
  const canOperate = hasPrivilege(me, "admin.entra.write", "admin.entra.helpdesk");
  const [user, setUser] = useState<EntraUser | null>(null);
  const [licenses, setLicenses] = useState<EntraLicense[]>([]);
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [department, setDepartment] = useState("");
  const [location, setLocation] = useState("");
  const [password, setPassword] = useState("");
  const [temporary, setTemporary] = useState<string | null>(null);
  const [addSku, setAddSku] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    api<EntraUser>(`/admin/entra/users/${params.id}`)
      .then((row) => {
        setUser(row);
        setName(row.display_name);
        setTitle(row.job_title || "");
        setDepartment(row.department || "");
        setLocation(row.usage_location || "");
      })
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  useEffect(() => {
    if (!tenantId || !canWrite) {
      setLicenses([]);
      return;
    }
    api<EntraLicense[]>(`/admin/entra/licenses${qs({ tenant_id: tenantId })}`)
      .then(setLicenses)
      .catch(() => setLicenses([]));
  }, [tenantId, canWrite]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const row = await api<EntraUser>(`/admin/entra/users/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          display_name: name.trim(),
          job_title: title,
          department,
          usage_location: location.trim().toUpperCase(),
        }),
      });
      setUser(row);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus() {
    if (!user) return;
    const next = user.status === "active" ? "disabled" : "active";
    if (!window.confirm(next === "disabled" ? "Disable this account in Entra?" : "Enable this account in Entra?")) return;
    setSaving(true);
    setError(null);
    try {
      const row = await api<EntraUser>(`/admin/entra/users/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      setUser(row);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update account");
    } finally {
      setSaving(false);
    }
  }

  async function resetPassword() {
    if (!window.confirm("Reset this password in Entra? The user will be required to change it at next sign-in.")) return;
    setSaving(true);
    setError(null);
    setTemporary(null);
    try {
      const row = await api<EntraUser>(`/admin/entra/users/${params.id}/password`, {
        method: "POST",
        body: JSON.stringify({ password: password.trim() || null, force_change: true }),
      });
      setUser(row);
      setTemporary(row.temporary_password || null);
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset password");
    } finally {
      setSaving(false);
    }
  }

  async function changeLicense(add: string[], remove: string[]) {
    setSaving(true);
    setError(null);
    try {
      const row = await api<EntraUser>(`/admin/entra/users/${params.id}/licenses`, {
        method: "POST",
        body: JSON.stringify({
          add_sku_ids: add,
          remove_sku_ids: remove,
          usage_location: location.trim().toUpperCase() || null,
        }),
      });
      setUser(row);
      setLocation(row.usage_location || location);
      setAddSku("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change licenses");
    } finally {
      setSaving(false);
    }
  }

  if (!user) {
    return <p className="text-mist-400">{error || "Loading user…"}</p>;
  }

  const assigned = new Set((user.assigned_licenses || []).map((item) => item.sku_id));
  const available = licenses.filter((item) => !assigned.has(item.sku_id));

  return (
    <div>
      <Link href="/entra/users" className="text-xs text-mist-500 hover:text-glass">
        ← Entra users
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl">{user.display_name}</h2>
          <p className="mt-1 text-sm text-mist-400">{user.user_principal_name || user.email}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={user.status} />
          {canOperate && (
            <button className={user.status === "active" ? "btn-danger" : "btn-primary"} onClick={toggleStatus} disabled={saving}>
              {user.status === "active" ? "Disable in Entra" : "Enable in Entra"}
            </button>
          )}
        </div>
      </div>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      <dl className="panel-pad mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="label">Object ID</dt>
          <dd className="font-mono text-xs text-mist-300">{user.entra_oid}</dd>
        </div>
        <div>
          <dt className="label">Last synced</dt>
          <dd className="text-sm">{when(user.last_synced_at)}</dd>
        </div>
        <div>
          <dt className="label">Last Looking Glass sign-in</dt>
          <dd className="text-sm">{when(user.last_login_at)}</dd>
        </div>
        <div>
          <dt className="label">Source</dt>
          <dd className="text-sm capitalize">{user.source}</dd>
        </div>
      </dl>

      <section className="panel-pad mt-4 grid gap-3 md:grid-cols-4">
        <div>
          <label className="label">Display name</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} disabled={!canWrite} />
        </div>
        <div>
          <label className="label">Job title</label>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} disabled={!canWrite} />
        </div>
        <div>
          <label className="label">Department</label>
          <input className="input" value={department} onChange={(e) => setDepartment(e.target.value)} disabled={!canWrite} />
        </div>
        <div>
          <label className="label">Usage location</label>
          <input
            className="input"
            value={location}
            maxLength={2}
            placeholder="GB"
            onChange={(e) => setLocation(e.target.value)}
            disabled={!canWrite}
          />
        </div>
      </section>
      {canWrite && (
        <button className="btn-primary mt-4" onClick={save} disabled={!name.trim() || saving}>
          Save in Entra
        </button>
      )}

      {canOperate && (
        <section className="panel-pad mt-4">
          <h3 className="text-sm font-medium">Password</h3>
          <p className="mt-1 text-sm text-mist-400">
            Leave the field blank to generate a password. The user must change it at next sign-in. The app registration
            needs the Password Administrator or User Administrator directory role.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <input
              className="input max-w-sm"
              type="text"
              placeholder="Generate if blank"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="off"
            />
            <button className="btn-danger" onClick={resetPassword} disabled={saving}>
              Reset password
            </button>
          </div>
          {temporary && (
            <p className="mt-3 text-sm">
              Temporary password (shown once): <span className="font-mono text-warn">{temporary}</span>
            </p>
          )}
        </section>
      )}

      {canWrite && (
        <section className="panel-pad mt-4">
          <h3 className="text-sm font-medium">Licenses</h3>
          <ul className="mt-3 space-y-2 text-sm">
            {(user.assigned_licenses || []).map((item) => (
              <li key={item.sku_id} className="flex items-center justify-between gap-3 border-b border-white/5 py-2">
                <span>
                  {item.display_name || item.sku_part_number || item.sku_id}
                  {item.sku_part_number && <span className="ml-2 font-mono text-xs text-mist-500">{item.sku_part_number}</span>}
                </span>
                <button className="text-xs text-rose" disabled={saving} onClick={() => changeLicense([], [item.sku_id])}>
                  Remove
                </button>
              </li>
            ))}
            {!user.assigned_licenses?.length && <li className="text-mist-500">No licenses assigned.</li>}
          </ul>
          <div className="mt-4 flex flex-wrap gap-2">
            <select className="input max-w-md" value={addSku} onChange={(e) => setAddSku(e.target.value)}>
              <option value="">Assign license…</option>
              {available.map((item) => (
                <option key={item.sku_id} value={item.sku_id}>
                  {item.display_name} ({item.available_units} available)
                </option>
              ))}
            </select>
            <button className="btn-primary" disabled={!addSku || saving} onClick={() => changeLicense([addSku], [])}>
              Assign
            </button>
          </div>
          {!licenses.length && (
            <p className="mt-3 text-xs text-mist-500">Refresh licenses on the Licenses tab if this list is empty.</p>
          )}
        </section>
      )}

      <AppAssignments items={user.app_assignments} />
    </div>
  );
}
