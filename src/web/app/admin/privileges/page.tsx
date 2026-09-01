"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { PrivilegeAssignment } from "@/lib/types";

export default function PrivilegesPage() {
  const [rows, setRows] = useState<PrivilegeAssignment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [moduleFilter, setModuleFilter] = useState("");

  useEffect(() => {
    api<PrivilegeAssignment[]>("/admin/privileges/assignments")
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }, []);

  const modules = useMemo(() => Array.from(new Set(rows.map((row) => row.module))), [rows]);
  const visible = moduleFilter ? rows.filter((row) => row.module === moduleFilter) : rows;

  if (error) return <div className="panel-pad text-rose">{error}</div>;
  if (!rows.length && !error) return <p className="text-mist-400">Loading permissions…</p>;

  return (
    <div>
      <h2 className="font-display text-2xl">Permissions</h2>
      <p className="mt-1 max-w-2xl text-sm text-mist-400">
        These are the checkboxes you tick when creating a role. Grant them by putting a role on a group (preferred) or
        a user.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button className={!moduleFilter ? "tab tab-active" : "tab"} onClick={() => setModuleFilter("")}>
          All
        </button>
        {modules.map((module) => (
          <button
            key={module}
            className={moduleFilter === module ? "tab tab-active" : "tab"}
            onClick={() => setModuleFilter(module)}
          >
            {module}
          </button>
        ))}
      </div>
      <div className="table-wrap mt-4">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Permission</th>
              <th>Roles</th>
              <th>Groups</th>
              <th>Direct users</th>
              <th>Effective users</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.key}>
                <td>
                  <div className="font-medium text-mist-100">{row.name}</div>
                  <div className="font-mono text-[11px] text-glass/80">{row.key}</div>
                  <div className="mt-1 max-w-md text-xs text-mist-500">{row.description}</div>
                </td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {row.roles?.length
                      ? row.roles.map((role) => (
                          <Link key={role.id} href={`/admin/roles/${role.id}`} className="chip hover:border-glass/40">
                            {role.name}
                          </Link>
                        ))
                      : <span className="text-xs text-mist-500">None</span>}
                  </div>
                </td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {row.groups.length
                      ? row.groups.map((group) => (
                          <Link key={group.id} href={`/admin/groups/${group.id}`} className="chip hover:border-glass/40">
                            {group.name}
                          </Link>
                        ))
                      : <span className="text-xs text-mist-500">None</span>}
                  </div>
                </td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {row.direct_users.length
                      ? row.direct_users.map((user) => (
                          <Link key={user.id} href={`/admin/users/${user.id}`} className="chip hover:border-glass/40">
                            {user.display_name}
                          </Link>
                        ))
                      : <span className="text-xs text-mist-500">None</span>}
                  </div>
                </td>
                <td className="text-mist-300">{row.effective_user_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
