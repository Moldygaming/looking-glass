"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PrivilegeEditor } from "@/components/admin/PrivilegeEditor";
import { useMe } from "@/components/MeProvider";
import { api } from "@/lib/api";
import { hasPrivilege } from "@/lib/iam";
import type { AccessRole, PrivilegeCatalog } from "@/lib/types";

export default function RolesPage() {
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "admin.roles.write");
  const [rows, setRows] = useState<AccessRole[]>([]);
  const [catalog, setCatalog] = useState<PrivilegeCatalog | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [privileges, setPrivileges] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    api<AccessRole[]>("/admin/roles")
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    api<PrivilegeCatalog>("/admin/privileges").then(setCatalog).catch(() => undefined);
  }, []);

  async function create() {
    setSaving(true);
    setError(null);
    try {
      const role = await api<AccessRole>("/admin/roles", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), description, privileges }),
      });
      window.location.href = `/admin/roles/${role.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create role");
      setSaving(false);
    }
  }

  return (
    <div>
      <h2 className="font-display text-2xl">Roles</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        A role is a named set of permissions. Tick what the role can do, then assign it to groups or users.
      </p>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      {canWrite && catalog && (
        <section className="panel-pad mt-6">
          <h3 className="text-sm font-medium">Create role</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            <input className="input" placeholder="Role name" value={name} onChange={(e) => setName(e.target.value)} />
            <input
              className="input"
              placeholder="Description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="mt-4">
            <PrivilegeEditor catalog={catalog.catalog} selected={privileges} onChange={setPrivileges} />
          </div>
          <button className="btn-primary mt-4" onClick={create} disabled={!name.trim() || saving}>
            Create role
          </button>
        </section>
      )}

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {rows.map((role) => (
          <Link key={role.id} href={`/admin/roles/${role.id}`} className="panel-pad hover:border-glass/40">
            <div className="flex items-start justify-between gap-3">
              <h3 className="font-display text-xl">{role.name}</h3>
              {role.is_system && <span className="chip text-glass">System</span>}
            </div>
            <p className="mt-2 text-sm text-mist-400">{role.description || "No description"}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {role.privileges.includes("platform.admin") ? (
                <span className="chip text-glass">platform.admin</span>
              ) : (
                role.privileges.slice(0, 6).map((key) => (
                  <span key={key} className="chip">
                    {key}
                  </span>
                ))
              )}
              {role.privileges.length > 6 && !role.privileges.includes("platform.admin") && (
                <span className="chip">+{role.privileges.length - 6}</span>
              )}
            </div>
            <p className="mt-3 text-xs text-mist-500">
              {role.privileges.length} permission{role.privileges.length === 1 ? "" : "s"} · {role.groups.length} group
              {role.groups.length === 1 ? "" : "s"} · {role.users.length} direct user
              {role.users.length === 1 ? "" : "s"}
            </p>
          </Link>
        ))}
        {!rows.length && <p className="text-sm text-mist-500">No roles yet.</p>}
      </div>
    </div>
  );
}
