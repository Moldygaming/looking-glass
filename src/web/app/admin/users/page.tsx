"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { useMe } from "@/components/MeProvider";
import { api } from "@/lib/api";
import { when } from "@/lib/format";
import { hasPrivilege } from "@/lib/iam";
import type { Group, UserRow } from "@/lib/types";

export default function UsersPage() {
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "admin.users.write");
  const [rows, setRows] = useState<UserRow[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [groupId, setGroupId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [newGroup, setNewGroup] = useState("");
  const [saving, setSaving] = useState(false);

  function load() {
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (status) params.set("status", status);
    if (groupId) params.set("group_id", groupId);
    const qs = params.toString();
    api<UserRow[]>(`/admin/users${qs ? `?${qs}` : ""}`)
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    api<Group[]>("/admin/groups").then(setGroups).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createUser() {
    setSaving(true);
    setError(null);
    try {
      const user = await api<UserRow>("/admin/users", {
        method: "POST",
        body: JSON.stringify({
          display_name: name.trim(),
          email: email.trim(),
          group_ids: newGroup ? [newGroup] : [],
        }),
      });
      window.location.href = `/admin/users/${user.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create user");
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl">Users</h2>
          <p className="mt-1 max-w-2xl text-sm text-mist-400">
            People appear here after they sign in, or you can pre-provision an email so group membership is waiting for
            them.
          </p>
        </div>
      </div>

      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      {canWrite && (
        <section className="panel-pad mt-6">
          <h3 className="text-sm font-medium">Pre-provision a user</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            <input className="input" placeholder="Display name" value={name} onChange={(e) => setName(e.target.value)} />
            <input className="input" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
            <select className="input" value={newGroup} onChange={(e) => setNewGroup(e.target.value)}>
              <option value="">No group yet</option>
              {groups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
            <button className="btn-primary" disabled={!name.trim() || !email.trim() || saving} onClick={createUser}>
              Create user
            </button>
          </div>
        </section>
      )}

      <div className="mt-6 grid gap-2 md:grid-cols-4">
        <input
          className="input md:col-span-2"
          placeholder="Search name or email"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
        />
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option>
          <option value="active">Active</option>
          <option value="disabled">Disabled</option>
        </select>
        <div className="flex gap-2">
          <select className="input" value={groupId} onChange={(e) => setGroupId(e.target.value)}>
            <option value="">Any group</option>
            {groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
          <button className="btn-ghost shrink-0" onClick={load}>
            Filter
          </button>
        </div>
      </div>

      <div className="table-wrap mt-4">
        <table className="admin-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Status</th>
              <th>Groups</th>
              <th>Access</th>
              <th>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link href={`/admin/users/${row.id}`} className="font-medium text-mist-100 hover:text-glass">
                    {row.display_name}
                  </Link>
                  <div className="text-xs text-mist-500">{row.email}</div>
                </td>
                <td>
                  <StatusBadge status={row.status} />
                </td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {row.groups.length
                      ? row.groups.map((group) => (
                          <Link key={group.id} href={`/admin/groups/${group.id}`} className="chip">
                            {group.name}
                          </Link>
                        ))
                      : <span className="text-xs text-mist-500">None</span>}
                  </div>
                </td>
                <td className="text-mist-400">
                  {row.is_admin
                    ? "Platform admin"
                    : (row.access_roles || []).length
                      ? (row.access_roles || []).map((role) => role.name).join(", ")
                      : `${row.privilege_count} permission${row.privilege_count === 1 ? "" : "s"}`}
                </td>
                <td className="whitespace-nowrap text-mist-400">{when(row.last_login_at)}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={5} className="py-8 text-center text-mist-500">
                  No users match those filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
