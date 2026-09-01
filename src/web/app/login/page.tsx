"use client";

import { signIn } from "next-auth/react";
import { useEffect, useState } from "react";
import { Logo } from "@/components/Logo";

const personas = [
  {
    id: "admin",
    name: "Avery Chen",
    role: "Platform admin",
    detail: "Platform admin. Manages users, groups, privileges and connectors.",
  },
  {
    id: "infra",
    name: "Sam Okonkwo",
    role: "Infra",
    detail: "Tag scope team=infra — all infra subscriptions, AWS accounts and GCP projects.",
  },
  {
    id: "project",
    name: "Priya Shah",
    role: "Project Alpha",
    detail: "Tag scope project=alpha — only Alpha application spend.",
  },
];

export default function LoginPage() {
  const [entra, setEntra] = useState(false);
  useEffect(() => {
    fetch("/api/config")
      .then((res) => res.json())
      .then((data) => setEntra(Boolean(data.entra)))
      .catch(() => setEntra(false));
  }, []);
  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16">
      <div className="mb-10 flex items-center gap-3">
        <Logo className="h-10 w-10" />
        <div>
          <h1 className="font-display text-3xl">Looking Glass</h1>
          <p className="text-sm text-mist-400">Infra ops for every cloud. Access, connectors and FinOps in one place.</p>
        </div>
      </div>
      {entra && (
        <button
          className="btn-primary mb-8 w-full max-w-sm"
          onClick={() => signIn("microsoft-entra-id", { callbackUrl: "/" })}
        >
          Sign in with Microsoft Entra ID
        </button>
      )}
      <p className="mb-4 text-xs uppercase tracking-[0.18em] text-mist-500">Demo personas</p>
      <div className="grid gap-4 md:grid-cols-3">
        {personas.map((p) => (
          <button
            key={p.id}
            onClick={() => signIn("demo", { persona: p.id, callbackUrl: "/" })}
            className="panel-pad text-left transition hover:border-glass/40 hover:shadow-glow"
          >
            <div className="font-display text-lg">{p.name}</div>
            <div className="mt-1 text-xs uppercase tracking-[0.16em] text-glass">{p.role}</div>
            <p className="mt-3 text-sm text-mist-400">{p.detail}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
