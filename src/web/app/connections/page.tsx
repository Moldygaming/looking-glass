"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { ProviderBadge } from "@/components/ProviderBadge";
import { useMe } from "@/components/MeProvider";
import { api } from "@/lib/api";
import { hasPrivilege } from "@/lib/iam";
import type { Connection } from "@/lib/types";

function summary(connection: Connection) {
  const cfg = connection.config || {};
  if (connection.provider === "azure") {
    return [cfg.tenant_id && `Tenant ${cfg.tenant_id}`, cfg.scope].filter(Boolean).join(" · ");
  }
  if (connection.provider === "aws") {
    return [cfg.account_id && `Account ${cfg.account_id}`, cfg.region].filter(Boolean).join(" · ");
  }
  return [cfg.project_id, cfg.billing_table].filter(Boolean).join(" · ");
}

export default function ConnectionsPage() {
  const { me } = useMe();
  const canWrite = hasPrivilege(me, "connections.write");
  const [rows, setRows] = useState<Connection[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Connection[]>("/connections")
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <Shell>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl">Cloud connections</h1>
          <p className="mt-2 max-w-2xl text-sm text-mist-400">
            Each connection is one billing organisation. Open a connection to set tenant, credentials, scope and ingest
            options — dummy names are not enough.
          </p>
        </div>
        {canWrite && (
          <Link href="/connections/new" className="btn-primary">
            Add connection
          </Link>
        )}
      </div>
      {error && <div className="panel-pad mt-6 text-rose">{error}</div>}
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {rows.map((c) => (
          <article key={c.id} className="panel-pad flex flex-col">
            <div className="flex items-center justify-between gap-2">
              <ProviderBadge provider={c.provider} />
              <span className={`chip ${c.credentials_configured ? "text-glass" : "text-warn"}`}>
                {c.credentials_configured ? c.status : "needs configuration"}
              </span>
            </div>
            <h2 className="mt-3 font-display text-xl">{c.name}</h2>
            <p className="mt-2 flex-1 font-mono text-xs text-mist-500">{summary(c) || "No settings saved yet."}</p>
            {c.last_error && <p className="mt-2 text-sm text-rose">{c.last_error}</p>}
            {c.last_ingest_at && <p className="mt-2 text-xs text-mist-500">Last ingest {c.last_ingest_at.replace("T", " ").slice(0, 16)} UTC</p>}
            {canWrite && (
              <Link href={`/connections/${c.id}`} className="btn-ghost mt-4 self-start">
                Configure
              </Link>
            )}
          </article>
        ))}
      </div>
    </Shell>
  );
}
