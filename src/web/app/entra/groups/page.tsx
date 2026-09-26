"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useEntraTenant } from "@/components/EntraTenantProvider";
import { useMe } from "@/components/MeProvider";
import { api, qs } from "@/lib/api";
import { hasPrivilege } from "@/lib/iam";
import type { EntraGroup } from "@/lib/types";

export default function DirectoryGroupsPage() {
  const { me } = useMe();
  const { tenantId } = useEntraTenant();
  const canWrite = hasPrivilege(me, "admin.entra.write");
  const [rows, setRows] = useState<EntraGroup[]>([]);
  const [q, setQ] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    if (!tenantId) {
      setRows([]);
      return;
    }
    api<EntraGroup[]>(`/admin/entra/groups${qs({ tenant_id: tenantId, q: q.trim() })}`)
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  async function createGroup() {
    setSaving(true);
    setError(null);
    try {
      const group = await api<EntraGroup>("/admin/entra/groups", {
        method: "POST",
        body: JSON.stringify({ tenant_id: tenantId, display_name: name.trim(), description }),
      });
      window.location.href = `/entra/groups/${group.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create group");
      setSaving(false);
    }
  }

  return (
    <div>
      <h2 className="font-display text-2xl">Entra groups</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        Security groups in your tenant. Membership changes here are written to Entra, then synced locally.
      </p>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      {canWrite && (
        <section className="panel-pad mt-6">
          <h3 className="text-sm font-medium">Create group in Entra</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-3">
            <input className="input" placeholder="Group name" value={name} onChange={(e) => setName(e.target.value)} />
            <input
              className="input"
              placeholder="Description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <button className="btn-primary" disabled={!tenantId || !name.trim() || saving} onClick={createGroup}>
              Create in Entra
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
          <Link key={group.id} href={`/entra/groups/${group.id}`} className="panel-pad hover:border-glass/40">
            <h3 className="font-display text-xl">{group.display_name}</h3>
            <p className="mt-2 text-sm text-mist-400">{group.description || "No description"}</p>
            <p className="mt-3 text-xs text-mist-500">
              {group.member_count} member{group.member_count === 1 ? "" : "s"}
              {group.security_enabled ? " · Security" : ""}
              {group.mail_enabled ? " · Mail" : ""}
            </p>
          </Link>
        ))}
        {!rows.length && <p className="text-sm text-mist-500">No Entra groups yet. Connect Graph in Admin and run a sync.</p>}
      </div>
    </div>
  );
}
