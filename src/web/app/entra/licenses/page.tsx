"use client";

import { useEffect, useState } from "react";
import { useEntraTenant } from "@/components/EntraTenantProvider";
import { useMe } from "@/components/MeProvider";
import { api, qs } from "@/lib/api";
import { hasPrivilege } from "@/lib/iam";
import type { EntraLicense } from "@/lib/types";

export default function EntraLicensesPage() {
  const { me } = useMe();
  const { tenantId } = useEntraTenant();
  const canWrite = hasPrivilege(me, "admin.entra.write");
  const [rows, setRows] = useState<EntraLicense[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function load() {
    if (!tenantId) {
      setRows([]);
      return;
    }
    api<EntraLicense[]>(`/admin/entra/licenses${qs({ tenant_id: tenantId })}`)
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  async function refresh() {
    if (!tenantId) return;
    setLoading(true);
    setError(null);
    try {
      const next = await api<EntraLicense[]>(`/admin/entra/licenses/refresh${qs({ tenant_id: tenantId })}`, {
        method: "POST",
        body: "{}",
      });
      setRows(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not refresh licenses");
    } finally {
      setLoading(false);
    }
  }

  const assigned = rows.reduce((sum, row) => sum + row.consumed_units, 0);
  const purchased = rows.reduce((sum, row) => sum + row.enabled_units, 0);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl">Licenses</h2>
          <p className="mt-1 max-w-2xl text-sm text-mist-400">
            Subscribed Microsoft 365 products for this tenant. {assigned} assigned of {purchased} purchased seats.
            Assign or remove a license from a user.
          </p>
        </div>
        {canWrite && (
          <button className="btn-primary" disabled={!tenantId || loading} onClick={refresh}>
            {loading ? "Refreshing…" : "Refresh from Entra"}
          </button>
        )}
      </div>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}
      <div className="table-wrap mt-6">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Product</th>
              <th>Assigned</th>
              <th>Purchased</th>
              <th>Available</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <div className="font-medium text-mist-100">{row.display_name}</div>
                  <div className="font-mono text-xs text-mist-500">{row.sku_part_number}</div>
                </td>
                <td>{row.consumed_units}</td>
                <td>{row.enabled_units}</td>
                <td className={row.available_units === 0 ? "text-warn" : ""}>{row.available_units}</td>
                <td className="text-mist-400">{row.capability_status || "—"}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={5} className="py-8 text-center text-mist-500">
                  No licenses cached. Refresh from Entra after the app has Directory.Read.All.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
