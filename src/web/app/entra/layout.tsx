"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { EntraTenantProvider, useEntraTenant } from "@/components/EntraTenantProvider";
import { Shell } from "@/components/Shell";
import { useMe } from "@/components/MeProvider";
import { hasPrivilege } from "@/lib/iam";

const directoryTabs = [
  { href: "/entra", label: "Overview", exact: true },
  { href: "/entra/users", label: "Users" },
  { href: "/entra/groups", label: "Groups" },
];

const adminTabs = [
  { href: "/entra/apps", label: "Apps" },
  { href: "/entra/licenses", label: "Licenses" },
  { href: "/entra/templates", label: "Templates" },
  { href: "/entra/bulk", label: "Bulk" },
  { href: "/entra/audit", label: "Audit" },
];

function EntraShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { me, loading } = useMe();
  const { tenants, tenantId, select } = useEntraTenant();

  if (loading) {
    return (
      <Shell>
        <p className="text-mist-400">Loading Entra…</p>
      </Shell>
    );
  }

  const canOpen = hasPrivilege(me, "admin.entra.read", "admin.entra.helpdesk");
  const canRead = hasPrivilege(me, "admin.entra.read");
  const tabs = canRead ? [...directoryTabs, ...adminTabs] : directoryTabs;

  if (!canOpen) {
    return (
      <Shell>
        <p className="text-xs uppercase tracking-[0.18em] text-mist-500">Infrastructure</p>
        <h1 className="font-display text-3xl">Microsoft Entra</h1>
        <p className="mt-2 max-w-xl text-sm text-mist-400">You need permission to view the Entra directory.</p>
      </Shell>
    );
  }

  return (
    <Shell>
      <p className="text-xs uppercase tracking-[0.18em] text-mist-500">Infrastructure</p>
      <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl">Microsoft Entra</h1>
          <p className="mt-2 max-w-2xl text-sm text-mist-400">
            Users, groups, licenses, and bulk changes for the selected tenant. Add tenants in{" "}
            <Link href="/admin/entra" className="text-glass hover:underline">
              Admin → Entra config
            </Link>
            .
          </p>
        </div>
        {tenants.length > 0 && (
          <label className="min-w-[220px]">
            <span className="label">Tenant</span>
            <select className="input" value={tenantId} onChange={(e) => select(e.target.value)}>
              {tenants.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                  {row.domain ? ` · ${row.domain}` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <nav className="mt-6 flex flex-wrap gap-2">
        {tabs.map((tab) => {
          const exact = "exact" in tab && tab.exact;
          const active = exact ? path === tab.href : path === tab.href || path.startsWith(`${tab.href}/`);
          return (
            <Link key={tab.href} href={tab.href} className={active ? "tab tab-active" : "tab"}>
              {tab.label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-8">{children}</div>
    </Shell>
  );
}

export default function EntraLayout({ children }: { children: React.ReactNode }) {
  return (
    <EntraTenantProvider>
      <EntraShell>{children}</EntraShell>
    </EntraTenantProvider>
  );
}
