"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import {
  Cloud,
  Gauge,
  IdCard,
  LayoutDashboard,
  LogOut,
  Plug,
  Shield,
  Sparkles,
} from "lucide-react";
import { Logo } from "./Logo";
import { useMe } from "./MeProvider";
import { canAccessAdmin, hasPrivilege } from "@/lib/iam";

type NavItem = {
  href: string;
  label: string;
  icon: typeof Gauge;
  anyOf?: string[];
  admin?: boolean;
};

const sections: { label: string | null; items: NavItem[] }[] = [
  {
    label: null,
    items: [{ href: "/", label: "Overview", icon: Gauge, anyOf: ["finops.costs.read"] }],
  },
  {
    label: "FinOps",
    items: [
      { href: "/costs", label: "Cost explorer", icon: Cloud, anyOf: ["finops.costs.read"] },
      { href: "/dashboards", label: "Dashboards", icon: LayoutDashboard, anyOf: ["finops.dashboards.read"] },
      { href: "/recommendations", label: "Savings", icon: Sparkles, anyOf: ["finops.recommendations.read"] },
    ],
  },
  {
    label: "Infrastructure",
    items: [
      { href: "/connections", label: "Connections", icon: Plug, anyOf: ["connections.read"] },
      { href: "/entra", label: "Entra", icon: IdCard, anyOf: ["admin.entra.read", "admin.entra.helpdesk"] },
      { href: "/admin", label: "Admin", icon: Shield, admin: true },
    ],
  },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { data } = useSession();
  const { me, loading, error } = useMe();
  const sessionAdmin = data?.user?.roles?.includes("platform_admin");
  const showAdmin = loading ? sessionAdmin : canAccessAdmin(me);

  function visible(item: NavItem) {
    if (item.admin) return loading && !me ? Boolean(sessionAdmin) : showAdmin;
    if (loading && !me) return true;
    return hasPrivilege(me, ...(item.anyOf || []));
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[260px_1fr]">
      <aside className="border-b border-white/10 bg-ink-900/80 lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-3 px-5 py-5">
          <Logo />
          <div>
            <div className="font-display text-lg leading-none tracking-tight">Looking Glass</div>
            <div className="mt-1 text-[11px] uppercase tracking-[0.18em] text-mist-500">Infra ops</div>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible">
          {sections.map((section) => {
            const items = section.items.filter((item) => visible(item));
            if (!items.length) return null;
            return (
              <div key={section.label || "root"} className="contents lg:block">
                {section.label && (
                  <div className="mb-1 mt-4 hidden px-3 text-[10px] uppercase tracking-[0.18em] text-mist-500 lg:block">
                    {section.label}
                  </div>
                )}
                {items.map((item) => {
                  const active = item.href === "/" ? path === "/" : path.startsWith(item.href);
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm ${
                        active ? "bg-glass/10 text-glass" : "text-mist-400 hover:bg-white/5 hover:text-mist-100"
                      }`}
                    >
                      <Icon size={16} />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            );
          })}
        </nav>
        <div className="hidden border-t border-white/10 p-4 lg:block">
          <div className="text-sm font-medium">{data?.user?.name}</div>
          <div className="truncate text-xs text-mist-500">{data?.user?.email}</div>
          <button onClick={() => signOut({ callbackUrl: "/login" })} className="btn-ghost mt-3 w-full">
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>
      <main className="min-w-0 p-4 sm:p-8">
        {error && (
          <div className="panel-pad mb-6 text-rose">
            {error.includes("disabled") ? "This account has been disabled. Contact a platform administrator." : error}
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
