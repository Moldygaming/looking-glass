"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { ConnectionForm } from "@/components/ConnectionForm";
import { api } from "@/lib/api";
import type { Connection } from "@/lib/types";

export default function ConnectionSettingsPage() {
  const params = useParams<{ id: string }>();
  const [connection, setConnection] = useState<Connection | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Connection>(`/connections/${params.id}`)
      .then(setConnection)
      .catch((err: Error) => setError(err.message));
  }, [params.id]);

  return (
    <Shell>
      <p className="text-xs uppercase tracking-[0.18em] text-mist-500">Connections</p>
      <h1 className="font-display text-3xl">{connection?.name || "Connection settings"}</h1>
      <p className="mt-2 mb-8 max-w-2xl text-sm text-mist-400">
        Credentials are stored on the API and never returned to the browser after save.
      </p>
      {error && <div className="panel-pad text-rose">{error}</div>}
      {connection && <ConnectionForm existing={connection} />}
    </Shell>
  );
}
