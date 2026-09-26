"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useMe } from "@/components/MeProvider";
import { api } from "@/lib/api";
import { when } from "@/lib/format";
import { hasPrivilege } from "@/lib/iam";
import type { DirectorySync, EntraStatus, EntraTenant } from "@/lib/types";

const PERMISSIONS = ["User.ReadWrite.All", "Group.ReadWrite.All", "Directory.Read.All"];

export default function EntraConfigPage() {
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "admin.entra.write");
  const [status, setStatus] = useState<EntraStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [domain, setDomain] = useState("");
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editId, setEditId] = useState<string | null>(null);
  const [editSecret, setEditSecret] = useState("");

  const tenants = status?.tenants || [];

  function load() {
    api<EntraStatus>("/admin/entra/status")
      .then(setStatus)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(load, []);

  async function createTenant() {
    setSaving(true);
    setError(null);
    try {
      await api<EntraTenant>("/admin/entra/tenants", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          tenant_id: tenantId.trim(),
          client_id: clientId.trim(),
          client_secret: clientSecret.trim(),
          domain: domain.trim(),
        }),
      });
      setName("");
      setTenantId("");
      setClientId("");
      setClientSecret("");
      setDomain("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add tenant");
    } finally {
      setSaving(false);
    }
  }

  async function saveTenant(row: EntraTenant) {
    setBusyId(row.id);
    setError(null);
    try {
      await api<EntraTenant>(`/admin/entra/tenants/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: row.name,
          tenant_id: row.tenant_id,
          client_id: row.client_id,
          domain: row.domain,
          client_secret: editSecret.trim() || undefined,
        }),
      });
      setEditId(null);
      setEditSecret("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save tenant");
    } finally {
      setBusyId(null);
    }
  }

  async function testTenant(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await api<EntraTenant>(`/admin/entra/tenants/${id}/test`, { method: "POST" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test failed");
      load();
    } finally {
      setBusyId(null);
    }
  }

  async function syncTenant(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await api<DirectorySync>(`/admin/entra/tenants/${id}/sync`, { method: "POST" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed");
      load();
    } finally {
      setBusyId(null);
    }
  }

  async function removeTenant(row: EntraTenant) {
    if (!window.confirm(`Remove tenant “${row.name}”? Synced groups and apps for this tenant will be deleted.`)) return;
    setBusyId(row.id);
    setError(null);
    try {
      await api(`/admin/entra/tenants/${row.id}`, { method: "DELETE" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete tenant");
    } finally {
      setBusyId(null);
    }
  }

  function updateLocal(id: string, patch: Partial<EntraTenant>) {
    setStatus((current) =>
      current
        ? {
            ...current,
            tenants: (current.tenants || []).map((row) => (row.id === id ? { ...row, ...patch } : row)),
          }
        : current
    );
  }

  return (
    <div>
      <h2 className="font-display text-2xl">Entra config</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        Connect one or more Microsoft Entra tenants. Each tenant needs its own app registration with application
        permissions. Directory management is under{" "}
        <Link href="/entra" className="text-glass hover:underline">
          Infrastructure → Entra
        </Link>
        .
      </p>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      <section className="panel-pad mt-6">
        <h3 className="text-sm font-medium">Required Graph permissions</h3>
        <p className="mt-2 text-sm text-mist-400">
          Grant these as <span className="text-mist-100">application</span> permissions with admin consent on each
          tenant&apos;s app registration. Password reset also needs that app&apos;s service principal to hold the
          Password Administrator or User Administrator directory role.
        </p>
        <ul className="mt-3 list-disc space-y-1 pl-5 font-mono text-xs text-glass">
          {(status?.required_permissions || PERMISSIONS).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      {canWrite && (
        <section className="panel-pad mt-6">
          <h3 className="text-sm font-medium">Add tenant</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            <div>
              <label className="label">Display name</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Contoso" />
            </div>
            <div>
              <label className="label">Directory (tenant) ID</label>
              <input
                className="input"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              />
            </div>
            <div>
              <label className="label">Primary domain</label>
              <input
                className="input"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="contoso.onmicrosoft.com"
              />
            </div>
            <div>
              <label className="label">Application (client) ID</label>
              <input className="input" value={clientId} onChange={(e) => setClientId(e.target.value)} />
            </div>
            <div>
              <label className="label">Client secret</label>
              <input
                className="input"
                type="password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                autoComplete="new-password"
              />
            </div>
            <div className="flex items-end">
              <button
                className="btn-primary w-full"
                disabled={!name.trim() || !tenantId.trim() || !clientId.trim() || !clientSecret.trim() || saving}
                onClick={createTenant}
              >
                {saving ? "Adding…" : "Add tenant"}
              </button>
            </div>
          </div>
        </section>
      )}

      <div className="mt-6 grid gap-4">
        {tenants.map((row) => {
          const editing = editId === row.id;
          const last = row.last_sync;
          return (
            <article key={row.id} className="panel-pad">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-display text-xl">{row.name}</h3>
                  <p className="mt-1 font-mono text-xs text-mist-500">{row.tenant_id}</p>
                  {row.domain && <p className="text-sm text-mist-400">{row.domain}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`chip ${row.status === "ready" ? "text-glass" : row.status === "error" ? "text-rose" : ""}`}>
                    {row.status}
                  </span>
                  {row.credentials_configured ? (
                    <span className="chip">Credentials set</span>
                  ) : (
                    <span className="chip text-warn">Missing secret</span>
                  )}
                </div>
              </div>
              <p className="mt-3 text-sm text-mist-400">
                Last sync: {last ? `${last.status} · ${when(last.finished_at || last.started_at)}` : "Never"}
                {last ? ` · ${last.users_upserted} users, ${last.groups_upserted} groups, ${last.apps_upserted ?? 0} apps` : ""}
              </p>
              {(row.last_error || last?.error) && (
                <p className="mt-2 text-sm text-rose">{row.last_error || last?.error}</p>
              )}

              {editing && canWrite && (
                <div className="mt-4 grid gap-2 md:grid-cols-2">
                  <div>
                    <label className="label">Display name</label>
                    <input className="input" value={row.name} onChange={(e) => updateLocal(row.id, { name: e.target.value })} />
                  </div>
                  <div>
                    <label className="label">Directory (tenant) ID</label>
                    <input
                      className="input"
                      value={row.tenant_id}
                      onChange={(e) => updateLocal(row.id, { tenant_id: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="label">Application (client) ID</label>
                    <input
                      className="input"
                      value={row.client_id}
                      onChange={(e) => updateLocal(row.id, { client_id: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="label">Primary domain</label>
                    <input
                      className="input"
                      value={row.domain}
                      onChange={(e) => updateLocal(row.id, { domain: e.target.value })}
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="label">Rotate client secret</label>
                    <input
                      className="input"
                      type="password"
                      value={editSecret}
                      onChange={(e) => setEditSecret(e.target.value)}
                      placeholder="Leave blank to keep the current secret"
                    />
                  </div>
                </div>
              )}

              {canWrite && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {editing ? (
                    <>
                      <button className="btn-primary" disabled={busyId === row.id} onClick={() => saveTenant(row)}>
                        Save
                      </button>
                      <button
                        className="btn-ghost"
                        onClick={() => {
                          setEditId(null);
                          setEditSecret("");
                          load();
                        }}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button className="btn-ghost" onClick={() => setEditId(row.id)}>
                      Edit
                    </button>
                  )}
                  <button className="btn-ghost" disabled={busyId === row.id || !row.credentials_configured} onClick={() => testTenant(row.id)}>
                    {busyId === row.id ? "Working…" : "Test Graph"}
                  </button>
                  <button className="btn-primary" disabled={busyId === row.id || !row.credentials_configured} onClick={() => syncTenant(row.id)}>
                    Sync now
                  </button>
                  <button className="btn-danger" disabled={busyId === row.id} onClick={() => removeTenant(row)}>
                    Remove
                  </button>
                </div>
              )}
            </article>
          );
        })}
        {!tenants.length && (
          <p className="text-sm text-mist-500">No Entra tenants configured yet. Add one above to start directory sync.</p>
        )}
      </div>
    </div>
  );
}
