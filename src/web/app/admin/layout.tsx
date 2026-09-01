"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Shell } from "@/components/Shell";
import { useMe } from "@/components/MeProvider";
import { canAccessAdmin, hasPrivilege } from "@/lib/iam";

const tabs = [
  { href: "/admin", label: "Overview", exact: true, anyOf: ["admin.users.read", "admin.groups.read", "admin.roles.read"] },
  { href: "/admin/users", label: "Users", anyOf: ["admin.users.read"] },
  { href: "/admin/groups", label: "Groups", anyOf: ["admin.groups.read"] },
  { href: "/admin/roles", label: "Roles", anyOf: ["admin.roles.read", "admin.groups.read", "admin.users.read"] },
  { href: "/admin/privileges", label: "Permissions", anyOf: ["admin.users.read", "admin.groups.read", "admin.roles.read"] },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { me, loading } = useMe();

  if (loading) {
    return (
      <Shell>
        <p className="text-mist-400">Loading admin…</p>
      </Shell>
    );
  }

  if (!canAccessAdmin(me)) {
    return (
      <Shell>
        <h1 className="font-display text-3xl">Admin</h1>
        <p className="mt-2 max-w-xl text-sm text-mist-400">
          You need an admin privilege to manage users, groups and access.
        </p>
      </Shell>
    );
  }

  const visible = tabs.filter((tab) => hasPrivilege(me, ...tab.anyOf));

  return (
    <Shell>
      <p className="text-xs uppercase tracking-[0.18em] text-mist-500">Admin</p>
      <h1 className="font-display text-3xl">Directory &amp; access</h1>
      <p className="mt-2 max-w-2xl text-sm text-mist-400">
        Create <span className="text-mist-100">roles</span> by ticking permissions, assign those roles to{" "}
        <span className="text-mist-100">groups</span> (or people), and use{" "}
        <span className="text-mist-100">data scopes</span> to limit which cloud resources they can see.
      </p>
      <nav className="mt-6 flex flex-wrap gap-2">
        {visible.map((tab) => {
          const active = tab.exact ? path === tab.href : path === tab.href || path.startsWith(`${tab.href}/`);
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
