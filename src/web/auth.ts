import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";

export const demoUsers = {
  admin: {
    id: "demo-admin",
    oid: "demo-admin",
    name: "Avery Chen",
    email: "avery.chen@lookingglass.local",
    roles: ["platform_admin"],
    groups: [] as string[],
  },
  infra: {
    id: "demo-infra",
    oid: "demo-infra",
    name: "Sam Okonkwo",
    email: "sam.okonkwo@lookingglass.local",
    roles: ["analyst"],
    groups: [] as string[],
  },
  project: {
    id: "demo-project",
    oid: "demo-project",
    name: "Priya Shah",
    email: "priya.shah@lookingglass.local",
    roles: ["analyst"],
    groups: [] as string[],
  },
};

const entraConfigured = Boolean(
  process.env.AUTH_MICROSOFT_ENTRA_ID_ID && process.env.AUTH_MICROSOFT_ENTRA_ID_TENANT_ID
);
const demoAllowed = process.env.AUTH_ALLOW_DEMO !== "false";

const providers = [
  ...(entraConfigured
    ? [
        MicrosoftEntraID({
          clientId: process.env.AUTH_MICROSOFT_ENTRA_ID_ID!,
          clientSecret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET!,
          issuer: `https://login.microsoftonline.com/${process.env.AUTH_MICROSOFT_ENTRA_ID_TENANT_ID}/v2.0`,
          authorization: { params: { scope: "openid profile email User.Read" } },
        }),
      ]
    : []),
  ...(demoAllowed
    ? [
        Credentials({
          id: "demo",
          name: "Demo",
          credentials: { persona: { label: "Persona", type: "text" } },
          async authorize(credentials) {
            const persona = String(credentials?.persona || "");
            return demoUsers[persona as keyof typeof demoUsers] ?? null;
          },
        }),
      ]
    : []),
];

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  secret: process.env.AUTH_SECRET,
  providers,
  pages: { signIn: "/login" },
  callbacks: {
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
        const p = profile as {
          oid?: string;
          sub?: string;
          roles?: string[];
          groups?: string[];
          preferred_username?: string;
        };
        token.oid = p.oid || p.sub;
        token.roles = p.roles || token.roles || [];
        token.groups = p.groups || token.groups || [];
        if (p.preferred_username) token.email = p.preferred_username;
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
