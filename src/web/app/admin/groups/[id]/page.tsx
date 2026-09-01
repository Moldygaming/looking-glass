"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { RoleChecklist } from "@/components/admin/RoleChecklist";
import { useMe } from "@/components/MeProvider";
import { api } from "@/lib/api";
import { hasPrivilege } from "@/lib/iam";
import type { AccessRole, Group, UserRow } from "@/lib/types";

type Tab = "members" | "roles" | "scopes";

export default function GroupDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "admin.groups.write");
  const [group, setGroup] = useState<Group | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [allRoles, setAllRoles] = useState<AccessRole[]>([]);
  const [tab, setTab] = useState<Tab>("members");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const [userId, setUserId] = useState("");
  const [entraGroup, setEntraGroup] = useState("");
  const [tagKey, setTagKey] = useState("team");
  const [tagValue, setTagValue] = useState("");
  const [provider, setProvider] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    api<Group>(`/admin/groups/${params.id}`)
      .then((row) => {
        setGroup(row);
        setName(row.name);
        setDescription(row.description);
        setRoleIds((row.roles || []).map((role) => role.id));
      })
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    api<UserRow[]>("/admin/users").then(setUsers).catch(() => undefined);
    api<AccessRole[]>("/admin/roles").then(setAllRoles).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  async function saveMeta() {
    setSaving(true);
    setError(null);
    try {
      const row = await api<Group>(`/admin/groups/${params.id}`, {
        method: "PUT",
        body: JSON.stringify({ name: name.trim(), description }),
      });
      setGroup(row);
      setName(row.name);
      setDescription(row.description);
      setRoleIds((row.roles || []).map((role) => role.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save group");
    } finally {
      setSaving(false);
    }
  }

  async function saveRoles() {
    setSaving(true);
    setError(null);
    try {
      const row = await api<Group>(`/admin/groups/${params.id}/roles`, {
        method: "PUT",
        body: JSON.stringify({ role_ids: roleIds }),
      });
      setGroup(row);
      setRoleIds((row.roles || []).map((role) => role.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save roles");
    } finally {
      setSaving(false);
    }
  }

  async function addMember() {
    setSaving(true);
    setError(null);
    try {
      await api(`/admin/groups/${params.id}/members`, {
        method: "POST",
        body: JSON.stringify({
          user_id: userId || null,
          entra_group_id: entraGroup.trim() || null,
        }),
      });
      setUserId("");
      setEntraGroup("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add member");
    } finally {
      setSaving(false);
    }
  }

  async function removeMember(memberId: string) {
    if (!window.confirm("Remove this member?")) return;
    setError(null);
    try {
      await api(`/admin/groups/${params.id}/members/${memberId}`, { method: "DELETE" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove member");
    }
  }

  async function addScope() {
    setSaving(true);
    setError(null);
    try {
      await api(`/admin/groups/${params.id}/scopes`, {
        method: "POST",
        body: JSON.stringify({
          tag_key: tagKey.trim(),
          tag_value: tagValue.trim(),
          provider: provider || null,
        }),
      });
      setTagValue("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add scope");
    } finally {
      setSaving(false);
    }
  }

  async function removeScope(scopeId: string) {
    try {
      await api(`/admin/groups/${params.id}/scopes/${scopeId}`, { method: "DELETE" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove scope");
    }
  }

  async function destroy() {
    if (!window.confirm(`Delete group “${group?.name}”? Members lose these roles and scopes.`)) return;
    try {
      await api(`/admin/groups/${params.id}`, { method: "DELETE" });
      router.push("/admin/groups");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete group");
    }
  }

  if (!group) {
    return <p className="text-mist-400">{error || "Loading group…"}</p>;
  }

  const memberUserIds = new Set(group.members.map((member) => member.user_id).filter(Boolean));
  const availableUsers = users.filter((user) => user.status === "active" && !memberUserIds.has(user.id));
  const lockedRoleIds = group.is_system
    ? allRoles.filter((role) => role.privileges.includes("platform.admin")).map((role) => role.id)
    : [];

  return (
    <div>
      <Link href="/admin/groups" className="text-xs text-mist-500 hover:text-glass">
        ← Groups
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <h2 className="font-display text-2xl">{group.name}</h2>
          {group.is_system && <span className="chip text-glass">System</span>}
        </div>
        {canWrite && !group.is_system && (
          <button className="btn-danger" onClick={destroy}>
            Delete group
          </button>
        )}
      </div>

      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      <section className="panel-pad mt-6 grid gap-3 md:grid-cols-[1fr_1fr_auto]">
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
        {canWrite && (
          <div className="flex items-end">
            <button className="btn-ghost w-full" onClick={saveMeta} disabled={!name.trim() || saving}>
              Save details
            </button>
          </div>
        )}
      </section>

      <div className="mt-6 flex flex-wrap gap-2">
        {(
          [
            ["members", `Members (${group.members.length})`],
            ["roles", `Roles (${(group.roles || []).length})`],
            ["scopes", `Data scopes (${group.scopes.length})`],
          ] as [Tab, string][]
        ).map(([id, label]) => (
          <button key={id} className={tab === id ? "tab tab-active" : "tab"} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "members" && (
        <section className="panel-pad mt-4">
          <p className="text-sm text-mist-400">
            Add a Looking Glass user, or map an Entra ID security group so membership stays in Azure AD.
          </p>
          <ul className="mt-4 space-y-2 text-sm">
            {group.members.map((member) => (
              <li key={member.id} className="flex items-center justify-between gap-3 border-b border-white/5 py-2">
                <span>
                  {member.kind === "entra_group" ? (
                    <>
                      Entra group
                      <span className="ml-2 font-mono text-xs text-mist-500">{member.entra_group_id}</span>
                    </>
                  ) : (
                    <>
                      {member.user_id ? (
                        <Link href={`/admin/users/${member.user_id}`} className="hover:text-glass">
                          {member.display_name || member.email}
                        </Link>
                      ) : (
                        member.display_name || member.email
                      )}
                      {member.email && member.display_name && (
                        <span className="ml-2 text-xs text-mist-500">{member.email}</span>
                      )}
                    </>
                  )}
                </span>
                {canWrite && (
                  <button className="text-xs text-rose" onClick={() => removeMember(member.id)}>
                    Remove
                  </button>
                )}
              </li>
            ))}
            {!group.members.length && <li className="text-mist-500">No members yet.</li>}
          </ul>
          {canWrite && (
            <div className="mt-4 grid gap-2 md:grid-cols-3">
              <select className="input" value={userId} onChange={(e) => setUserId(e.target.value)}>
                <option value="">Select user…</option>
                {availableUsers.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.display_name} ({user.email})
                  </option>
                ))}
              </select>
              <input
                className="input"
                placeholder="Or Entra group object ID"
                value={entraGroup}
                onChange={(e) => setEntraGroup(e.target.value)}
              />
              <button className="btn-primary" onClick={addMember} disabled={(!userId && !entraGroup.trim()) || saving}>
                Add member
              </button>
            </div>
          )}
        </section>
      )}

      {tab === "roles" && (
        <section className="mt-4">
          <p className="mb-4 text-sm text-mist-400">
            Tick the roles this group should have. Create or edit roles under{" "}
            <Link href="/admin/roles" className="text-glass">
              Roles
            </Link>
            . Data scopes (next tab) still limit what members can see.
          </p>
          <RoleChecklist
            roles={allRoles}
            selected={roleIds}
            onChange={setRoleIds}
            disabled={!canWrite}
            lockedIds={lockedRoleIds.filter((id) => roleIds.includes(id))}
          />
          {canWrite && (
            <button className="btn-primary mt-4" onClick={saveRoles} disabled={saving}>
              Save roles
            </button>
          )}
        </section>
      )}

      {tab === "scopes" && (
        <section className="panel-pad mt-4">
          <p className="text-sm text-mist-400">
            Members only see FinOps rows whose tags match any of these scopes. Platform administrators ignore scopes.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {group.scopes.map((scope) => (
              <span key={scope.id} className="chip">
                {scope.provider ? `${scope.provider} · ` : ""}
                {scope.tag_key}={scope.tag_value}
                {canWrite && (
                  <button className="ml-2 text-rose" onClick={() => removeScope(scope.id!)}>
                    ×
                  </button>
                )}
              </span>
            ))}
            {!group.scopes.length && (
              <span className="text-sm text-mist-500">No data scopes. Non-admins will see nothing.</span>
            )}
          </div>
          {canWrite && (
            <div className="mt-4 grid gap-2 md:grid-cols-4">
              <input className="input" value={tagKey} onChange={(e) => setTagKey(e.target.value)} placeholder="tag key" />
              <input
                className="input"
                value={tagValue}
                onChange={(e) => setTagValue(e.target.value)}
                placeholder="tag value"
              />
              <select className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
                <option value="">All clouds</option>
                <option value="azure">Azure only</option>
                <option value="aws">AWS only</option>
                <option value="gcp">GCP only</option>
              </select>
              <button className="btn-primary" onClick={addScope} disabled={!tagKey.trim() || !tagValue.trim() || saving}>
                Add scope
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
