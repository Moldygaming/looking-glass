"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { KpiCard } from "@/components/KpiCard";
import { api } from "@/lib/api";
import { when } from "@/lib/format";
import type { AdminOverview } from "@/lib/types";

export default function AdminOverviewPage() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<AdminOverview>("/admin/overview")
      .then(setData)
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) return <div className="panel-pad text-rose">{error}</div>;
  if (!data) return <p className="text-mist-400">Loading overview…</p>;

  return (
    <div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Users" value={String(data.user_count)} hint={`${data.active_user_count} active`} />
        <KpiCard
          label="Disabled"
          value={String(data.disabled_user_count)}
          hint="Cannot sign in to the API"
          tone={data.disabled_user_count ? "warn" : "good"}
        />
        <KpiCard label="Groups" value={String(data.group_count)} hint={`${data.role_count ?? 0} roles`} />
        <KpiCard
          label="Unassigned"
          value={String(data.users_without_groups.length)}
          hint="Active users in no group"
          tone={data.users_without_groups.length ? "warn" : "good"}
        />
      </div>

      {(data.users_without_groups.length > 0 || data.groups_without_roles.length > 0) && (
        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          {data.users_without_groups.length > 0 && (
            <section className="panel-pad">
              <h2 className="text-sm font-medium">Users without a group</h2>
              <p className="mt-1 text-xs text-mist-500">They can sign in but inherit no roles or data scopes.</p>
              <ul className="mt-3 space-y-2 text-sm">
                {data.users_without_groups.map((user) => (
                  <li key={user.id} className="flex items-center justify-between gap-3">
                    <span>
                      {user.display_name}
                      <span className="ml-2 text-xs text-mist-500">{user.email}</span>
                    </span>
                    <Link href={`/admin/users/${user.id}`} className="text-xs text-glass">
                      Assign
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {data.groups_without_roles.length > 0 && (
            <section className="panel-pad">
              <h2 className="text-sm font-medium">Groups without a role</h2>
              <p className="mt-1 text-xs text-mist-500">Members will not be able to open FinOps or connections pages.</p>
              <ul className="mt-3 space-y-2 text-sm">
                {data.groups_without_roles.map((group) => (
                  <li key={group.id} className="flex items-center justify-between gap-3">
                    <span>{group.name}</span>
                    <Link href={`/admin/groups/${group.id}`} className="text-xs text-glass">
                      Grant
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      <section className="panel-pad mt-6">
        <h2 className="text-sm font-medium">Recent sign-ins</h2>
        <div className="table-wrap mt-3">
          <table className="admin-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Status</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_logins.map((row) => (
                <tr key={row.id}>
                  <td>
                    <Link href={`/admin/users/${row.id}`} className="text-mist-100 hover:text-glass">
                      {row.display_name}
                    </Link>
                    <div className="text-xs text-mist-500">{row.email}</div>
                  </td>
                  <td className="capitalize text-mist-400">{row.status}</td>
                  <td className="text-mist-400">{when(row.last_login_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
