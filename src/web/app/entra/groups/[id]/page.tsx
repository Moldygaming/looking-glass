"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppAssignments } from "@/components/admin/AppAssignments";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { useMe } from "@/components/MeProvider";
import { api } from "@/lib/api";
import { hasPrivilege } from "@/lib/iam";
import type { EntraGroup, EntraUser } from "@/lib/types";

export default function DirectoryGroupDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "admin.entra.write");
  const canOperate = hasPrivilege(me, "admin.entra.write", "admin.entra.helpdesk");
  const [group, setGroup] = useState<EntraGroup | null>(null);
  const [users, setUsers] = useState<EntraUser[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [addUser, setAddUser] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    api<EntraGroup>(`/admin/entra/groups/${params.id}`)
      .then((row) => {
        setGroup(row);
        setName(row.display_name);
        setDescription(row.description || "");
      })
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    api<EntraUser[]>("/admin/entra/users").then(setUsers).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const row = await api<EntraGroup>(`/admin/entra/groups/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify({ display_name: name.trim(), description }),
      });
      setGroup(row);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function addMember() {
    if (!addUser) return;
    setSaving(true);
    setError(null);
    try {
      const row = await api<EntraGroup>(`/admin/entra/groups/${params.id}/members`, {
        method: "POST",
        body: JSON.stringify({ user_id: addUser }),
      });
      setGroup(row);
      setAddUser("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add member");
    } finally {
      setSaving(false);
    }
  }

  async function removeMember(entraUserId: string) {
    if (!window.confirm("Remove this member from the Entra group?")) return;
    setSaving(true);
    setError(null);
    try {
      const row = await api<EntraGroup>(`/admin/entra/groups/${params.id}/members/${entraUserId}`, {
        method: "DELETE",
      });
      setGroup(row);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove member");
    } finally {
      setSaving(false);
    }
  }

  async function destroy() {
    if (!window.confirm(`Delete Entra group “${group?.display_name}”? This cannot be undone.`)) return;
    try {
      await api(`/admin/entra/groups/${params.id}`, { method: "DELETE" });
      router.push("/entra/groups");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete group");
    }
  }

  if (!group) {
    return <p className="text-mist-400">{error || "Loading group…"}</p>;
  }

  const memberIds = new Set(group.members.map((member) => member.user_id).filter(Boolean));
  const available = users.filter((user) => user.status === "active" && !memberIds.has(user.id));

  return (
    <div>
      <Link href="/entra/groups" className="text-xs text-mist-500 hover:text-glass">
        ← Entra groups
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl">{group.display_name}</h2>
          <p className="mt-1 font-mono text-xs text-mist-500">{group.entra_id}</p>
        </div>
        {canWrite && (
          <button className="btn-danger" onClick={destroy}>
            Delete in Entra
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
      {canWrite && (
        <button className="btn-ghost mt-3" onClick={save} disabled={!name.trim() || saving}>
          Save in Entra
        </button>
      )}

      <section className="panel-pad mt-6">
        <h3 className="text-sm font-medium">Members ({group.members.length})</h3>
        <ul className="mt-4 space-y-2 text-sm">
          {group.members.map((member) => (
            <li key={member.entra_user_id} className="flex items-center justify-between gap-3 border-b border-white/5 py-2">
              <span>
                {member.user_id ? (
                  <Link href={`/entra/users/${member.user_id}`} className="hover:text-glass">
                    {member.display_name || member.email || member.entra_user_id}
                  </Link>
                ) : (
                  member.display_name || member.entra_user_id
                )}
                {member.email && <span className="ml-2 text-xs text-mist-500">{member.email}</span>}
                {member.status && (
                  <span className="ml-2">
                    <StatusBadge status={member.status} />
                  </span>
                )}
              </span>
              {canOperate && (
                <button className="text-xs text-rose" onClick={() => removeMember(member.entra_user_id)}>
                  Remove
                </button>
              )}
            </li>
          ))}
          {!group.members.length && <li className="text-mist-500">No members yet.</li>}
        </ul>
        {canOperate && (
          <div className="mt-4 flex flex-wrap gap-2">
            <select className="input max-w-md" value={addUser} onChange={(e) => setAddUser(e.target.value)}>
              <option value="">Add member…</option>
              {available.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name} ({user.user_principal_name || user.email})
                </option>
              ))}
            </select>
            <button className="btn-primary" disabled={!addUser || saving} onClick={addMember}>
              Add in Entra
            </button>
          </div>
        )}
      </section>

      <AppAssignments items={group.app_assignments} />
    </div>
  );
}
