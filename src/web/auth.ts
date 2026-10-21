import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";

export const BREAK_GLASS_OID = "local-break-glass";

const entraConfigured = Boolean(
  process.env.AUTH_MICROSOFT_ENTRA_ID_ID && process.env.AUTH_MICROSOFT_ENTRA_ID_TENANT_ID
);

function envValue(name: string, fallback = ""): string {
  const value = process.env[name];
  if (value == null || value === "") return fallback;
  return value;
}

const breakGlassUsername = envValue(
  "AUTH_BREAK_GLASS_USERNAME",
  envValue("BREAK_GLASS_USERNAME", "infraadmin")
);
const breakGlassPassword = envValue(
  "AUTH_BREAK_GLASS_PASSWORD",
  envValue("BREAK_GLASS_PASSWORD", "admin123+")
);

function safeEqual(left: string, right: string): boolean {
  const a = left;
  const b = right;
  const max = Math.max(a.length, b.length);
  let mismatch = a.length === b.length ? 0 : 1;
  for (let i = 0; i < max; i++) {
    mismatch |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return mismatch === 0;
}

type EntraProfile = {
  oid?: string;
  sub?: string;
  roles?: string[];
  groups?: string[] | string;
  preferred_username?: string;
  email?: string;
  name?: string;
  _claim_names?: { groups?: string };
};

function profileGroups(profile: EntraProfile): string[] {
  if (Array.isArray(profile.groups)) return profile.groups.map(String);
  if (typeof profile.groups === "string" && profile.groups) return [profile.groups];
  return [];
}

const UPSTREAM_TIMEOUT_MS = 15_000;

function loginError(code: string, reason: string): string {
  const params = new URLSearchParams({ error: code });
  if (reason) params.set("reason", reason.slice(0, 300));
  return `/login?${params.toString()}`;
}

async function responseDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    return "";
  }
  return "";
}

async function resolveGroups(profile: EntraProfile, accessToken?: string): Promise<string[]> {
  const groups = profileGroups(profile);
  const overage = Boolean(profile._claim_names?.groups);
  const adminId = envValue("AUTH_ENTRA_ADMIN_GROUP_ID", envValue("ENTRA_ADMIN_GROUP_ID"));
  const accessId = envValue("AUTH_ENTRA_ACCESS_GROUP_ID", envValue("ENTRA_ACCESS_GROUP_ID"));
  const wanted = [adminId, accessId].filter(Boolean);
  if ((!overage && groups.length) || !accessToken || !wanted.length) return groups;
  try {
    const res = await fetch("https://graph.microsoft.com/v1.0/me/checkMemberGroups", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ groupIds: wanted }),
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
    if (!res.ok) return groups;
    const data = (await res.json()) as { value?: string[] };
    return Array.from(new Set([...groups, ...(data.value || [])]));
  } catch {
    return groups;
  }
}

async function evaluateSso(payload: {
  oid: string;
  email: string;
  display_name: string;
  groups: string[];
  roles: string[];
}): Promise<true | string> {
  const base = process.env.API_URL || "http://127.0.0.1:8000";
  let res: Response;
  try {
    res = await fetch(`${base}/auth/sso`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Internal-Key": process.env.INTERNAL_API_KEY || "",
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (error) {
    console.error("Looking Glass SSO check failed. The web container could not reach", base, error);
    return loginError(
      "Callback",
      "The web container could not reach the API. Check API_URL from the web container."
    );
  }
  if (res.ok) return true;
  const detail = await responseDetail(res);
  console.error("Looking Glass SSO rejected the sign-in", res.status, detail);
  if (res.status === 403 && detail) return loginError("AccessDenied", detail);
  return loginError(
    "Callback",
    detail || `The API rejected sign-in (${res.status}). Check API_URL and INTERNAL_API_KEY.`
  );
}

const providers = [
  ...(entraConfigured
    ? [
        MicrosoftEntraID({
          clientId: process.env.AUTH_MICROSOFT_ENTRA_ID_ID!,
          clientSecret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET!,
          issuer: `https://login.microsoftonline.com/${process.env.AUTH_MICROSOFT_ENTRA_ID_TENANT_ID}/v2.0`,
          authorization: { params: { scope: "openid profile email User.Read" } },
          // The built-in profile downloads a Graph photo with no timeout and can hold
          // the callback open. Sign-in only needs the id-token claims.
          profile(profile) {
            const record = profile as EntraProfile;
            return {
              id: String(record.oid || record.sub || ""),
              name: record.name,
              email: record.preferred_username || record.email,
            };
          },
        }),
      ]
    : []),
  Credentials({
    id: "break-glass",
    name: "Break-glass",
    credentials: {
      username: { label: "Username", type: "text" },
      password: { label: "Password", type: "password" },
    },
    async authorize(credentials) {
      const username = String(credentials?.username || "").trim();
      const password = String(credentials?.password || "");
      if (!username || !password) return null;
      const userOk = safeEqual(username.toLowerCase(), breakGlassUsername.toLowerCase());
      const passOk = safeEqual(password, breakGlassPassword);
      if (!userOk || !passOk) return null;
      return {
        id: BREAK_GLASS_OID,
        oid: BREAK_GLASS_OID,
        name: "Infra Admin",
        email: `${breakGlassUsername}@lookingglass.local`,
        roles: ["platform_admin"],
        groups: [] as string[],
      };
    },
  }),
];

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  secret: process.env.AUTH_SECRET,
  providers,
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    async signIn({ user, account, profile }) {
      if (!account) return false;
      if (account.provider === "break-glass") return true;
      if (account.provider !== "microsoft-entra-id") return false;
      const p = (profile || {}) as EntraProfile;
      const oid = String(p.oid || p.sub || "");
      if (!oid) return false;
      const groups = await resolveGroups(p, account.access_token);
      const roles = Array.isArray(p.roles) ? p.roles.map(String) : [];
      const ok = await evaluateSso({
        oid,
        email: String(p.preferred_username || p.email || user.email || ""),
        display_name: String(p.name || user.name || ""),
        groups,
        roles,
      });
      if (ok !== true) return ok;
      const next = user as { oid?: string; roles?: string[]; groups?: string[] };
      next.oid = oid;
      next.groups = groups;
      next.roles = roles;
      return true;
    },
    async jwt({ token, user, profile, account }) {
      if (user) {
        const u = user as {
          oid?: string;
          roles?: string[];
          groups?: string[];
          id?: string;
        };
        token.oid = u.oid || u.id;
        token.roles = u.roles || [];
        token.groups = u.groups || [];
      }
      if (account?.provider === "microsoft-entra-id" && profile) {
        const p = profile as EntraProfile;
        token.oid = p.oid || p.sub || token.oid;
        token.roles = Array.isArray(p.roles) ? p.roles : token.roles || [];
        if (Array.isArray(p.groups) && p.groups.length) {
          const current = Array.isArray(token.groups) ? token.groups.map(String) : [];
          token.groups = Array.from(new Set([...current, ...p.groups.map(String)]));
        }
      }
      return token;
    },
    async session({ session, token }) {
      session.user.id = String(token.oid || "");
      session.user.roles = (token.roles as string[]) || [];
      session.user.groups = (token.groups as string[]) || [];
      return session;
    },
  },
});

export const entraEnabled = entraConfigured;
