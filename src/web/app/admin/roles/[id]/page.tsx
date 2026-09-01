"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { PrivilegeEditor } from "@/components/admin/PrivilegeEditor";
import { useMe } from "@/components/MeProvider";
import { api } from "@/lib/api";
import { hasPrivilege } from "@/lib/iam";
import type { AccessRole, PrivilegeCatalog } from "@/lib/types";

export default function RoleDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "admin.roles.write");
  const [role, setRole] = useState<AccessRole | null>(null);
  const [catalog, setCatalog] = useState<PrivilegeCatalog | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [privileges, setPrivileges] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    api<AccessRole>(`/admin/roles/${params.id}`)
      .then((row) => {
        setRole(row);
        setName(row.name);
        setDescription(row.description);
        setPrivileges(row.privileges || []);
      })
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    api<PrivilegeCatalog>("/admin/privileges").then(setCatalog).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const row = await api<AccessRole>(`/admin/roles/${params.id}`, {
        method: "PUT",
        body: JSON.stringify({ name: name.trim(), description, privileges }),
      });
      setRole(row);
      setName(row.name);
      setDescription(row.description);
      setPrivileges(row.privileges || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save role");
    } finally {
      setSaving(false);
    }
  }

  async function destroy() {
    if (!window.confirm(`Delete role “${role?.name}”? Groups and users lose these permissions.`)) return;
    try {
      await api(`/admin/roles/${params.id}`, { method: "DELETE" });
      router.push("/admin/roles");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete role");
    }
  }

  if (!role) {
    return <p className="text-mist-400">{error || "Loading role…"}</p>;
  }

  return (
    <div>
      <Link href="/admin/roles" className="text-xs text-mist-500 hover:text-glass">
        ← Roles
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <h2 className="font-display text-2xl">{role.name}</h2>
          {role.is_system && <span className="chip text-glass">System</span>}
        </div>
        {canWrite && !role.is_system && (
          <button className="btn-danger" onClick={destroy}>
            Delete role
          </button>
        )}
      </div>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      <section className="panel-pad mt-6 grid gap-3 md:grid-cols-2">
        <div>
          <label className="label">Name</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} disabled={!canWrite} />
        </div>
        <div>
          <label className="label">Description</label>
          <input
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={!canWrite}
          />
        </div>
      </section>

      <section className="mt-6">
        <h3 className="mb-3 text-sm font-medium">Permissions</h3>
        {catalog && (
          <PrivilegeEditor
            catalog={catalog.catalog}
            selected={privileges}
            onChange={setPrivileges}
            disabled={!canWrite}
            lockedKeys={role.is_system ? ["platform.admin"] : []}
          />
        )}
        {canWrite && (
          <button className="btn-primary mt-4" onClick={save} disabled={!name.trim() || saving}>
            Save role
          </button>
        )}
      </section>

      <section className="panel-pad mt-6">
        <h3 className="text-sm font-medium">Assigned to</h3>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <div>
            <p className="label">Groups</p>
            {role.groups.length ? (
              <ul className="space-y-1 text-sm">
                {role.groups.map((group) => (
                  <li key={group.id}>
                    <Link href={`/admin/groups/${group.id}`} className="hover:text-glass">
                      {group.name}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-mist-500">No groups.</p>
            )}
          </div>
          <div>
            <p className="label">Users (direct)</p>
            {role.users.length ? (
              <ul className="space-y-1 text-sm">
                {role.users.map((user) => (
                  <li key={user.id}>
                    <Link href={`/admin/users/${user.id}`} className="hover:text-glass">
                      {user.display_name}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-mist-500">No direct users.</p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
