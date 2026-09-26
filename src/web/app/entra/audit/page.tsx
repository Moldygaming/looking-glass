"use client";

import { useEffect, useState } from "react";
import { useEntraTenant } from "@/components/EntraTenantProvider";
import { api, qs } from "@/lib/api";
import { when } from "@/lib/format";
import type { EntraAuditEvent } from "@/lib/types";

export default function EntraAuditPage() {
  const { tenantId } = useEntraTenant();
  const [rows, setRows] = useState<EntraAuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantId) {
      setRows([]);
      return;
    }
    api<EntraAuditEvent[]>(`/admin/entra/audit${qs({ tenant_id: tenantId, limit: 100 })}`)
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }, [tenantId]);

  return (
    <div>
      <h2 className="font-display text-2xl">Directory audit</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        Changes Looking Glass made in this tenant. Passwords are not stored. The Graph request id is the one Microsoft
        returned for the call.
      </p>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}
      <div className="mt-6 space-y-2">
        {rows.map((row) => (
          <details key={row.id} className="panel-pad">
            <summary className="cursor-pointer text-sm">
              <span className="text-mist-500">{when(row.created_at)}</span>
              <span className="mx-2 font-mono text-xs text-glass">{row.action}</span>
              <span>{row.target_label || row.target_id}</span>
              <span className="ml-2 text-mist-500">{row.actor_name || row.actor_email}</span>
              {row.status !== "ok" && <span className="ml-2 text-rose">{row.status}</span>}
            </summary>
            <div className="mt-3 space-y-2 text-xs text-mist-400">
              {row.error && <p className="text-rose">{row.error}</p>}
              {row.graph_request_id && <p className="font-mono">request {row.graph_request_id}</p>}
              {row.before && (
                <pre className="overflow-auto whitespace-pre-wrap">before {JSON.stringify(row.before, null, 2)}</pre>
              )}
              {row.after && <pre className="overflow-auto whitespace-pre-wrap">after {JSON.stringify(row.after, null, 2)}</pre>}
            </div>
          </details>
        ))}
        {!rows.length && !error && <p className="text-sm text-mist-500">No directory changes recorded for this tenant.</p>}
      </div>
    </div>
  );
}
