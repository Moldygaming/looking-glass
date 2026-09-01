"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";

type MeState = {
  me: Me | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
};

const MeContext = createContext<MeState>({
  me: null,
  loading: true,
  error: null,
  reload: () => undefined,
});

export function MeProvider({ children }: { children: React.ReactNode }) {
  const { status } = useSession();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    if (status !== "authenticated") {
      setMe(null);
      setLoading(status === "loading");
      return;
    }
    setLoading(true);
    api<Me>("/me")
      .then((user) => {
        setMe(user);
        setError(null);
      })
      .catch((err: Error) => {
        setMe(null);
        setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [status]);

  useEffect(() => {
    reload();
  }, [reload]);

  return <MeContext.Provider value={{ me, loading, error, reload }}>{children}</MeContext.Provider>;
}

export function useMe() {
  return useContext(MeContext);
}
