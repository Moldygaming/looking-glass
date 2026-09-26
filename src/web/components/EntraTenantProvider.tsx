"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { EntraTenant } from "@/lib/types";

const STORAGE = "lg.entra-tenant";

type Ctx = {
  tenants: EntraTenant[];
  tenantId: string;
  tenant: EntraTenant | null;
  select: (id: string) => void;
  reload: () => void;
};

const EntraTenantContext = createContext<Ctx>({
  tenants: [],
  tenantId: "",
  tenant: null,
  select: () => undefined,
  reload: () => undefined,
});

export function EntraTenantProvider({ children }: { children: React.ReactNode }) {
  const [tenants, setTenants] = useState<EntraTenant[]>([]);
  const [tenantId, setTenantId] = useState("");

  function apply(rows: EntraTenant[], preferred?: string) {
    setTenants(rows);
    const saved = preferred || (typeof window !== "undefined" ? localStorage.getItem(STORAGE) : "") || "";
    const next = rows.find((row) => row.id === saved)?.id || rows[0]?.id || "";
    setTenantId(next);
    if (next) localStorage.setItem(STORAGE, next);
  }

  function reload() {
    api<EntraTenant[]>("/admin/entra/tenants")
      .then((rows) => apply(rows, tenantId))
      .catch(() => apply([]));
  }

  useEffect(reload, []);

  const value = useMemo<Ctx>(
    () => ({
      tenants,
      tenantId,
      tenant: tenants.find((row) => row.id === tenantId) || null,
      select: (id: string) => {
        setTenantId(id);
        localStorage.setItem(STORAGE, id);
      },
      reload,
    }),
    [tenants, tenantId]
  );

  return <EntraTenantContext.Provider value={value}>{children}</EntraTenantContext.Provider>;
}

export function useEntraTenant() {
  return useContext(EntraTenantContext);
}
