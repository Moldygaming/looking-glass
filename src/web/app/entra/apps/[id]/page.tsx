"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { api } from "@/lib/api";
import { when } from "@/lib/format";
import type { EntraApp, EntraAppAssignment } from "@/lib/types";

function principalLink(row: EntraAppAssignment) {
  const name = row.principal_display_name || row.email || row.principal_id;
  if (row.principal_type === "User" && row.user_id) {
    return (
      <Link href={`/entra/users/${row.user_id}`} className="hover:text-glass">
        {name}
      </Link>
    );
  }
  if (row.principal_type === "Group" && row.group_id) {
    return (
      <Link href={`/entra/groups/${row.group_id}`} className="hover:text-glass">
        {name}
      </Link>
    );
  }
  return <span>{name}</span>;
}

function AssignmentTable({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: EntraAppAssignment[];
  empty: string;
}) {
  return (
    <section className="panel-pad mt-6">
      <h3 className="text-sm font-medium">
        {title} ({rows.length})
      </h3>
      <ul className="mt-4 space-y-2 text-sm">
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 py-2">
            <span>
              {principalLink(row)}
              {row.email && <span className="ml-2 text-xs text-mist-500">{row.email}</span>}
              {row.status && (
                <span className="ml-2">
                  <StatusBadge status={row.status} />
                </span>
              )}
            </span>
            <span className="text-xs text-mist-500">{row.app_role_name}</span>
          </li>
        ))}
        {!rows.length && <li className="text-mist-500">{empty}</li>}
      </ul>
    </section>
  );
}

export default function DirectoryAppDetailPage() {
  const params = useParams<{ id: string }>();
  const [app, setApp] = useState<EntraApp | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<EntraApp>(`/admin/entra/apps/${params.id}`)
      .then(setApp)
      .catch((err: Error) => setError(err.message));
  }, [params.id]);

  if (!app) {
    return <p className="text-mist-400">{error || "Loading application…"}</p>;
  }

  const users = app.assignments.filter((row) => row.principal_type === "User");
  const groups = app.assignments.filter((row) => row.principal_type === "Group");
  const others = app.assignments.filter((row) => row.principal_type !== "User" && row.principal_type !== "Group");

  return (
    <div>
      <Link href="/entra/apps" className="text-xs text-mist-500 hover:text-glass">
        ← Enterprise apps
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl">{app.display_name}</h2>
          <p className="mt-1 text-sm text-mist-400">{app.publisher_name || "No publisher"}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="chip">{app.has_app_registration ? "App registration" : "Enterprise app"}</span>
          {app.is_microsoft && <span className="chip">Microsoft</span>}
          <span className="chip">{app.account_enabled ? "Enabled" : "Disabled"}</span>
        </div>
      </div>
      {error && <div className="panel-pad mt-4 text-rose">{error}</div>}

      <dl className="panel-pad mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="label">Application (client) ID</dt>
          <dd className="font-mono text-xs text-mist-300">{app.app_id}</dd>
        </div>
        <div>
          <dt className="label">Service principal ID</dt>
          <dd className="font-mono text-xs text-mist-300">{app.service_principal_id}</dd>
        </div>
        <div>
          <dt className="label">App registration object ID</dt>
          <dd className="font-mono text-xs text-mist-300">{app.application_object_id || "Not in this tenant"}</dd>
        </div>
        <div>
          <dt className="label">Last synced</dt>
          <dd className="text-sm">{when(app.last_synced_at)}</dd>
        </div>
      </dl>

      <p className="mt-4 max-w-3xl text-sm text-mist-400">
        {app.assignment_required
          ? "User assignment is required. Only the users and groups listed below can sign in to this app."
          : "User assignment is optional. People can sign in without being listed, but these identities are still assigned a role."}
      </p>
      {app.description && <p className="mt-2 max-w-3xl text-sm text-mist-500">{app.description}</p>}

      {!!app.app_roles.length && (
        <section className="panel-pad mt-6">
          <h3 className="text-sm font-medium">App roles ({app.app_roles.length})</h3>
          <ul className="mt-4 space-y-2 text-sm">
            {app.app_roles.map((role) => (
              <li key={role.id} className="border-b border-white/5 py-2">
                <span className="text-mist-100">{role.display_name}</span>
                {role.value && <span className="ml-2 font-mono text-xs text-mist-500">{role.value}</span>}
                {role.description && <div className="text-xs text-mist-500">{role.description}</div>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <AssignmentTable title="Assigned users" rows={users} empty="No users are assigned to this app." />
      <AssignmentTable title="Assigned groups" rows={groups} empty="No groups are assigned to this app." />
      {!!others.length && (
        <AssignmentTable title="Assigned applications" rows={others} empty="No other principals assigned." />
      )}
    </div>
  );
}
