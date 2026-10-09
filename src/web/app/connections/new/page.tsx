"use client";

import { Shell } from "@/components/Shell";
import { ConnectionForm } from "@/components/ConnectionForm";

export default function NewConnectionPage() {
  return (
    <Shell>
      <p className="text-xs uppercase tracking-[0.18em] text-mist-500">Connections</p>
      <h1 className="font-display text-3xl">Add a connection</h1>
      <p className="mt-2 mb-8 max-w-2xl text-sm text-mist-400">
        Choose Azure, AWS, GCP or Azure DevOps, then fill in the organisation identity and credentials.
      </p>
      <ConnectionForm />
    </Shell>
  );
}
