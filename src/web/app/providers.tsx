"use client";

import { SessionProvider } from "next-auth/react";
import { MeProvider } from "@/components/MeProvider";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <MeProvider>{children}</MeProvider>
    </SessionProvider>
  );
}
