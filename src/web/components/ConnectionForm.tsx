"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Connection } from "@/lib/types";

type Provider = "azure" | "aws" | "gcp";
type TagRow = { key: string; value: string };

const providers: { id: Provider; title: string; body: string }[] = [
  { id: "azure", title: "Azure tenant", body: "Entra tenant + Cost Management scope (subscription, management group, or billing account)." },
  { id: "aws", title: "AWS organisation", body: "Payer / linked account with Cost Explorer or a CUR path." },
  { id: "gcp", title: "GCP organisation", body: "Billing account export in BigQuery plus a service account." },
];

function str(config: Record<string, unknown>, key: string, fallback = "") {
  const value = config[key];
  return typeof value === "string" ? value : fallback;
}

function num(config: Record<string, unknown>, key: string, fallback: number) {
  const value = config[key];
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function tagRows(config: Record<string, unknown>): TagRow[] {
  const tags = config.default_tags;
  if (tags && typeof tags === "object" && !Array.isArray(tags)) {
    const rows = Object.entries(tags as Record<string, string>).map(([key, value]) => ({ key, value: String(value) }));
    if (rows.length) return rows;
  }
  return [{ key: "", value: "" }];
}

function buildScope(kind: string, value: string, custom: string) {
  const id = value.trim();
  if (kind === "subscription") return id ? `/subscriptions/${id}` : "";
  if (kind === "management_group") return id ? `/providers/Microsoft.Management/managementGroups/${id}` : "";
  if (kind === "billing_account") return id ? `/providers/Microsoft.Billing/billingAccounts/${id}` : "";
  return custom.trim();
}

function parseScope(scope: string, storedKind: string, storedValue: string) {
  if (storedKind && storedKind !== "subscription") {
    return { kind: storedKind, value: storedValue, custom: scope };
  }
  const sub = scope.match(/^\/subscriptions\/([^/]+)$/);
  if (sub) return { kind: "subscription", value: sub[1], custom: scope };
  const mg = scope.match(/managementGroups\/([^/]+)$/);
  if (mg) return { kind: "management_group", value: mg[1], custom: scope };
  const bill = scope.match(/billingAccounts\/([^/]+)$/);
  if (bill) return { kind: "billing_account", value: bill[1], custom: scope };
  if (scope) return { kind: "custom", value: "", custom: scope };
  return { kind: storedKind || "subscription", value: storedValue, custom: scope };
}

export function ConnectionForm({ existing }: { existing?: Connection }) {
  const router = useRouter();
  const initial = existing?.config || {};
  const [provider, setProvider] = useState<Provider | "">((existing?.provider as Provider) || "");
  const [name, setName] = useState(existing?.name || "");
  const [lookback, setLookback] = useState(num(initial, "lookback_days", 14));
  const [currency, setCurrency] = useState(str(initial, "currency", "GBP"));
  const [tags, setTags] = useState<TagRow[]>(tagRows(initial));
  const [busy, setBusy] = useState<"save" | "test" | "ingest" | "delete" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const parsedScope = parseScope(str(initial, "scope"), str(initial, "scope_kind"), str(initial, "scope_value"));
  const [tenantId, setTenantId] = useState(str(initial, "tenant_id"));
  const [clientId, setClientId] = useState(str(initial, "client_id"));
  const [clientSecret, setClientSecret] = useState("");
  const [scopeKind, setScopeKind] = useState(parsedScope.kind);
  const [scopeValue, setScopeValue] = useState(parsedScope.value);
  const [scopeCustom, setScopeCustom] = useState(parsedScope.custom);

  const [accountId, setAccountId] = useState(str(initial, "account_id"));
  const [region, setRegion] = useState(str(initial, "region", "eu-west-2"));
  const [accessKey, setAccessKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [curUri, setCurUri] = useState(str(initial, "cur_uri"));

  const [projectId, setProjectId] = useState(str(initial, "project_id"));
  const [billingTable, setBillingTable] = useState(str(initial, "billing_table"));
  const [saJson, setSaJson] = useState("");

  const azureScope = useMemo(
    () => buildScope(scopeKind, scopeValue, scopeCustom),
    [scopeKind, scopeValue, scopeCustom]
  );

  function payload() {
    const default_tags: Record<string, string> = {};
    for (const row of tags) {
      if (row.key.trim() && row.value.trim()) default_tags[row.key.trim()] = row.value.trim();
    }
    const shared = { lookback_days: lookback, currency, default_tags };
    if (provider === "azure") {
      return {
        name,
        provider,
        config: {
          ...shared,
          tenant_id: tenantId.trim(),
          client_id: clientId.trim(),
          scope_kind: scopeKind,
          scope_value: scopeValue.trim(),
          scope: azureScope,
        },
        secrets: { client_secret: clientSecret },
      };
    }
    if (provider === "aws") {
      return {
        name,
        provider,
        config: { ...shared, account_id: accountId.trim(), region, cur_uri: curUri.trim() },
        secrets: { access_key_id: accessKey, secret_access_key: secretKey },
      };
    }
    return {
      name,
      provider,
      config: { ...shared, project_id: projectId.trim(), billing_table: billingTable.trim() },
      secrets: { service_account_json: saJson },
    };
  }

  async function save() {
    if (!provider || !name.trim()) return;
    setBusy("save");
    setError(null);
    setMessage(null);
    try {
      const body = payload();
      const saved = existing
        ? await api<Connection>(`/connections/${existing.id}`, { method: "PUT", body: JSON.stringify(body) })
        : await api<Connection>("/connections", { method: "POST", body: JSON.stringify(body) });
      setMessage("Settings saved. Secrets are stored on the server and are never shown again.");
      if (!existing) router.replace(`/connections/${saved.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    if (!provider || !name.trim()) return;
    setBusy("test");
    setError(null);
    setMessage(null);
    try {
      const body = payload();
      const saved = existing
        ? await api<Connection>(`/connections/${existing.id}`, { method: "PUT", body: JSON.stringify(body) })
        : await api<Connection>("/connections", { method: "POST", body: JSON.stringify(body) });
      const result = await api<{ ok: boolean; message: string }>(`/connections/${saved.id}/test`, { method: "POST" });
      if (result.ok) setMessage(result.message);
      else setError(result.message);
      if (!existing) router.replace(`/connections/${saved.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test failed");
    } finally {
      setBusy(null);
    }
  }

  async function ingest() {
    if (!existing) return;
    setBusy("ingest");
    setError(null);
    setMessage(null);
    try {
      await api(`/connections/${existing.id}`, { method: "PUT", body: JSON.stringify(payload()) });
      const result = await api<{ written: number }>(`/connections/${existing.id}/ingest`, { method: "POST" });
      setMessage(`Ingest finished. ${result.written} cost rows written.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (!existing || !confirm("Delete this cloud connection? Its ingested cost rows will be removed.")) return;
    setBusy("delete");
    try {
      await api(`/connections/${existing.id}`, { method: "DELETE" });
      router.push("/connections");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
      setBusy(null);
    }
  }

  if (!provider) {
    return (
      <div className="grid gap-4 md:grid-cols-3">
        {providers.map((p) => (
          <button key={p.id} className="panel-pad text-left hover:border-glass/40" onClick={() => setProvider(p.id)}>
            <div className="text-xs uppercase tracking-[0.16em] text-glass">{p.id}</div>
            <h2 className="mt-2 font-display text-xl">{p.title}</h2>
            <p className="mt-2 text-sm text-mist-400">{p.body}</p>
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="panel-pad grid gap-4 md:grid-cols-2">
        <div>
          <label className="label">Display name</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Contoso production Azure" />
        </div>
        <div>
          <label className="label">Provider</label>
          <input className="input opacity-70" value={providers.find((p) => p.id === provider)?.title} readOnly />
        </div>
      </section>

      {provider === "azure" && (
        <section className="panel-pad space-y-4">
          <h2 className="font-display text-xl">Azure identity</h2>
          <p className="text-sm text-mist-400">
            Register an app in this tenant, grant it <span className="text-mist-100">Cost Management Reader</span> on the
            chosen scope, then paste the application credentials.
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="label">Directory (tenant) ID</label>
              <input className="input font-mono" value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
            </div>
            <div>
              <label className="label">Application (client) ID</label>
              <input className="input font-mono" value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
            </div>
            <div className="md:col-span-2">
              <label className="label">Client secret</label>
              <input
                className="input font-mono"
                type="password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                placeholder={existing?.credentials_configured ? "Leave blank to keep the current secret" : "Paste the client secret"}
              />
            </div>
          </div>
          <h3 className="pt-2 text-sm font-medium">Cost Management scope</h3>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="label">Scope type</label>
              <select className="input" value={scopeKind} onChange={(e) => setScopeKind(e.target.value)}>
                <option value="subscription">Subscription</option>
                <option value="management_group">Management group</option>
                <option value="billing_account">Billing account</option>
                <option value="custom">Custom ARM scope</option>
              </select>
            </div>
            {scopeKind === "custom" ? (
              <div>
                <label className="label">ARM scope</label>
                <input className="input font-mono" value={scopeCustom} onChange={(e) => setScopeCustom(e.target.value)} placeholder="/providers/Microsoft.Billing/billingAccounts/..." />
              </div>
            ) : (
              <div>
                <label className="label">
                  {scopeKind === "subscription" ? "Subscription ID" : scopeKind === "management_group" ? "Management group ID" : "Billing account ID"}
                </label>
                <input className="input font-mono" value={scopeValue} onChange={(e) => setScopeValue(e.target.value)} />
              </div>
            )}
          </div>
          <p className="hint">Resolved scope: {azureScope || "—"}</p>
        </section>
      )}

      {provider === "aws" && (
        <section className="panel-pad space-y-4">
          <h2 className="font-display text-xl">AWS identity</h2>
          <p className="text-sm text-mist-400">
            Use a payer account IAM user or role with <span className="text-mist-100">ce:GetCostAndUsage</span>. CUR in S3 is optional.
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="label">Payer / account ID</label>
              <input className="input font-mono" value={accountId} onChange={(e) => setAccountId(e.target.value)} placeholder="123456789012" />
            </div>
            <div>
              <label className="label">Region</label>
              <input className="input font-mono" value={region} onChange={(e) => setRegion(e.target.value)} placeholder="eu-west-2" />
              <p className="hint">Cost Explorer is called in this region. For most orgs that is us-east-1 or your home region.</p>
            </div>
            <div>
              <label className="label">Access key ID</label>
              <input
                className="input font-mono"
                value={accessKey}
                onChange={(e) => setAccessKey(e.target.value)}
                placeholder={existing?.credentials_configured ? "Leave blank to keep the current key" : "AKIA..."}
              />
            </div>
            <div>
              <label className="label">Secret access key</label>
              <input
                className="input font-mono"
                type="password"
                value={secretKey}
                onChange={(e) => setSecretKey(e.target.value)}
                placeholder={existing?.credentials_configured ? "Leave blank to keep the current secret" : ""}
              />
            </div>
            <div className="md:col-span-2">
              <label className="label">CUR URI (optional)</label>
              <input className="input font-mono" value={curUri} onChange={(e) => setCurUri(e.target.value)} placeholder="s3://my-cur-bucket/prefix/" />
            </div>
          </div>
        </section>
      )}

      {provider === "gcp" && (
        <section className="panel-pad space-y-4">
          <h2 className="font-display text-xl">GCP identity</h2>
          <p className="text-sm text-mist-400">
            Enable Cloud Billing export to BigQuery, then grant the service account Job User plus read on that dataset.
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="label">GCP project ID</label>
              <input className="input font-mono" value={projectId} onChange={(e) => setProjectId(e.target.value)} placeholder="my-billing-project" />
            </div>
            <div>
              <label className="label">Billing export table</label>
              <input className="input font-mono" value={billingTable} onChange={(e) => setBillingTable(e.target.value)} placeholder="project.dataset.gcp_billing_export_v1" />
            </div>
            <div className="md:col-span-2">
              <label className="label">Service account JSON</label>
              <textarea
                className="textarea"
                value={saJson}
                onChange={(e) => setSaJson(e.target.value)}
                placeholder={existing?.credentials_configured ? "Leave blank to keep the current key file" : '{ "type": "service_account", ... }'}
              />
            </div>
          </div>
        </section>
      )}

      <section className="panel-pad space-y-4">
        <h2 className="font-display text-xl">Ingest options</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="label">Lookback (days)</label>
            <input className="input" type="number" min={1} max={90} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 14)} />
          </div>
          <div>
            <label className="label">Currency display</label>
            <input className="input" value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
          </div>
        </div>
        <div>
          <label className="label">Default tags applied to ingested rows</label>
          <div className="space-y-2">
            {tags.map((row, index) => (
              <div key={index} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                <input
                  className="input"
                  placeholder="key (team)"
                  value={row.key}
                  onChange={(e) => setTags(tags.map((t, i) => (i === index ? { ...t, key: e.target.value } : t)))}
                />
                <input
                  className="input"
                  placeholder="value (infra)"
                  value={row.value}
                  onChange={(e) => setTags(tags.map((t, i) => (i === index ? { ...t, value: e.target.value } : t)))}
                />
                <button className="btn-ghost" type="button" onClick={() => setTags(tags.filter((_, i) => i !== index))}>
                  Remove
                </button>
              </div>
            ))}
          </div>
          <button className="btn-ghost mt-3" type="button" onClick={() => setTags([...tags, { key: "", value: "" }])}>
            Add tag
          </button>
          <p className="hint">Use this when the cloud export does not already carry organisation tags you want in access groups.</p>
        </div>
      </section>

      {error && <div className="panel-pad text-sm text-rose">{error}</div>}
      {message && <div className="panel-pad text-sm text-glass">{message}</div>}

      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" onClick={save} disabled={Boolean(busy) || !name.trim()}>
          {busy === "save" ? "Saving…" : "Save settings"}
        </button>
        <button className="btn-ghost" onClick={test} disabled={Boolean(busy) || !name.trim()}>
          {busy === "test" ? "Testing…" : "Test connection"}
        </button>
        {existing && (
          <>
            <button className="btn-ghost" onClick={ingest} disabled={Boolean(busy)}>
              {busy === "ingest" ? "Ingesting…" : "Run ingest"}
            </button>
            <button className="btn-danger ml-auto" onClick={remove} disabled={Boolean(busy)}>
              Delete
            </button>
          </>
        )}
      </div>
    </div>
  );
}
