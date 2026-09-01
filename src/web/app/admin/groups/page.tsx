"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useMe } from "@/components/MeProvider";
import { api } from "@/lib/api";
import { hasPrivilege } from "@/lib/iam";
import type { Group } from "@/lib/types";

export default function GroupsPage() {
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "admin.groups.write");
  const [rows, setRows] = useState<Group[]>([]);
  const [q, setQ] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    const qs = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
    api<Group[]>(`/admin/groups${qs}`)
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create() {
    setSaving(true);
    setError(null);
    try {
      const group = await api<Group>("/admin/groups", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), description }),
      });
      window.location.href = `/admin/groups/${group.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create group");
      setSaving(false);
    }
  }

  return (
    <div>
      <h2 className="font-display text-2xl">Groups</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        A group is people + roles + data scopes. Assign roles you created under Roles; scopes limit which tagged
        resources they can see.
      </p>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      {canWrite && (
        <section className="panel-pad mt-6">
          <h3 className="text-sm font-medium">Create group</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-3">
            <input className="input" placeholder="Group name" value={name} onChange={(e) => setName(e.target.value)} />
            <input
              className="input"
              placeholder="Description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <button className="btn-primary" onClick={create} disabled={!name.trim() || saving}>
              Create group
            </button>
          </div>
        </section>
      )}

      <div className="mt-6 flex gap-2">
        <input
          className="input max-w-md"
          placeholder="Search groups"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
        />
        <button className="btn-ghost" onClick={load}>
          Search
        </button>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {rows.map((group) => (
          <Link key={group.id} href={`/admin/groups/${group.id}`} className="panel-pad hover:border-glass/40">
            <div className="flex items-start justify-between gap-3">
              <h3 className="font-display text-xl">{group.name}</h3>
              {group.is_system && <span className="chip text-glass">System</span>}
            </div>
            <p className="mt-2 text-sm text-mist-400">{group.description || "No description"}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {(group.roles || []).map((role) => (
                <span key={role.id} className="chip text-glass">
                  {role.name}
                </span>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {group.scopes.map((scope) => (
                <span key={scope.id} className="chip text-mist-300">
                  {scope.tag_key}={scope.tag_value}
                </span>
              ))}
            </div>
            <p className="mt-3 text-xs text-mist-500">
              {group.members.length} member{group.members.length === 1 ? "" : "s"} · {(group.roles || []).length} role
              {(group.roles || []).length === 1 ? "" : "s"} · {group.scopes.length} scope
              {group.scopes.length === 1 ? "" : "s"}
            </p>
          </Link>
        ))}
        {!rows.length && <p className="text-sm text-mist-500">No groups match.</p>}
      </div>
    </div>
  );
}
