import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async redirects() {
    return [
      { source: "/admin/directory", destination: "/entra", permanent: false },
      { source: "/admin/directory/users", destination: "/entra/users", permanent: false },
      { source: "/admin/directory/users/:id", destination: "/entra/users/:id", permanent: false },
      { source: "/admin/directory/groups", destination: "/entra/groups", permanent: false },
      { source: "/admin/directory/groups/:id", destination: "/entra/groups/:id", permanent: false },
      { source: "/admin/directory/apps", destination: "/entra/apps", permanent: false },
      { source: "/admin/directory/apps/:id", destination: "/entra/apps/:id", permanent: false },
    ];
  },
};

export default nextConfig;
