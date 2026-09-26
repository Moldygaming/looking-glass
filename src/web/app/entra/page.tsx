"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useEntraTenant } from "@/components/EntraTenantProvider";
import { KpiCard } from "@/components/KpiCard";
import { api, qs } from "@/lib/api";
import { when } from "@/lib/format";
import type { EntraApp, EntraGroup, EntraUser } from "@/lib/types";

export default function EntraOverviewPage() {
  const { tenants, tenant, tenantId } = useEntraTenant();
  const [users, setUsers] = useState<EntraUser[]>([]);
  const [groups, setGroups] = useState<EntraGroup[]>([]);
  const [apps, setApps] = useState<EntraApp[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantId) {
      setUsers([]);
      setGroups([]);
      setApps([]);
      return;
    }
    const query = qs({ tenant_id: tenantId });
    api<EntraUser[]>(`/admin/entra/users${query}`)
      .then(setUsers)
      .catch((err: Error) => setError(err.message));
    api<EntraGroup[]>(`/admin/entra/groups${query}`)
      .then(setGroups)
      .catch(() => setGroups([]));
    api<EntraApp[]>(`/admin/entra/apps${qs({ tenant_id: tenantId, hide_microsoft: "false" })}`)
      .then(setApps)
      .catch(() => setApps([]));
  }, [tenantId]);

  const last = tenant?.last_sync;

  if (!tenants.length) {
    return (
      <section className="panel-pad">
        <h2 className="font-display text-2xl">No tenants yet</h2>
        <p className="mt-2 max-w-xl text-sm text-mist-400">
          Add one or more Entra tenants in{" "}
          <Link href="/admin/entra" className="text-glass hover:underline">
            Admin → Entra config
          </Link>
          . Each tenant uses its own app registration.
        </p>
      </section>
    );
  }

  return (
    <div>
      <h2 className="font-display text-2xl">{tenant?.name || "Directory"}</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        {tenant?.domain || tenant?.tenant_id || "Synced identities from Microsoft Entra."}
      </p>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}
      {tenant && !tenant.credentials_configured && (
        <section className="panel-pad mt-6">
          <h3 className="text-sm font-medium">Graph credentials missing</h3>
          <p className="mt-2 text-sm text-mist-400">
            Add a client secret for this tenant in{" "}
            <Link href="/admin/entra" className="text-glass hover:underline">
              Admin → Entra config
            </Link>
            .
          </p>
        </section>
      )}

      <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Directory users" value={String(users.length)} hint="Synced from this tenant" />
        <KpiCard label="Directory groups" value={String(groups.length)} hint="Security and Microsoft 365 groups" />
        <KpiCard
          label="Enterprise apps"
          value={String(apps.length)}
          hint={`${apps.filter((app) => app.user_assignment_count + app.group_assignment_count > 0).length} with user or group assignments`}
        />
        <KpiCard
          label="Last sync"
          value={last ? last.status : tenant?.status || "Never"}
          hint={last ? when(last.finished_at || last.started_at) : "Run a sync from Entra config"}
          tone={last?.status === "error" || tenant?.status === "error" ? "bad" : last?.status === "ok" ? "good" : "default"}
        />
      </div>
      {(last?.error || tenant?.last_error) && <p className="mt-3 text-sm text-rose">{last?.error || tenant?.last_error}</p>}
    </div>
  );
}
