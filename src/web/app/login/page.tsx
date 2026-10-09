"use client";

import { signIn } from "next-auth/react";
import { FormEvent, useEffect, useState } from "react";
import { Logo } from "@/components/Logo";

function errorMessage(code: string | null): string | null {
  if (!code) return null;
  if (code === "AccessDenied") {
    return "You signed in with Entra ID but do not have access to Looking Glass. You must be in the platform admin group, or an administrator must assign you a role in the portal.";
  }
  if (code === "CredentialsSignin") {
    return "Break-glass username or password is incorrect.";
  }
  if (code === "Configuration") {
    return "Sign-in is not configured. Check AUTH_SECRET and the Entra app registration.";
  }
  return "Sign-in failed. Try again or use the break-glass account.";
}

export default function LoginPage() {
  const [entra, setEntra] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"entra" | "local" | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showBreakGlass, setShowBreakGlass] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setError(errorMessage(params.get("error")));
    fetch("/api/config")
      .then((res) => res.json())
      .then((data) => {
        setEntra(Boolean(data.entra));
        if (!data.entra) setShowBreakGlass(true);
      })
      .catch(() => {
        setEntra(false);
        setShowBreakGlass(true);
      });
  }, []);

  async function onBreakGlass(event: FormEvent) {
    event.preventDefault();
    setBusy("local");
    setError(null);
    const callbackUrl = new URLSearchParams(window.location.search).get("callbackUrl") || "/";
    const result = await signIn("break-glass", {
      username,
      password,
      callbackUrl,
      redirect: false,
    });
    setBusy(null);
    if (!result) {
      setError("Sign-in failed. Try again or use the break-glass account.");
      return;
    }
    if (result.error) {
      setError(errorMessage(result.error) || "Break-glass username or password is incorrect.");
      return;
    }
    window.location.href = result.url || callbackUrl;
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-lg flex-col justify-center px-6 py-16">
      <div className="mb-10 flex items-center gap-3">
        <Logo className="h-10 w-10" />
        <div>
          <h1 className="font-display text-3xl">Looking Glass</h1>
          <p className="text-sm text-mist-400">
            Sign in with Microsoft Entra ID. Platform access is granted by the admin group; finer
            permissions are assigned in the portal.
          </p>
        </div>
      </div>

      {error && <div className="panel-pad mb-6 text-sm text-rose">{error}</div>}

      {entra ? (
        <button
          className="btn-primary w-full"
          disabled={busy !== null}
          onClick={() => {
            setBusy("entra");
            const callbackUrl =
              new URLSearchParams(window.location.search).get("callbackUrl") || "/";
            void signIn("microsoft-entra-id", { callbackUrl });
          }}
        >
          {busy === "entra" ? "Redirecting…" : "Sign in with Microsoft Entra ID"}
        </button>
      ) : (
        <div className="panel-pad text-sm text-mist-400">
          Microsoft Entra ID is not configured. Set{" "}
          <span className="font-mono text-mist-200">AUTH_MICROSOFT_ENTRA_ID_ID</span>,{" "}
          <span className="font-mono text-mist-200">AUTH_MICROSOFT_ENTRA_ID_SECRET</span> and{" "}
          <span className="font-mono text-mist-200">AUTH_MICROSOFT_ENTRA_ID_TENANT_ID</span>, plus{" "}
          <span className="font-mono text-mist-200">ENTRA_ADMIN_GROUP_ID</span> for the platform
          admin group. Until then, use the local break-glass account.
        </div>
      )}

      <div className="mt-10">
        <button
          type="button"
          className="text-xs uppercase tracking-[0.18em] text-mist-500 hover:text-mist-300"
          onClick={() => setShowBreakGlass((open) => !open)}
        >
          {showBreakGlass ? "Hide emergency access" : "Emergency local access"}
        </button>
        {showBreakGlass && (
          <form className="panel-pad mt-4" onSubmit={onBreakGlass}>
            <p className="mb-4 text-sm text-mist-400">
              Single break-glass account for when Entra is unavailable. Username defaults to{" "}
              <span className="font-mono text-mist-200">infraadmin</span>.
            </p>
            <label className="label" htmlFor="username">
              Username
            </label>
            <input
              id="username"
              className="input mb-3"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
            <label className="label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            <button className="btn-ghost mt-4 w-full" disabled={busy !== null} type="submit">
              {busy === "local" ? "Signing in…" : "Sign in locally"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
