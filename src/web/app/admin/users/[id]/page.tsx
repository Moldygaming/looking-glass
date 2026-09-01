"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { RoleChecklist } from "@/components/admin/RoleChecklist";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { useMe } from "@/components/MeProvider";
import { api } from "@/lib/api";
import { when } from "@/lib/format";
import { hasPrivilege, sourceLabel } from "@/lib/iam";
import type { AccessRole, Group, UserDetail } from "@/lib/types";

type Tab = "groups" | "roles" | "effective";

export default function UserDetailPage() {
  const params = useParams<{ id: string }>();
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "admin.users.write");
  const [user, setUser] = useState<UserDetail | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [allRoles, setAllRoles] = useState<AccessRole[]>([]);
  const [tab, setTab] = useState<Tab>("groups");
  const [addGroup, setAddGroup] = useState("");
  const [notes, setNotes] = useState("");
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    api<UserDetail>(`/admin/users/${params.id}`)
      .then((row) => {
        setUser(row);
        setNotes(row.notes || "");
        setRoleIds((row.direct_roles || []).map((role) => role.id));
      })
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    api<Group[]>("/admin/groups").then(setGroups).catch(() => undefined);
    api<AccessRole[]>("/admin/roles").then(setAllRoles).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  async function patch(body: Record<string, unknown>) {
    setSaving(true);
    setError(null);
    try {
      const row = await api<UserDetail>(`/admin/users/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setUser(row);
      setNotes(row.notes || "");
      setRoleIds((row.direct_roles || []).map((role) => role.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function saveNotes() {
    await patch({ notes });
  }

  async function toggleStatus() {
    if (!user) return;
    const next = user.status === "active" ? "disabled" : "active";
    const label = next === "disabled" ? "Disable this account? They will not be able to use the API." : "Re-enable this account?";
    if (!window.confirm(label)) return;
    await patch({ status: next });
  }

  async function saveRoles() {
    setSaving(true);
    setError(null);
    try {
      const row = await api<UserDetail>(`/admin/users/${params.id}/roles`, {
        method: "PUT",
        body: JSON.stringify({ role_ids: roleIds }),
      });
      setUser(row);
      setRoleIds((row.direct_roles || []).map((role) => role.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update roles");
    } finally {
      setSaving(false);
    }
  }

  async function joinGroup() {
    if (!addGroup) return;
    setSaving(true);
    setError(null);
    try {
      const row = await api<UserDetail>(`/admin/users/${params.id}/groups/${addGroup}`, { method: "POST" });
      setUser(row);
      setRoleIds((row.direct_roles || []).map((role) => role.id));
      setAddGroup("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add to group");
    } finally {
      setSaving(false);
    }
  }

  async function leaveGroup(groupId: string) {
    if (!window.confirm("Remove this user from the group?")) return;
    setSaving(true);
    setError(null);
    try {
      const row = await api<UserDetail>(`/admin/users/${params.id}/groups/${groupId}`, { method: "DELETE" });
      setUser(row);
      setRoleIds((row.direct_roles || []).map((role) => role.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove from group");
    } finally {
      setSaving(false);
    }
  }

  if (!user) {
    return <p className="text-mist-400">{error || "Loading user…"}</p>;
  }

  const availableGroups = groups.filter((group) => !user.groups.some((item) => item.id === group.id));

  return (
    <div>
      <Link href="/admin/users" className="text-xs text-mist-500 hover:text-glass">
        ← Users
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl">{user.display_name}</h2>
          <p className="mt-1 text-sm text-mist-400">{user.email}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={user.status} />
          {canWrite && (
            <button className={user.status === "active" ? "btn-danger" : "btn-primary"} onClick={toggleStatus} disabled={saving}>
              {user.status === "active" ? "Disable" : "Enable"}
            </button>
          )}
        </div>
      </div>

      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      <dl className="panel-pad mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="label">Identity</dt>
          <dd className="font-mono text-xs text-mist-300">{user.entra_oid}</dd>
        </div>
        <div>
          <dt className="label">Last seen</dt>
          <dd className="text-sm">{when(user.last_login_at)}</dd>
        </div>
        <div>
          <dt className="label">Created</dt>
          <dd className="text-sm">{when(user.created_at)}</dd>
        </div>
        <div>
          <dt className="label">Effective access</dt>
          <dd className="text-sm">
            {user.is_admin ? "Platform admin" : `${user.effective_privileges.length} privileges`}
          </dd>
        </div>
      </dl>

      <section className="panel-pad mt-4">
        <label className="label">Notes</label>
        <textarea
          className="textarea min-h-[88px] font-sans text-sm"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          disabled={!canWrite}
          placeholder="Internal notes, not shown to the user"
        />
        {canWrite && (
          <button className="btn-ghost mt-3" onClick={saveNotes} disabled={saving}>
            Save notes
          </button>
        )}
      </section>

      <div className="mt-6 flex flex-wrap gap-2">
        {(["groups", "roles", "effective"] as Tab[]).map((item) => (
          <button key={item} className={tab === item ? "tab tab-active" : "tab"} onClick={() => setTab(item)}>
            {item === "groups" ? "Groups" : item === "roles" ? "Direct roles" : "Effective access"}
          </button>
        ))}
      </div>

      {tab === "groups" && (
        <section className="panel-pad mt-4">
          <p className="text-sm text-mist-400">
            Roles and data scopes are inherited from these groups. Direct roles (next tab) stack on top.
          </p>
          <ul className="mt-4 space-y-2">
            {user.groups.map((group) => (
              <li key={group.id} className="flex items-center justify-between gap-3 border-b border-white/5 py-2">
                <Link href={`/admin/groups/${group.id}`} className="hover:text-glass">
                  {group.name}
                </Link>
                {canWrite && (
                  <button className="text-xs text-rose" onClick={() => leaveGroup(group.id)}>
                    Remove
                  </button>
                )}
              </li>
            ))}
            {!user.groups.length && <li className="text-sm text-mist-500">Not in any group.</li>}
          </ul>
          {canWrite && (
            <div className="mt-4 flex flex-wrap gap-2">
              <select className="input max-w-sm" value={addGroup} onChange={(e) => setAddGroup(e.target.value)}>
                <option value="">Add to group…</option>
                {availableGroups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
              <button className="btn-primary" disabled={!addGroup || saving} onClick={joinGroup}>
                Add
              </button>
            </div>
          )}
        </section>
      )}

      {tab === "roles" && (
        <section className="mt-4">
          <p className="mb-4 text-sm text-mist-400">
            Prefer assigning roles on a group. Direct roles are for exceptions.
          </p>
          <RoleChecklist roles={allRoles} selected={roleIds} onChange={setRoleIds} disabled={!canWrite} />
          {canWrite && (
            <button className="btn-primary mt-4" onClick={saveRoles} disabled={saving}>
              Save direct roles
            </button>
          )}
        </section>
      )}

      {tab === "effective" && (
        <section className="panel-pad mt-4">
          <h3 className="text-sm font-medium">Permissions</h3>
          <div className="table-wrap mt-3">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Permission</th>
                  <th>Module</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {user.privilege_sources.map((row) => (
                  <tr key={row.key}>
                    <td>
                      <div>{row.name}</div>
                      <div className="font-mono text-[11px] text-mist-500">{row.key}</div>
                    </td>
                    <td className="text-mist-400">{row.module}</td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {row.sources.map((source, index) => (
                          <span key={`${source.kind}-${source.group_id || index}`} className="chip">
                            {sourceLabel(source.kind, source.via)}
                            {source.role_name ? ` · ${source.role_name}` : ""}
                            {source.group_name ? ` · ${source.group_name}` : ""}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
                {!user.privilege_sources.length && (
                  <tr>
                    <td colSpan={3} className="py-6 text-center text-mist-500">
                      No permissions. Add this user to a group or assign a role.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <h3 className="mt-6 text-sm font-medium">Data scopes</h3>
          <p className="mt-1 text-xs text-mist-500">
            Inherited from groups. Platform admins ignore scopes and see every account.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {user.scopes.length ? (
              user.scopes.map((scope) => (
                <span key={scope.id} className="chip">
                  {scope.provider ? `${scope.provider} · ` : ""}
                  {scope.tag_key}={scope.tag_value}
                </span>
              ))
            ) : (
              <span className="text-sm text-mist-500">{user.is_admin ? "Unscoped (admin bypass)" : "None"}</span>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
