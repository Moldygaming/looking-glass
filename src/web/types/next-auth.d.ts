import "next-auth";

declare module "next-auth" {
  interface Session {
    user: {
      id: string;
      name?: string | null;
      email?: string | null;
      image?: string | null;
      roles: string[];
      groups: string[];
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    oid?: string;
    roles?: string[];
    groups?: string[];
  }
}
