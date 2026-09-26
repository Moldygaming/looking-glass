"use client";

import { useState } from "react";
import { useEntraTenant } from "@/components/EntraTenantProvider";
import { api } from "@/lib/api";
import type { EntraBulkResult } from "@/lib/types";

const SAMPLE = `action,user_principal_name,display_name,job_title,department,usage_location,template,groups,licenses
create,ada@contoso.com,Ada Lovelace,Engineer,Research,GB,,Finance Readers,SPE_E5
disable,old.account@contoso.com,,,,,,,
add_groups,ada@contoso.com,,,,,,Helpdesk,
assign_licenses,ada@contoso.com,,,,,,,SPE_E5
reset_password,ada@contoso.com,,,,,,,`;

export default function EntraBulkPage() {
  const { tenantId } = useEntraTenant();
  const [csv, setCsv] = useState(SAMPLE);
  const [result, setResult] = useState<EntraBulkResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function run() {
    if (!tenantId) return;
    setSaving(true);
    setError(null);
    setResult(null);
    try {
      const next = await api<EntraBulkResult>("/admin/entra/bulk", {
        method: "POST",
        body: JSON.stringify({ tenant_id: tenantId, csv }),
      });
      setResult(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk change failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h2 className="font-display text-2xl">Bulk changes</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        One row per change. Actions: create, update, enable, disable, reset_password, add_groups, remove_groups,
        assign_licenses, remove_licenses. Separate several groups or licenses with semicolons. A blank password is
        generated and shown once. Empty update fields are left unchanged.
      </p>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}
      <textarea className="textarea mt-6 min-h-56 font-mono text-xs" value={csv} onChange={(e) => setCsv(e.target.value)} />
      <button className="btn-primary mt-4" disabled={!tenantId || !csv.trim() || saving} onClick={run}>
        {saving ? "Applying…" : "Apply to Entra"}
      </button>
      {result && (
        <div className="mt-6">
          <p className="text-sm text-mist-300">
            {result.ok} succeeded, {result.failed} failed.
          </p>
          <div className="table-wrap mt-3">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Action</th>
                  <th>User</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((row) => (
                  <tr key={`${row.row}-${row.action}`}>
                    <td>{row.row}</td>
                    <td className="font-mono text-xs">{row.action}</td>
                    <td>{row.user_principal_name}</td>
                    <td className={row.status === "error" ? "text-rose" : "text-mist-300"}>{row.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
