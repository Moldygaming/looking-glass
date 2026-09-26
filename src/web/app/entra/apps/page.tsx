"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useEntraTenant } from "@/components/EntraTenantProvider";
import { api, qs } from "@/lib/api";
import type { EntraApp } from "@/lib/types";

export default function DirectoryAppsPage() {
  const { tenantId } = useEntraTenant();
  const [rows, setRows] = useState<EntraApp[]>([]);
  const [q, setQ] = useState("");
  const [hideMicrosoft, setHideMicrosoft] = useState(true);
  const [assignedOnly, setAssignedOnly] = useState(false);
  const [registrationsOnly, setRegistrationsOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (!tenantId) {
      setRows([]);
      return;
    }
    api<EntraApp[]>(
      `/admin/entra/apps${qs({
        tenant_id: tenantId,
        q: q.trim(),
        hide_microsoft: hideMicrosoft ? "true" : "false",
        assigned_only: assignedOnly ? "true" : "false",
        registrations_only: registrationsOnly ? "true" : "false",
      })}`
    )
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, hideMicrosoft, assignedOnly, registrationsOnly]);

  return (
    <div>
      <h2 className="font-display text-2xl">Enterprise apps</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        Users and groups assigned to enterprise applications in Entra. Assignments live on the service principal, including
        apps that also have an in-tenant app registration.
      </p>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      <div className="mt-6 grid gap-2 md:grid-cols-4">
        <input
          className="input md:col-span-2"
          placeholder="Search name, client ID or publisher"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
        />
        <button className="btn-ghost" onClick={load}>
          Filter
        </button>
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-sm text-mist-400">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={hideMicrosoft} onChange={(e) => setHideMicrosoft(e.target.checked)} />
          Hide unassigned Microsoft apps
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={assignedOnly} onChange={(e) => setAssignedOnly(e.target.checked)} />
          Assigned only
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={registrationsOnly} onChange={(e) => setRegistrationsOnly(e.target.checked)} />
          App registrations only
        </label>
      </div>

      <div className="table-wrap mt-4">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Application</th>
              <th>Type</th>
              <th>Users</th>
              <th>Groups</th>
              <th>Assignment</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link href={`/entra/apps/${row.id}`} className="font-medium text-mist-100 hover:text-glass">
                    {row.display_name}
                  </Link>
                  <div className="text-xs text-mist-500">{row.publisher_name || row.app_id}</div>
                </td>
                <td className="text-mist-400">
                  {row.has_app_registration ? "App registration" : "Enterprise app"}
                  {row.is_microsoft ? <div className="text-xs text-mist-500">Microsoft</div> : null}
                </td>
                <td>{row.user_assignment_count}</td>
                <td>{row.group_assignment_count}</td>
                <td className="text-mist-400">{row.assignment_required ? "Required" : "Optional"}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={5} className="py-8 text-center text-mist-500">
                  No enterprise apps yet. Connect Graph in Admin and run a sync.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
